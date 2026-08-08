"""Per-station METAR cache: the thing that makes an on-demand endpoint safe.

The systemd timer this replaces guaranteed at most one upstream call every 5
minutes no matter what the board did. An HTTP endpoint has no such guarantee,
and METARs are issued half-hourly (plus SPECI), so polling harder buys
nothing. A 300s TTL reproduces the old bound; a 60s error backoff stops a
failing upstream turning a polling board into a retry storm.

Serving stale on error is deliberate, and inherited: "A stale METAR is far
better than none." The staleness is reported rather than hidden.

Time is injected so tests can move it without sleeping. Monotonic time drives
TTL and backoff, because a wall-clock step (NTP settling on a Pi with no RTC)
must not expire the cache or freeze it. Wall clock is only recorded for the
envelope's `t`, which must be a real timestamp.
"""

import threading
import time

from .upstream import UpstreamError

DEFAULT_TTL_S = 300
DEFAULT_ERROR_BACKOFF_S = 60


class MetarCache:
    def __init__(self, fetcher, ttl_s=DEFAULT_TTL_S,
                 error_backoff_s=DEFAULT_ERROR_BACKOFF_S,
                 monotonic=time.monotonic, wallclock=time.time):
        self._fetch = fetcher
        self._ttl_s = ttl_s
        self._backoff_s = error_backoff_s
        self._monotonic = monotonic
        self._wallclock = wallclock
        # icao -> {"obs": dict, "mono": float, "wall": float}
        self._entries = {}
        # icao -> monotonic time before which we will not try upstream again
        self._blocked_until = {}
        # One lock for the whole refill. Requests are ~free when cached, and
        # the realistic client count is one board polling once a minute, so
        # per-station locking would be complexity without a payoff. What this
        # does buy is single-flight: concurrent requests for a cold station
        # produce one upstream call, not N.
        self._lock = threading.Lock()

    def get(self, ids):
        now_mono = self._monotonic()
        with self._lock:
            wanted = self._needing_refresh(ids, now_mono)
            if wanted:
                self._refill(wanted, now_mono)
            return self._collect(ids, self._monotonic())

    # -- internals ---------------------------------------------------------

    def _needing_refresh(self, ids, now_mono):
        out = []
        for icao in ids:
            if now_mono < self._blocked_until.get(icao, 0.0):
                continue
            entry = self._entries.get(icao)
            if entry is None or now_mono - entry["mono"] >= self._ttl_s:
                out.append(icao)
        return out

    def _refill(self, ids, now_mono):
        try:
            observations = self._fetch(ids)
        except UpstreamError:
            # Existing entries stay exactly as they are and will be served
            # and reported stale.
            self._block(ids, now_mono)
            return
        wall = self._wallclock()
        seen = set()
        for obs in observations:
            icao = str(obs.get("icaoId") or "")
            if icao not in ids:
                continue  # the API can echo extras; ignore what we did not ask for
            seen.add(icao)
            self._entries[icao] = {"obs": obs, "mono": now_mono, "wall": wall}
            self._blocked_until.pop(icao, None)
        # A station the API has no observation for is a miss, not an error,
        # but it still gets a backoff so a typo'd ICAO cannot be polled at
        # full request rate.
        self._block([i for i in ids if i not in seen], now_mono)

    def _block(self, ids, now_mono):
        until = now_mono + self._backoff_s
        for icao in ids:
            self._blocked_until[icao] = until

    def _collect(self, ids, now_mono):
        served = [self._entries[i] for i in ids if i in self._entries]
        if not served:
            return [], 0, True
        stale = any(now_mono - e["mono"] >= self._ttl_s for e in served)
        stale = stale or len(served) < len(set(ids))
        oldest_wall = min(e["wall"] for e in served)
        return [e["obs"] for e in served], int(oldest_wall), stale
