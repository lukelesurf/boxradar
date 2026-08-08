"""The one place that talks to aviationweather.gov.

Isolated for two reasons. Tests never need the network — cache.py takes a
fetcher callable and is tested with a fake. And this is the TLS boundary that
justifies the whole proxy: terminating it here keeps a ~40KB handshake off an
ESP32 whose heap floor is ~43KB with the render sprite live.
"""

import json
import time
import urllib.error
import urllib.request

from . import VERSION

API = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json"
USER_AGENT = f"boxradar-site/{VERSION} (+local desk toy)"


class UpstreamError(Exception):
    """Any failure to obtain parsed JSON from the upstream API."""


def fetch(ids, timeout_s=20.0):
    """Observations for `ids`, as the API's raw dicts.

    Returns a list, which may be shorter than `ids` — the API omits stations
    it has no observation for rather than returning a placeholder.
    """
    url = API.format(ids=",".join(ids))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # Logged unconditionally, because "did the cache actually go upstream?" is
    # the operational question about this service and request logs alone cannot
    # answer it. One line per real fetch makes the TTL visible in journald.
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = json.load(r)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"upstream: FAILED for {','.join(ids)}: {e}", flush=True)
        raise UpstreamError(f"fetch failed: {e}") from e
    except json.JSONDecodeError as e:
        print(f"upstream: BAD JSON for {','.join(ids)}: {e}", flush=True)
        raise UpstreamError(f"bad JSON upstream: {e}") from e
    if not isinstance(raw, list):
        print(f"upstream: BAD SHAPE for {','.join(ids)}", flush=True)
        raise UpstreamError(f"expected a JSON array, got {type(raw).__name__}")
    obs = [o for o in raw if isinstance(o, dict)]
    ms = (time.monotonic() - started) * 1000
    print(f"upstream: fetched {','.join(ids)} -> {len(obs)} obs in {ms:.0f}ms",
          flush=True)
    return obs
