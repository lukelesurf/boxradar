# METAR Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `tools/metar-feed`'s timer-and-static-file with an on-demand caching HTTP proxy that serves any ICAO station, as the first module of the `tools/boxradar-site` Pi application.

**Architecture:** A stdlib-only Python HTTP service on the receiver Pi, listening on port 8081. `GET /metar/EGSS` returns the exact JSON envelope the board already parses, built from a per-station cache in front of aviationweather.gov. The cache is what makes an on-demand endpoint safe: today's systemd timer guarantees at most one upstream call per 5 minutes, and a 300s TTL preserves that guarantee no matter how often the board asks. Normalisation logic moves verbatim out of `metar_feed.py` into a pure, unit-tested module.

**Tech Stack:** Python 3 standard library only — `http.server.ThreadingHTTPServer`, `urllib.request`, `unittest`. No Flask, no pip, no venv.

## Global Constraints

- **stdlib only.** From `metar_feed.py`: "Debian's Python is externally managed (PEP 668) and this should not need a venv or pip on a receiver box." Phase 2 will need shapely and will decide the venv question then; phase 1 must not force it.
- **Plain HTTP on the LAN.** TLS terminates on the Pi. Per the spec, that is architectural: "a TLS handshake costs tens of KB of transient heap on an ESP32 with no PSRAM that is already holding a 76.8KB sprite, plus a CA bundle in flash."
- **The response envelope does not change.** `lib/radarcore/metar.cpp` and `struct Metar` must not be modified. `loadMetar()` iterates `root["stations"]` matching on `id`, reading `cov`, `rwy`, `wdir`, `wspd`, `gust`, `vis`, `ceil`, `conf`. Adding fields is safe (ArduinoJson ignores unknown keys); removing or renaming any of those is not.
- **The only board change is `METAR_URL`** in `include/config.h` and `include/config.example.h`.
- **Per-station cache with a short TTL, serving stale on upstream error.** From the spec: "the timer currently guarantees at most one upstream call per 5 minutes no matter what the board does. An on-demand proxy can be hammered by a board bug, and METARs are issued half-hourly so there is nothing to gain from polling harder."
- **Target host is the receiver Pi, not the home server.** `ssh pi@192.0.2.10`, hostname `adsb`, Debian, Python 3.11.2, aarch64, passwordless sudo. Nothing in this plan runs as a service on the home server.
- **Python 3.7+.** `install.sh` already enforces this; keep the check.
- Run all Python tests from the repo root with:
  `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`

---

## File Structure

**Created:**

| file | responsibility |
|---|---|
| `tools/boxradar-site/boxradar_site/__init__.py` | package marker, `VERSION` |
| `tools/boxradar-site/boxradar_site/metar.py` | pure normalisation: upstream JSON → fixed-type fields. No network, no clock, no config |
| `tools/boxradar-site/boxradar_site/upstream.py` | the only code that talks to aviationweather.gov. Isolated so tests never touch the network |
| `tools/boxradar-site/boxradar_site/cache.py` | per-station TTL cache, error backoff, batched refill. Clock injected for tests |
| `tools/boxradar-site/boxradar_site/config.py` | reads `/etc/boxradar-site/config.json` — runway tables and `calm_kt` |
| `tools/boxradar-site/boxradar_site/server.py` | routes, ICAO validation, envelope assembly, JSON responses |
| `tools/boxradar-site/boxradar_site/__main__.py` | entry point: parse args, wire modules, serve |
| `tools/boxradar-site/tests/test_metar.py` | normalisation, including every documented upstream weirdness |
| `tools/boxradar-site/tests/test_cache.py` | TTL, backoff, stale-on-error, batching — with a fake clock and fake fetcher |
| `tools/boxradar-site/tests/test_server.py` | real HTTP against a real server on port 0, with a fake cache |
| `tools/boxradar-site/boxradar-site.service` | systemd unit (`Type=simple`, restart always) |
| `tools/boxradar-site/install.sh` | installs the package, the unit and the default config |
| `tools/boxradar-site/README.md` | what it is, how to install, how to verify |

**Modified:** `include/config.h`, `include/config.example.h`, `README.md`, `SPEC.md`
**Deleted (last task only):** `tools/metar-feed/`

Why the split: `metar.py` is pure and is where the value is — the normalisation rules encode hard-won knowledge about a loose API, and they are the thing most worth testing. Keeping the clock in `cache.py` and the socket in `upstream.py` is what lets `metar.py` be tested with plain function calls.

---

### Task 1: Normalisation module

Move the pure functions out of `metar_feed.py` unchanged in behaviour, parameterise the module-level `CALM_KT`, and fix one latent crash: `pick_runway()` currently calls `max()` on the runway list, which raises `ValueError` on an empty list. Today that is unreachable because `build()` skips stations absent from `STATIONS`; the proxy serves arbitrary stations, so it becomes reachable.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/__init__.py`
- Create: `tools/boxradar-site/boxradar_site/metar.py`
- Test: `tools/boxradar-site/tests/test_metar.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_CALM_KT: int = 7`
  - `as_int(v, default: int = 0) -> int`
  - `visibility_m(v) -> int`
  - `ceiling(clouds) -> tuple[int, str]`
  - `pick_runway(wdir, wspd, runways: list[tuple[str, int]], calm_kt: int = DEFAULT_CALM_KT) -> tuple[str, bool]`
  - `normalise(obs: dict, runways: list[tuple[str, int]], calm_kt: int = DEFAULT_CALM_KT) -> dict`
  - `envelope(stations: list[dict], fetched_at: int, stale: bool = False) -> dict`

- [ ] **Step 1: Create the package marker**

Create `tools/boxradar-site/boxradar_site/__init__.py`:

```python
"""BOXRADAR site application — runs on the receiver Pi.

Phase 1 is the METAR proxy. Later phases add the geography generator and the
site configuration UI. See
docs/superpowers/specs/2026-08-08-runtime-site-config-design.md
"""

VERSION = "1.0.0"
```

- [ ] **Step 2: Create the empty tests directory marker**

Create `tools/boxradar-site/tests/__init__.py` as an empty file:

```python
```

- [ ] **Step 3: Write the failing tests**

Create `tools/boxradar-site/tests/test_metar.py`:

```python
import unittest

from boxradar_site import metar


class TestAsInt(unittest.TestCase):
    def test_none_gives_default(self):
        self.assertEqual(metar.as_int(None, -1), -1)

    def test_bool_is_not_a_number(self):
        # bool is an int subclass in Python; treating True as 1 would turn a
        # flag into a wind speed.
        self.assertEqual(metar.as_int(True, 0), 0)

    def test_float_truncates(self):
        self.assertEqual(metar.as_int(12.7), 12)

    def test_string_gives_default(self):
        self.assertEqual(metar.as_int("VRB", -1), -1)


class TestVisibility(unittest.TestCase):
    def test_plus_suffix_is_unlimited(self):
        # The API reports "6+" for 6 statute miles or more. 9999 is the METAR
        # convention for "10km or more".
        self.assertEqual(metar.visibility_m("6+"), 9999)

    def test_numeric_string_converts_from_statute_miles(self):
        self.assertEqual(metar.visibility_m("3"), 4827)

    def test_number_converts_and_clamps(self):
        self.assertEqual(metar.visibility_m(2), 3218)
        self.assertEqual(metar.visibility_m(10), 9999)

    def test_garbage_is_unlimited_not_zero(self):
        # Zero would render as fog. Unknown must not look like the worst case.
        self.assertEqual(metar.visibility_m("who knows"), 9999)
        self.assertEqual(metar.visibility_m(None), 9999)


class TestCeiling(unittest.TestCase):
    def test_no_clouds(self):
        self.assertEqual(metar.ceiling([]), (0, "NCD"))
        self.assertEqual(metar.ceiling(None), (0, "NCD"))

    def test_few_only_has_no_ceiling_but_reports_cover(self):
        # 0 feet means no ceiling, which is NOT the same as no cloud.
        self.assertEqual(metar.ceiling([{"cover": "FEW", "base": 1200}]),
                         (0, "FEW"))

    def test_ceiling_is_lowest_bkn_or_ovc_cover_is_lowest_any(self):
        clouds = [{"cover": "FEW", "base": 1200},
                  {"cover": "BKN", "base": 2500},
                  {"cover": "OVC", "base": 4000}]
        self.assertEqual(metar.ceiling(clouds), (2500, "FEW"))

    def test_ignores_non_dict_layers(self):
        self.assertEqual(metar.ceiling([None, {"cover": "OVC", "base": 900}]),
                         (900, "OVC"))


class TestPickRunway(unittest.TestCase):
    RWYS = [("04", 43), ("22", 223)]

    def test_variable_wind_gives_no_runway(self):
        self.assertEqual(metar.pick_runway("VRB", 10, self.RWYS), ("", False))

    def test_missing_wind_gives_no_runway(self):
        self.assertEqual(metar.pick_runway(None, 10, self.RWYS), ("", False))

    def test_bool_is_not_a_direction(self):
        self.assertEqual(metar.pick_runway(True, 10, self.RWYS), ("", False))

    def test_empty_runway_table_gives_no_runway(self):
        # Reachable now that the proxy serves stations with no configured
        # runways. max() on an empty sequence would raise.
        self.assertEqual(metar.pick_runway(40, 10, []), ("", False))

    def test_greatest_headwind_component_wins(self):
        self.assertEqual(metar.pick_runway(40, 12, self.RWYS), ("04", True))
        self.assertEqual(metar.pick_runway(220, 12, self.RWYS), ("22", True))

    def test_light_wind_is_not_confident(self):
        # Confidence is not about the arithmetic; it is about whether wind is
        # deciding the runway at all.
        self.assertEqual(metar.pick_runway(40, 5, self.RWYS), ("04", False))

    def test_calm_threshold_is_inclusive_and_configurable(self):
        self.assertEqual(metar.pick_runway(40, 7, self.RWYS), ("04", True))
        self.assertEqual(metar.pick_runway(40, 7, self.RWYS, calm_kt=10),
                         ("04", False))


class TestNormalise(unittest.TestCase):
    RWYS = [("04", 43), ("22", 223)]

    def test_full_observation(self):
        obs = {"icaoId": "EGSS", "wdir": 43, "wspd": 12, "wgst": 20,
               "visib": "6+", "clouds": [{"cover": "BKN", "base": 2500}],
               "altim": 1013, "temp": 14, "obsTime": 1754639400}
        self.assertEqual(metar.normalise(obs, self.RWYS), {
            "id": "EGSS", "wdir": 43, "wspd": 12, "gust": 20, "vis": 9999,
            "ceil": 2500, "cov": "BKN", "qnh": 1013, "temp": 14,
            "rwy": "04", "conf": 1, "obs": 1754639400,
        })

    def test_variable_wind_direction_is_minus_one_not_zero(self):
        # 0 would render as due north.
        out = metar.normalise({"icaoId": "EGSS", "wdir": "VRB"}, self.RWYS)
        self.assertEqual(out["wdir"], -1)
        self.assertEqual(out["rwy"], "")
        self.assertEqual(out["conf"], 0)

    def test_empty_observation_yields_every_key(self):
        # The firmware's struct has no optional fields; every key must exist.
        out = metar.normalise({}, [])
        self.assertEqual(set(out), {"id", "wdir", "wspd", "gust", "vis",
                                    "ceil", "cov", "qnh", "temp", "rwy",
                                    "conf", "obs"})
        self.assertEqual(out["id"], "")
        self.assertEqual(out["cov"], "NCD")
        self.assertEqual(out["vis"], 9999)

    def test_null_gust_becomes_zero(self):
        out = metar.normalise({"icaoId": "EGSS", "wgst": None}, self.RWYS)
        self.assertEqual(out["gust"], 0)


class TestEnvelope(unittest.TestCase):
    def test_shape_matches_what_loadmetar_parses(self):
        # lib/radarcore/metar.cpp iterates root["stations"] matching on "id".
        env = metar.envelope([{"id": "EGSS"}], 1754640000)
        self.assertEqual(env, {"t": 1754640000, "stale": 0,
                               "stations": [{"id": "EGSS"}]})

    def test_stale_flag(self):
        env = metar.envelope([], 1754640000, stale=True)
        self.assertEqual(env["stale"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL with `ImportError: cannot import name 'metar' from 'boxradar_site'`

- [ ] **Step 5: Write the implementation**

Create `tools/boxradar-site/boxradar_site/metar.py`:

```python
"""Normalise aviationweather.gov METAR JSON into fixed-type fields.

Moved from tools/metar-feed/metar_feed.py, where this ran on a timer and
wrote a static file. The reasoning is unchanged and still load-bearing:

The upstream API is loose in ways that would silently corrupt an embedded
parse — `visib` may be the string "6+", `wdir` may be "VRB", `wgst` may be
null, `clouds` may be []. Everything here normalises to fixed-type,
always-present fields so the firmware can never coerce a surprise into a
plausible-looking zero.

Pure functions: no network, no clock, no config, no I/O.
"""

import math

# Below this the wind is not choosing the runway; the airfield will be using
# its noise-preferential or default direction instead. Set at 7 rather than 5
# because observations here routinely sit at 4-5kt with 60-80 degrees of
# variability (e.g. "14005KT 120V180"), and calling that confident overstates
# what is known. The API does not expose the variable range as a field, so
# speed is the only proxy available without parsing rawOb.
DEFAULT_CALM_KT = 7

# METAR convention for "10km or more", which is what the raw observation
# carries. Unknown visibility maps here rather than to 0, which would render
# as fog.
VIS_UNLIMITED_M = 9999

M_PER_STATUTE_MILE = 1609


def as_int(v, default=0):
    """Coerce the API's mixed types to an int, without inventing data.

    bool is excluded explicitly: it is an int subclass in Python, so a stray
    flag would otherwise become a wind speed of 1.
    """
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    return default


def visibility_m(v):
    """Statute miles (sometimes as the string '6+') to metres."""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("+"):
            return VIS_UNLIMITED_M
        try:
            v = float(s)
        except ValueError:
            return VIS_UNLIMITED_M
    if isinstance(v, bool):
        return VIS_UNLIMITED_M
    if isinstance(v, (int, float)):
        return min(VIS_UNLIMITED_M, int(v * M_PER_STATUTE_MILE))
    return VIS_UNLIMITED_M


def ceiling(clouds):
    """(ceiling_ft, cover_of_lowest_layer).

    Ceiling is the lowest broken/overcast base. 0 feet means no ceiling,
    which is not the same as no cloud — hence returning the cover of the
    lowest layer of any kind separately.
    """
    if not isinstance(clouds, list) or not clouds:
        return 0, "NCD"
    lowest_any, ceil_ft = None, 0
    for layer in clouds:
        if not isinstance(layer, dict):
            continue
        base = as_int(layer.get("base"), -1)
        cover = str(layer.get("cover") or "")
        if base >= 0 and (lowest_any is None or base < lowest_any[0]):
            lowest_any = (base, cover)
        if cover in ("BKN", "OVC", "OVX") and base >= 0:
            if ceil_ft == 0 or base < ceil_ft:
                ceil_ft = base
    cover = lowest_any[1] if lowest_any else "NCD"
    return ceil_ft, cover or "NCD"


def pick_runway(wdir, wspd, runways, calm_kt=DEFAULT_CALM_KT):
    """Runway whose heading gives the greatest headwind component.

    Returns (name, confident). Confidence is NOT about the arithmetic — it is
    about whether wind is the deciding factor at all. In light or variable
    conditions the answer is a guess, and the display should say so rather
    than assert a runway the airfield isn't using.

    An empty runway table returns no runway. The old timer-based script could
    not reach that case because it skipped stations absent from STATIONS; the
    proxy serves any station asked for, so it can.
    """
    if not runways:
        return "", False
    if not isinstance(wdir, (int, float)) or isinstance(wdir, bool):
        return "", False  # "VRB" or missing
    best = max(runways, key=lambda r: math.cos(math.radians(wdir - r[1])))
    return best[0], as_int(wspd) >= calm_kt


def normalise(obs, runways, calm_kt=DEFAULT_CALM_KT):
    """One upstream observation dict to the flat form the firmware parses.

    Every key is always present with a fixed type. lib/radarcore/metar.cpp
    reads id, cov, rwy, wdir, wspd, gust, vis, ceil and conf; qnh, temp and
    obs are carried for future use and for humans reading curl output.
    """
    wdir_raw = obs.get("wdir")
    wspd = as_int(obs.get("wspd"))
    rwy, confident = pick_runway(wdir_raw, wspd, runways, calm_kt)
    ceil_ft, cover = ceiling(obs.get("clouds"))
    return {
        "id": str(obs.get("icaoId") or ""),
        # -1 rather than 0 for variable: 0 would read as due north.
        "wdir": as_int(wdir_raw, -1),
        "wspd": wspd,
        "gust": as_int(obs.get("wgst")),
        "vis": visibility_m(obs.get("visib")),
        "ceil": ceil_ft,
        "cov": cover,
        "qnh": as_int(obs.get("altim")),
        "temp": as_int(obs.get("temp")),
        "rwy": rwy,
        "conf": 1 if confident else 0,
        "obs": as_int(obs.get("obsTime")),
    }


def envelope(stations, fetched_at, stale=False):
    """The response body.

    Shape is fixed by lib/radarcore/metar.cpp, which iterates
    root["stations"] matching on "id". `t` is the wall-clock time of the
    UPSTREAM fetch, not of this response, so it does not falsely refresh when
    a cached entry is served. `stale` is additive and currently unused by the
    firmware; ArduinoJson ignores keys it does not read.
    """
    return {"t": int(fetched_at), "stale": 1 if stale else 0,
            "stations": stations}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 25 tests

- [ ] **Step 7: Commit**

```bash
git add tools/boxradar-site/boxradar_site/__init__.py \
        tools/boxradar-site/boxradar_site/metar.py \
        tools/boxradar-site/tests/__init__.py \
        tools/boxradar-site/tests/test_metar.py
git commit -m "feat: extract METAR normalisation into a tested module

Moved verbatim from tools/metar-feed/metar_feed.py, with CALM_KT
parameterised and one latent crash fixed: pick_runway() called max() on the
runway list, which raises on an empty one. Unreachable while stations came
from a hardcoded dict; reachable once the proxy serves any station asked for."
```

---

### Task 2: Upstream fetch

The only module that opens a socket. Isolated so no test ever touches the network and so the TLS-termination boundary is one file.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/upstream.py`

**Interfaces:**
- Consumes: `boxradar_site.VERSION`
- Produces:
  - `class UpstreamError(Exception)`
  - `fetch(ids: list[str], timeout_s: float = 20.0) -> list[dict]` — raises `UpstreamError` on any network, timeout or JSON failure.

- [ ] **Step 1: Write the implementation**

There is no unit test for this module: it is a thin adapter whose entire behaviour is "call the network and translate exceptions". Task 3 tests everything that consumes it, with a fake. Task 7 verifies it against the real API on the Pi.

Create `tools/boxradar-site/boxradar_site/upstream.py`:

```python
"""The one place that talks to aviationweather.gov.

Isolated for two reasons. Tests never need the network — cache.py takes a
fetcher callable and is tested with a fake. And this is the TLS boundary that
justifies the whole proxy: terminating it here keeps a ~40KB handshake off an
ESP32 whose heap floor is ~43KB with the render sprite live.
"""

import json
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
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = json.load(r)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpstreamError(f"fetch failed: {e}") from e
    except json.JSONDecodeError as e:
        raise UpstreamError(f"bad JSON upstream: {e}") from e
    if not isinstance(raw, list):
        raise UpstreamError(f"expected a JSON array, got {type(raw).__name__}")
    return [obs for obs in raw if isinstance(obs, dict)]
```

- [ ] **Step 2: Verify it imports and the module is syntactically sound**

Run: `python3 -c "import sys; sys.path.insert(0, 'tools/boxradar-site'); from boxradar_site import upstream; print(upstream.USER_AGENT)"`
Expected: prints `boxradar-site/1.0.0 (+local desk toy)`

- [ ] **Step 3: Commit**

```bash
git add tools/boxradar-site/boxradar_site/upstream.py
git commit -m "feat: isolate the aviationweather upstream fetch

One module owns the socket and the TLS boundary, so the cache can be tested
with a fake fetcher and nothing else in the package imports urllib."
```

---

### Task 3: Cache with TTL, batching and error backoff

This task is what makes an on-demand endpoint safe. Today's timer bounds upstream load at one call per 5 minutes; a 300s TTL reproduces that bound regardless of how often the board polls, and a 60s error backoff stops a failing upstream turning a polling board into a retry storm.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/cache.py`
- Test: `tools/boxradar-site/tests/test_cache.py`

**Interfaces:**
- Consumes: `boxradar_site.upstream.UpstreamError`
- Produces:
  - `DEFAULT_TTL_S: int = 300`
  - `DEFAULT_ERROR_BACKOFF_S: int = 60`
  - `class MetarCache(fetcher, ttl_s=DEFAULT_TTL_S, error_backoff_s=DEFAULT_ERROR_BACKOFF_S, monotonic=time.monotonic, wallclock=time.time)`
    - `get(ids: list[str]) -> tuple[list[dict], int, bool]` — `(raw observation dicts, wall-clock time of the oldest entry served, whether any served entry is past its TTL)`. Returns `([], 0, True)` when nothing is available.

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_cache.py`:

```python
import unittest

from boxradar_site.cache import MetarCache
from boxradar_site.upstream import UpstreamError


class FakeClock:
    """Injected for both monotonic and wall-clock reads, so tests can move
    time without sleeping."""

    def __init__(self, t=1000.0):
        self.t = t

    def advance(self, dt):
        self.t += dt

    def __call__(self):
        return self.t


class FakeFetcher:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.responses = {}

    def __call__(self, ids, timeout_s=20.0):
        self.calls.append(list(ids))
        if self.fail:
            raise UpstreamError("boom")
        return [self.responses[i] for i in ids if i in self.responses]


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.fetcher = FakeFetcher()
        self.fetcher.responses = {
            "EGSS": {"icaoId": "EGSS", "wspd": 12},
            "EGGW": {"icaoId": "EGGW", "wspd": 8},
        }
        self.cache = MetarCache(self.fetcher, ttl_s=300, error_backoff_s=60,
                                monotonic=self.clock, wallclock=self.clock)


class TestFreshFetch(CacheTest):
    def test_first_call_fetches(self):
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(self.fetcher.calls, [["EGSS"]])
        self.assertEqual(obs, [{"icaoId": "EGSS", "wspd": 12}])
        self.assertEqual(at, 1000)
        self.assertFalse(stale)

    def test_second_call_within_ttl_does_not_fetch(self):
        self.cache.get(["EGSS"])
        self.clock.advance(299)
        obs, _, stale = self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 1)
        self.assertEqual(len(obs), 1)
        self.assertFalse(stale)

    def test_call_after_ttl_refetches(self):
        self.cache.get(["EGSS"])
        self.clock.advance(301)
        self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_ttl_bounds_upstream_calls_regardless_of_poll_rate(self):
        # A board polling every 60s for an hour must produce 12 calls, not 60.
        for _ in range(60):
            self.cache.get(["EGSS"])
            self.clock.advance(60)
        self.assertEqual(len(self.fetcher.calls), 12)


class TestBatching(CacheTest):
    def test_multiple_stations_are_one_upstream_call(self):
        self.cache.get(["EGSS", "EGGW"])
        self.assertEqual(self.fetcher.calls, [["EGSS", "EGGW"]])

    def test_only_expired_stations_are_refetched(self):
        self.cache.get(["EGSS"])
        self.clock.advance(100)
        self.cache.get(["EGSS", "EGGW"])
        # EGSS is still fresh, so only EGGW goes upstream.
        self.assertEqual(self.fetcher.calls, [["EGSS"], ["EGGW"]])

    def test_returns_every_station_it_holds(self):
        self.cache.get(["EGSS"])
        obs, _, _ = self.cache.get(["EGSS", "EGGW"])
        ids = sorted(o["icaoId"] for o in obs)
        self.assertEqual(ids, ["EGGW", "EGSS"])

    def test_oldest_entry_sets_the_timestamp(self):
        self.cache.get(["EGSS"])
        self.clock.advance(100)
        _, at, _ = self.cache.get(["EGSS", "EGGW"])
        self.assertEqual(at, 1000)  # EGSS's fetch time, not EGGW's


class TestUpstreamFailure(CacheTest):
    def test_failure_with_no_prior_data_returns_empty(self):
        self.fetcher.fail = True
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(obs, [])
        self.assertEqual(at, 0)
        self.assertTrue(stale)

    def test_failure_serves_stale_data_flagged_stale(self):
        self.cache.get(["EGSS"])
        self.clock.advance(400)
        self.fetcher.fail = True
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(obs, [{"icaoId": "EGSS", "wspd": 12}])
        self.assertEqual(at, 1000)
        self.assertTrue(stale)

    def test_backoff_suppresses_retries(self):
        self.fetcher.fail = True
        self.cache.get(["EGSS"])
        self.clock.advance(59)
        self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 1)

    def test_backoff_expires(self):
        self.fetcher.fail = True
        self.cache.get(["EGSS"])
        self.clock.advance(61)
        self.cache.get(["EGSS"])
        self.assertEqual(len(self.fetcher.calls), 2)

    def test_recovery_clears_stale(self):
        self.fetcher.fail = True
        self.cache.get(["EGSS"])
        self.clock.advance(61)
        self.fetcher.fail = False
        obs, at, stale = self.cache.get(["EGSS"])
        self.assertEqual(len(obs), 1)
        self.assertEqual(at, 1061)
        self.assertFalse(stale)


class TestMissingUpstreamStation(CacheTest):
    def test_station_the_api_does_not_know_is_not_cached_but_is_backed_off(self):
        # The API omits stations it has no observation for. Treat that as a
        # miss with backoff, so a typo'd ICAO cannot be polled at full rate.
        obs, _, stale = self.cache.get(["ZZZZ"])
        self.assertEqual(obs, [])
        self.assertTrue(stale)
        self.clock.advance(59)
        self.cache.get(["ZZZZ"])
        self.assertEqual(len(self.fetcher.calls), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.cache'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/cache.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 39 tests total

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/cache.py \
        tools/boxradar-site/tests/test_cache.py
git commit -m "feat: per-station METAR cache with TTL and error backoff

The timer this replaces bounded upstream load at one call per 5 minutes no
matter what the board did. A 300s TTL reproduces that bound for an on-demand
endpoint, and a 60s backoff stops a failing upstream turning a polling board
into a retry storm. Stale is served rather than withheld, and flagged.

TTL and backoff run on monotonic time so NTP settling on an RTC-less Pi
cannot expire or freeze the cache; wall clock is recorded only for the
envelope timestamp."
```

---

### Task 4: Runway table configuration

The runway headings that `pick_runway()` needs cannot come from the request — the proxy serves arbitrary ICAOs. They move from the hardcoded `STATIONS` dict into a JSON file that phase 4's web UI will later own.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/config.py`
- Test: `tools/boxradar-site/tests/test_config.py`

**Interfaces:**
- Consumes: `boxradar_site.metar.DEFAULT_CALM_KT`
- Produces:
  - `DEFAULT_PATH: str = "/etc/boxradar-site/config.json"`
  - `class SiteConfig` with attributes `runways: dict[str, list[tuple[str, int]]]` and `calm_kt: int`, and method `runways_for(icao: str) -> list[tuple[str, int]]`
  - `load(path: str = DEFAULT_PATH) -> SiteConfig` — never raises; a missing or malformed file yields empty runways and the default `calm_kt`, with a warning on stderr.

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_config.py`:

```python
import json
import os
import tempfile
import unittest

from boxradar_site import config


class ConfigTest(unittest.TestCase):
    def write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        self.addCleanup(os.unlink, path)
        return path


class TestLoad(ConfigTest):
    def test_missing_file_is_not_an_error(self):
        # The proxy must serve wind and cloud for any station even with no
        # config at all; only the runway recommendation needs one.
        cfg = config.load("/nonexistent/boxradar/config.json")
        self.assertEqual(cfg.runways, {})
        self.assertEqual(cfg.calm_kt, 7)

    def test_malformed_json_is_not_an_error(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{not json")
        self.addCleanup(os.unlink, path)
        cfg = config.load(path)
        self.assertEqual(cfg.runways, {})

    def test_reads_runways_and_calm_kt(self):
        path = self.write({"runways": {"EGSS": [["04", 43], ["22", 223]]},
                           "calm_kt": 9})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("EGSS"), [("04", 43), ("22", 223)])
        self.assertEqual(cfg.calm_kt, 9)

    def test_icao_lookup_is_case_insensitive(self):
        path = self.write({"runways": {"EGSS": [["04", 43]]}})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("egss"), [("04", 43)])

    def test_unknown_station_has_no_runways(self):
        path = self.write({"runways": {"EGSS": [["04", 43]]}})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("EGLL"), [])

    def test_malformed_runway_entries_are_dropped_not_fatal(self):
        path = self.write({"runways": {
            "EGSS": [["04", 43], ["22"], "nonsense", ["23", "not a number"]],
        }})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("EGSS"), [("04", 43)])

    def test_non_integer_calm_kt_falls_back_to_default(self):
        path = self.write({"calm_kt": "seven"})
        self.assertEqual(config.load(path).calm_kt, 7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.config'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/config.py`:

```python
"""Site configuration: runway headings, and the calm-wind threshold.

The runway table cannot come from the request — the proxy serves whatever
ICAO is asked for, and headings are published data the caller does not have.
It moves here from the STATIONS dict that used to sit at the top of
metar_feed.py. Phase 4's web UI takes ownership of this file.

Nothing here raises. A missing or broken config must not stop the proxy
serving wind, cloud and visibility: only the runway recommendation depends on
it, and pick_runway() already degrades to no-runway on an empty table.

NOTE headings are TRUE, not magnetic. Runway designators are magnetic and
rounded to 10 degrees, so 05 is not 050.
"""

import json
import os
import sys

from .metar import DEFAULT_CALM_KT

DEFAULT_PATH = "/etc/boxradar-site/config.json"


class SiteConfig:
    def __init__(self, runways=None, calm_kt=DEFAULT_CALM_KT):
        self.runways = runways or {}
        self.calm_kt = calm_kt

    def runways_for(self, icao):
        return self.runways.get(str(icao).upper(), [])


def _clean_runways(raw):
    """Drop anything malformed rather than failing the whole file.

    A typo in one airfield's table must not cost the other airfields their
    runway recommendation.
    """
    out = {}
    if not isinstance(raw, dict):
        return out
    for icao, entries in raw.items():
        if not isinstance(entries, list):
            continue
        pairs = []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            name, heading = entry
            if isinstance(heading, bool) or not isinstance(heading, (int, float)):
                continue
            pairs.append((str(name), int(heading)))
        if pairs:
            out[str(icao).upper()] = pairs
    return out


def load(path=DEFAULT_PATH):
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return SiteConfig()
    except (OSError, json.JSONDecodeError) as e:
        print(f"boxradar-site: ignoring unreadable {path}: {e}",
              file=sys.stderr)
        return SiteConfig()
    if not isinstance(raw, dict):
        print(f"boxradar-site: ignoring {path}: expected a JSON object",
              file=sys.stderr)
        return SiteConfig()
    calm = raw.get("calm_kt", DEFAULT_CALM_KT)
    if isinstance(calm, bool) or not isinstance(calm, (int, float)):
        calm = DEFAULT_CALM_KT
    return SiteConfig(_clean_runways(raw.get("runways")), int(calm))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 46 tests total

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/config.py \
        tools/boxradar-site/tests/test_config.py
git commit -m "feat: runway tables from a config file instead of a dict

Headings cannot come from the request, so they move out of metar_feed.py's
STATIONS dict into /etc/boxradar-site/config.json. Loading never raises: a
broken file costs the runway recommendation, not the wind and cloud."
```

---

### Task 5: HTTP server and routes

**Files:**
- Create: `tools/boxradar-site/boxradar_site/server.py`
- Test: `tools/boxradar-site/tests/test_server.py`

**Interfaces:**
- Consumes: `boxradar_site.metar.normalise`, `boxradar_site.metar.envelope`, `boxradar_site.config.SiteConfig`, `boxradar_site.cache.MetarCache` (duck-typed: anything with `get(ids)`)
- Produces:
  - `MAX_IDS: int = 8`
  - `parse_ids(segment: str) -> list[str] | None` — uppercased list, or `None` if invalid
  - `make_server(addr: tuple[str, int], cache, cfg) -> http.server.ThreadingHTTPServer`

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_server.py`:

```python
import json
import threading
import unittest
import urllib.error
import urllib.request

from boxradar_site import server
from boxradar_site.config import SiteConfig


class FakeCache:
    def __init__(self):
        self.observations = []
        self.at = 1754640000
        self.stale = False
        self.asked = []

    def get(self, ids):
        self.asked.append(list(ids))
        return self.observations, self.at, self.stale


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.cache = FakeCache()
        self.cfg = SiteConfig({"EGSS": [("04", 43), ("22", 223)]})
        # Port 0 lets the OS choose, so tests never collide with the real
        # service or with each other.
        self.httpd = server.make_server(("127.0.0.1", 0), self.cache, self.cfg)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.load(r)

    def get_expecting_error(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
        self.fail("expected an HTTP error")


class TestParseIds(unittest.TestCase):
    def test_single(self):
        self.assertEqual(server.parse_ids("EGSS"), ["EGSS"])

    def test_lowercase_is_accepted_and_uppercased(self):
        self.assertEqual(server.parse_ids("egss"), ["EGSS"])

    def test_comma_list(self):
        self.assertEqual(server.parse_ids("EGSS,EGGW"), ["EGSS", "EGGW"])

    def test_duplicates_collapse(self):
        self.assertEqual(server.parse_ids("EGSS,EGSS"), ["EGSS"])

    def test_wrong_length_rejected(self):
        self.assertIsNone(server.parse_ids("EGS"))
        self.assertIsNone(server.parse_ids("EGSSX"))

    def test_non_alpha_rejected(self):
        # This is an unauthenticated service that makes outbound requests.
        # The id list goes into an upstream URL, so it is validated, not
        # trusted.
        self.assertIsNone(server.parse_ids("EG.."))
        self.assertIsNone(server.parse_ids("../../etc/passwd"))
        self.assertIsNone(server.parse_ids("EGSS&foo=1"))

    def test_empty_rejected(self):
        self.assertIsNone(server.parse_ids(""))

    def test_too_many_rejected(self):
        self.assertIsNone(server.parse_ids(",".join(["EGSS"] * 9)))


class TestMetarRoute(ServerTest):
    def test_envelope_shape_is_what_loadmetar_parses(self):
        self.cache.observations = [{"icaoId": "EGSS", "wdir": 43, "wspd": 12,
                                    "visib": "6+",
                                    "clouds": [{"cover": "BKN",
                                                "base": 2500}]}]
        status, body = self.get("/metar/EGSS")
        self.assertEqual(status, 200)
        self.assertEqual(body["t"], 1754640000)
        self.assertEqual(body["stale"], 0)
        self.assertEqual(len(body["stations"]), 1)
        station = body["stations"][0]
        self.assertEqual(station["id"], "EGSS")
        self.assertEqual(station["rwy"], "04")
        self.assertEqual(station["conf"], 1)
        self.assertEqual(station["cov"], "BKN")
        self.assertEqual(station["ceil"], 2500)
        self.assertEqual(station["vis"], 9999)

    def test_station_without_a_runway_table_still_serves_weather(self):
        self.cache.observations = [{"icaoId": "EGLL", "wdir": 90, "wspd": 15}]
        _, body = self.get("/metar/EGLL")
        station = body["stations"][0]
        self.assertEqual(station["rwy"], "")
        self.assertEqual(station["conf"], 0)
        self.assertEqual(station["wspd"], 15)

    def test_lowercase_path_works(self):
        self.cache.observations = [{"icaoId": "EGSS"}]
        status, _ = self.get("/metar/egss")
        self.assertEqual(status, 200)
        self.assertEqual(self.cache.asked, [["EGSS"]])

    def test_stale_is_reported(self):
        self.cache.observations = [{"icaoId": "EGSS"}]
        self.cache.stale = True
        _, body = self.get("/metar/EGSS")
        self.assertEqual(body["stale"], 1)

    def test_no_data_at_all_is_503(self):
        self.cache.observations = []
        status, body = self.get_expecting_error("/metar/EGSS")
        self.assertEqual(status, 503)
        self.assertIn("error", body)

    def test_invalid_id_is_400(self):
        status, body = self.get_expecting_error("/metar/NOPE!")
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.cache.asked, [])  # never reached the cache

    def test_response_is_not_cached_by_intermediaries(self):
        self.cache.observations = [{"icaoId": "EGSS"}]
        url = f"http://127.0.0.1:{self.port}/metar/EGSS"
        with urllib.request.urlopen(url, timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "application/json")
            self.assertEqual(r.headers["Cache-Control"], "no-store")


class TestHealthRoute(ServerTest):
    def test_healthz(self):
        status, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("version", body)

    def test_unknown_path_is_404(self):
        status, body = self.get_expecting_error("/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_bare_metar_without_a_station_is_400(self):
        # /metar/ matches the route prefix, so it reaches the id parser and
        # is rejected there rather than 404ing. Either would be defensible;
        # this is what the code does and the message is the useful one.
        status, body = self.get_expecting_error("/metar/")
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.server'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/server.py`:

```python
"""HTTP routes for the site application.

    GET /metar/EGSS         one station
    GET /metar/EGSS,EGGW    several, in one upstream call
    GET /healthz            liveness

The /metar response envelope is fixed by lib/radarcore/metar.cpp and must not
change shape: it iterates root["stations"] matching on "id". Extra keys are
safe — ArduinoJson ignores what it does not read.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION
from .metar import envelope, normalise

# ICAO location indicators are four letters. Validated rather than trusted:
# this is an unauthenticated LAN service and the value is interpolated into an
# outbound URL, so a permissive parser here would be an open relay with extra
# steps. The cap bounds a single upstream request.
MAX_IDS = 8
_ICAO_RE = re.compile(r"^[A-Z]{4}$")


def parse_ids(segment):
    """Uppercased ICAO list, or None if the segment is not acceptable."""
    if not segment:
        return None
    seen, out = set(), []
    for part in segment.upper().split(","):
        if not _ICAO_RE.match(part):
            return None
        if part not in seen:
            seen.add(part)
            out.append(part)
    if not out or len(out) > MAX_IDS:
        return None
    return out


def _make_handler(cache, cfg):
    class Handler(BaseHTTPRequestHandler):
        # Keep-alive matters: the board polls one URL every 60s over the LAN,
        # and HTTP/1.0 would make every poll a fresh connection.
        protocol_version = "HTTP/1.1"
        server_version = f"boxradar-site/{VERSION}"

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, {"ok": True, "version": VERSION})
                return
            if path.startswith("/metar/"):
                self._metar(path[len("/metar/"):])
                return
            self._json(404, {"error": "not found"})

        def _metar(self, segment):
            ids = parse_ids(segment)
            if ids is None:
                self._json(400, {"error": "expected one to "
                                          f"{MAX_IDS} four-letter ICAO codes"})
                return
            observations, fetched_at, stale = cache.get(ids)
            if not observations:
                # Nothing cached and nothing upstream. 503 rather than an
                # empty 200: the board keeps its last good reading on a
                # non-200, and an empty stations array would look like a
                # successful publish with no weather in it.
                self._json(503, {"error": "no observation available"})
                return
            stations = [
                normalise(obs, cfg.runways_for(obs.get("icaoId") or ""),
                          cfg.calm_kt)
                for obs in observations
            ]
            self._json(200, envelope(stations, fetched_at, stale))

        def _json(self, status, payload):
            body = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Default goes to stderr with a timestamp systemd already adds.
            print(f"{self.address_string()} {fmt % args}", flush=True)

    return Handler


def make_server(addr, cache, cfg):
    """Threading so a slow upstream fetch cannot block an unrelated request.

    Pass port 0 to let the OS choose — used by the tests.
    """
    return ThreadingHTTPServer(addr, _make_handler(cache, cfg))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 64 tests total

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/server.py \
        tools/boxradar-site/tests/test_server.py
git commit -m "feat: HTTP routes for the METAR proxy

GET /metar/<icao[,icao...]> returns the exact envelope
lib/radarcore/metar.cpp already parses, so the board needs no code change.
ICAO codes are validated against ^[A-Z]{4}$ rather than trusted: the value is
interpolated into an outbound URL on an unauthenticated LAN service.

503 rather than an empty 200 when there is no observation, because the
firmware keeps its last good reading on a non-200 and an empty stations array
would look like a successful publish with no weather in it."
```

---

### Task 6: Entry point, systemd unit and installer

**Files:**
- Create: `tools/boxradar-site/boxradar_site/__main__.py`
- Create: `tools/boxradar-site/boxradar-site.service`
- Create: `tools/boxradar-site/install.sh`
- Create: `tools/boxradar-site/README.md`

**Interfaces:**
- Consumes: everything from tasks 1–5.
- Produces: `python3 -m boxradar_site [--host H] [--port P] [--config PATH] [--ttl S]`, and a systemd service named `boxradar-site`.

- [ ] **Step 1: Write the entry point**

Create `tools/boxradar-site/boxradar_site/__main__.py`:

```python
"""Run the site application.

    python3 -m boxradar_site --port 8081

Wiring only: argument parsing and construction. Everything testable lives in
the modules this imports.
"""

import argparse
import sys

from . import VERSION
from .cache import DEFAULT_ERROR_BACKOFF_S, DEFAULT_TTL_S, MetarCache
from .config import DEFAULT_PATH, load
from .server import make_server
from .upstream import fetch

DEFAULT_PORT = 8081


def main(argv=None):
    p = argparse.ArgumentParser(prog="boxradar-site")
    p.add_argument("--host", default="0.0.0.0",
                   help="bind address (default: all interfaces, LAN only)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--config", default=DEFAULT_PATH)
    p.add_argument("--ttl", type=int, default=DEFAULT_TTL_S,
                   help="seconds before a cached observation is refetched")
    p.add_argument("--backoff", type=int, default=DEFAULT_ERROR_BACKOFF_S,
                   help="seconds to wait after an upstream failure")
    p.add_argument("--version", action="version", version=VERSION)
    args = p.parse_args(argv)

    cfg = load(args.config)
    cache = MetarCache(fetch, ttl_s=args.ttl, error_backoff_s=args.backoff)
    httpd = make_server((args.host, args.port), cache, cfg)
    stations = ", ".join(sorted(cfg.runways)) or "none"
    print(f"boxradar-site {VERSION} on {args.host}:{args.port} "
          f"(ttl {args.ttl}s, runway tables: {stations})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it starts and answers, locally**

```bash
cd tools/boxradar-site
python3 -m boxradar_site --port 8099 --config /nonexistent.json &
sleep 1
curl -s http://127.0.0.1:8099/healthz; echo
curl -s http://127.0.0.1:8099/metar/EGSS; echo
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8099/metar/NOPE
kill %1
cd ../..
```

Expected: `{"ok":true,"version":"1.0.0"}`; then a real envelope for EGSS with `"rwy":""` (no config file, so no runway table); then `400`.

This is the first time the real `upstream.fetch` runs. If it fails, check outbound HTTPS before suspecting the code.

- [ ] **Step 3: Write the systemd unit**

Create `tools/boxradar-site/boxradar-site.service`:

```ini
[Unit]
Description=BOXRADAR site application (METAR proxy)
Documentation=https://aviationweather.gov/data/api/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# A long-running service replaces the oneshot timer this supersedes. It needs
# no write access anywhere — the old script ran as root only to write into
# lighttpd's document root, and there is no file to write any more.
DynamicUser=yes
Environment=PYTHONPATH=/usr/local/lib/boxradar-site
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -m boxradar_site --port 8081
Restart=always
RestartSec=5
Nice=10

# Needs outbound HTTPS, one read-only config file, and a listening socket.
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6
MemoryMax=128M

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Write the installer**

Create `tools/boxradar-site/install.sh`:

```bash
#!/usr/bin/env bash
# Install the BOXRADAR site application on the RECEIVER Pi (the box running
# readsb/tar1090, NOT the display and NOT the home server).
#
#   sudo ./install.sh
#
# Afterwards the display fetches http://<receiver>:8081/metar/<ICAO> instead
# of the static /metar.json the old timer published.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/local/lib/boxradar-site
CONF_DIR=/etc/boxradar-site
UNIT_DIR=/etc/systemd/system
PORT=8081

if [[ $EUID -ne 0 ]]; then
  echo "error: run as root (sudo ./install.sh)" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "error: no systemd on this host" >&2
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)'; then
  echo "error: python3 >= 3.7 required" >&2
  exit 1
fi

# Fail early rather than leaving a unit in a restart loop against whatever
# already owns the port.
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  echo "error: something is already listening on port $PORT:" >&2
  ss -ltnp "sport = :$PORT" >&2
  exit 1
fi

echo "installing package to $LIB_DIR"
install -d -m 0755 "$LIB_DIR"
rm -rf "$LIB_DIR/boxradar_site"
cp -r "$SRC_DIR/boxradar_site" "$LIB_DIR/boxradar_site"
find "$LIB_DIR/boxradar_site" -type f -exec chmod 0644 {} +
find "$LIB_DIR/boxradar_site" -type d -exec chmod 0755 {} +

install -d -m 0755 "$CONF_DIR"
if [[ -f $CONF_DIR/config.json ]]; then
  echo "keeping existing $CONF_DIR/config.json"
else
  echo "writing default $CONF_DIR/config.json"
  # Runway headings are TRUE, not magnetic. Designators are magnetic and
  # rounded to 10 degrees, so 05 is not 050. These are the three fields the
  # superseded metar_feed.py carried.
  cat > "$CONF_DIR/config.json" <<'JSON'
{
  "runways": {
    "EGSS": [["04", 43], ["22", 223]],
    "EGGW": [["07", 74], ["25", 254]],
    "EGMC": [["05", 54], ["23", 234]]
  },
  "calm_kt": 7
}
JSON
  chmod 0644 "$CONF_DIR/config.json"
fi

echo "installing systemd unit"
install -m 0644 "$SRC_DIR/boxradar-site.service" \
                "$UNIT_DIR/boxradar-site.service"
systemctl daemon-reload
systemctl enable --now boxradar-site.service

sleep 2
if ! curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  echo "error: service is not answering on port $PORT" >&2
  echo "check: journalctl -u boxradar-site.service -n 30 --no-pager" >&2
  exit 1
fi

echo
echo "OK. verify from another machine:"
echo "  curl http://\$(hostname -I | awk '{print \$1}'):$PORT/metar/EGSS"
echo
systemctl --no-pager status boxradar-site.service | head -n 12
```

- [ ] **Step 5: Make it executable and write the README**

```bash
chmod +x tools/boxradar-site/install.sh
```

Create `tools/boxradar-site/README.md`:

```markdown
# boxradar-site

The Pi-side application for BOXRADAR. Runs on the **receiver** Pi — the box
running readsb/tar1090 — not on the display and not on a separate server.

Phase 1 is the METAR proxy. Later phases add the geography generator and the
site configuration UI; see
`docs/superpowers/specs/2026-08-08-runtime-site-config-design.md`.

## Why a proxy

Its job is terminating TLS off the device. An ESP32 TLS handshake wants ~40KB
of heap against a board whose floor is ~43KB with the render sprite live, so
`https://aviationweather.gov` is not reachable from the firmware at all.

The proxy replaces a systemd timer that fetched three hardcoded stations
every 5 minutes and wrote `/var/www/html/metar.json`. Any ICAO can now be
asked for, and the station list stops being configuration on both sides.

## Endpoints

| route | returns |
|---|---|
| `GET /metar/EGSS` | one station |
| `GET /metar/EGSS,EGGW` | several, in one upstream call |
| `GET /healthz` | `{"ok":true,"version":"..."}` |

`400` for anything that is not one to eight four-letter ICAO codes. `503`
when there is no observation cached and none available upstream — the
firmware keeps its last good reading on a non-200, whereas an empty
`stations` array would look like a successful publish with no weather in it.

## Caching

The timer this replaces bounded upstream load at one call per 5 minutes no
matter what the board did. The cache reproduces that bound: a 300s TTL per
station, so a board polling every 60s produces 12 upstream calls an hour
rather than 60. A 60s backoff after a failure stops a polling board turning a
broken upstream into a retry storm. Stale observations are served rather than
withheld and are flagged with `"stale":1`; `t` stays the wall-clock time of
the upstream fetch, so it never falsely refreshes.

## Install

```bash
ssh pi@<receiver>
cd /path/to/boxradar/tools/boxradar-site
sudo ./install.sh
```

Runway headings live in `/etc/boxradar-site/config.json` and are **TRUE, not
magnetic** — designators are magnetic and rounded to 10 degrees, so 05 is not
050. A station with no runway table still returns wind, cloud and visibility;
it just gets `"rwy":""` and `"conf":0`.

## Tests

From the repo root:

```bash
python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v
```

stdlib only — no venv, no pip. Debian's Python is externally managed
(PEP 668) and this must stay installable on a receiver box without either.
```

- [ ] **Step 6: Verify the whole suite still passes and nothing was broken**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 64 tests

- [ ] **Step 7: Commit**

```bash
git add tools/boxradar-site/boxradar_site/__main__.py \
        tools/boxradar-site/boxradar-site.service \
        tools/boxradar-site/install.sh \
        tools/boxradar-site/README.md
git commit -m "feat: entry point, systemd unit and installer for boxradar-site

A long-running service replaces the oneshot timer. It needs no write access
anywhere now that there is no metar.json to publish, so it runs under
DynamicUser rather than as root. The installer refuses to proceed if
something already holds port 8081, rather than leaving a unit in a restart
loop."
```

---

### Task 7: Deploy, cut the board over, retire the old feed

Order matters: the display is on a shelf and its weather line is live. The old timer stays running until the new service is verified **on the device**, not merely on the Pi.

**Files:**
- Modify: `include/config.h` (gitignored — the local one)
- Modify: `include/config.example.h:20-22`
- Modify: `README.md` (four places: the METAR section, the Relocating table, the worked example, the Layout block)
- Delete: `tools/metar-feed/`

`SPEC.md` mentions METAR nowhere — `grep -i metar SPEC.md` returns nothing — so
it needs no change. Its "Non-goals" entry for a web config portal is reopened
by the spec, but that belongs to phase 3a, not here.

- [ ] **Step 1: Install on the receiver Pi**

```bash
ssh pi@192.0.2.10 'ls /path/to/boxradar 2>/dev/null || echo "repo not on the Pi"'
```

If the repo is not on the Pi, copy just this directory over:

```bash
rsync -a --delete tools/boxradar-site/ pi@192.0.2.10:/tmp/boxradar-site/
ssh pi@192.0.2.10 'cd /tmp/boxradar-site && sudo ./install.sh'
```

Expected: `OK. verify from another machine:` and a green `active (running)`.

- [ ] **Step 2: Verify the proxy from the home server, and compare against the old feed**

```bash
curl -s http://192.0.2.10:8081/metar/EGSS | python3 -m json.tool
curl -s http://192.0.2.10/metar.json | python3 -m json.tool
```

Expected: the same `id`, `rwy`, `wdir`, `wspd`, `cov`, `ceil` and `vis` values for EGSS in both (allowing for the observation having refreshed between the two calls). The new response additionally carries `"stale":0`.

Confirm the cache is actually bounding upstream calls:

```bash
for i in 1 2 3 4 5; do curl -s -o /dev/null http://192.0.2.10:8081/metar/EGSS; done
ssh pi@192.0.2.10 'journalctl -u boxradar-site -n 20 --no-pager'
```

Expected: five request log lines, and no evidence of five upstream fetches — the startup line plus request lines only.

- [ ] **Step 3: Point the board at the proxy**

Edit `include/config.h`:

```c
#define METAR_URL "http://192.0.2.10:8081/metar/EGSS"
```

Edit `include/config.example.h`, replacing the `METAR_URL` and `METAR_STATION` block at lines 20-22:

```c
// Optional weather, proxied by tools/boxradar-site on the receiver Pi. The
// path names the station, so METAR_STATION must match the last path segment —
// the firmware picks that id out of the "stations" array. Comment out
// METAR_URL to disable; the status line simply omits the weather segments and
// everything else carries on.
#define METAR_URL "http://receiver.lan:8081/metar/EGSS"
#define METAR_STATION "EGSS"
```

- [ ] **Step 4: Confirm the firmware still builds**

Run: `pio run -e usb`
Expected: SUCCESS. No source file changed, so this only proves the config header is well-formed.

- [ ] **Step 5: Flash over OTA and verify on the device**

```bash
pio run -e ota -t upload
```

Run one upload at a time. "Listen Failed" means host port 3232 is still in `TIME_WAIT` — wait 60s and retry once.

Then read the status strip on the shelf: it must still show the active runway, wind, cloud and any restricted visibility. **This is the acceptance test for the whole task** — the proxy is only correct if the panel looks unchanged.

If the weather segments have vanished, the board got a non-200 or a shape it could not parse. Check `journalctl -u boxradar-site -f` on the Pi while the board polls (every 60s per `METAR_POLL_INTERVAL_MS`).

- [ ] **Step 6: Retire the old feed, only now**

```bash
ssh pi@192.0.2.10 'sudo systemctl disable --now metar-feed.timer && \
  sudo systemctl stop metar-feed.service; \
  sudo rm -f /etc/systemd/system/metar-feed.service \
             /etc/systemd/system/metar-feed.timer \
             /usr/local/bin/metar_feed.py \
             /var/www/html/metar.json && \
  sudo systemctl daemon-reload && \
  systemctl list-timers --all --no-pager | grep -c metar-feed || true'
```

Expected: `0` matching timers.

```bash
git rm -r tools/metar-feed
```

- [ ] **Step 7: Update the README — the METAR section**

Replace the whole `### METAR feed (optional, receiver-side)` section
(`README.md:245` through the paragraph ending "the status strip simply omits
the weather segments") with:

```markdown
### METAR proxy (optional, receiver-side)

`tools/boxradar-site/` installs on the **receiver Pi**, not the display and
not a separate server. It answers `GET /metar/<ICAO>` on port 8081, fetching
from aviationweather.gov on demand and caching each station for 5 minutes,
so the display polls `http://<receiver>:8081/metar/EGSS` over plain HTTP
alongside the `aircraft.json` it already gets from the same box.

```bash
# on the receiver Pi
sudo ./install.sh
```

Any ICAO can be asked for — there is no station list to configure. The one
thing the Pi still needs per airfield is runway **true** headings, in
`/etc/boxradar-site/config.json`, because that is published data the request
cannot carry. A station with no entry there still returns wind, cloud and
visibility; it just reports no active runway.

Keeping it on the receiver means the whole system stays two devices —
receiver for data, ESP32 for display — which is what makes it portable to
another location. It also avoids TLS on the ESP32: a handshake wants
~40KB of heap against a board whose floor is ~46KB with the render sprite
live.

The Pi normalises the upstream API's loose types (`visib` can be the
string `"6+"`, `wdir` can be `"VRB"`, `wgst` can be null) into fixed
always-present integers, and derives the likely active runway from the
wind. `conf` is 0 below `calm_kt` (7) — at that point wind isn't choosing
the runway and the value is a guess, which the display marks with a `?`.

Cloud shows as `CLEAR` when no layers are reported: upstream reports NCD,
NSC, SKC and CAVOK identically, so the broader word is the honest one.

The cache is what makes an on-demand endpoint safe. The timer this replaced
guaranteed at most one upstream call every 5 minutes; a 300s per-station TTL
reproduces that bound, so a board polling every 60s produces 12 upstream
calls an hour rather than 60. After an upstream failure the proxy backs off
for 60s and serves the last good observation flagged `"stale":1`, because a
stale METAR is far better than none.

Set `METAR_URL` and `METAR_STATION` in `config.h` to consume it. They must
agree — the URL's last path segment names the station the firmware then picks
out of the response. Both are optional: comment out `METAR_URL` and the whole
feature compiles out, and the status strip simply omits the weather segments.
```

- [ ] **Step 8: Update the README — Relocating table, worked example, Layout**

In the Relocating table, replace the `tools/metar-feed/metar_feed.py` row:

```markdown
| `/etc/boxradar-site/config.json` (on the Pi) | `runways` — stations and runway **true** headings | no — lives on the receiver |
```

In the "Worked example: Southend-on-Sea" block, replace the trailing Python
snippet:

````markdown
```json
// /etc/boxradar-site/config.json on the receiver Pi (headings are TRUE)
{"runways": {"EGMC": [["05", 54], ["23", 234]]}}
```
````

In the Layout block, replace the `tools/` line:

```
tools/          airspace and coastline codegen, boxradar-site (receiver-side
                METAR proxy; grows into the site config app)
```

- [ ] **Step 9: Verify the suite and the build one more time, then commit**

```bash
python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v
pio run -e usb
git add -A
git commit -m "feat: serve METAR from a proxy instead of a published file

The board now fetches http://<receiver>:8081/metar/EGSS. The response
envelope is unchanged, so lib/radarcore/metar.cpp and struct Metar are
untouched and the only firmware change is METAR_URL.

Retires tools/metar-feed: the station list stops being configuration on
either side, and a proxy can answer for any ICAO instead of the three that
were compiled into a dict."
```

---

## Notes for whoever executes this

**The acceptance test is the panel, not the test suite.** 66 unit tests prove
the normalisation and caching behave; only the shelf proves the board still
renders wind, runway and cloud. Task 7 step 5 is the gate.

**Serial is usually unavailable on this unit.** It runs off USB power on a
shelf, not plugged into a host — check `/dev/ttyUSB*` exists before planning
around it. OTA is the flash path. `ping 192.0.2.20` in a short loop
confirms a reboot completed.

**Do not add a dependency.** The stdlib-only constraint is load-bearing for
phase 1 and the reason is recorded at the top of the plan. If something feels
like it wants Flask, it wants a different design.

**The runway table is a known loose end, deliberately left.** The spec says
"the station list stops being config on either side", and it does — but runway
*headings* are still per-station config, now in
`/etc/boxradar-site/config.json` instead of a Python dict. They have to be:
the proxy serves any ICAO and headings are published data the request cannot
carry.

There is a better answer available in phase 3b, and it is worth not
foreclosing. Once the board loads its geography blob it already holds
`RunwayAxis` entries — both threshold coordinates per runway, for the extended
centrelines. `pick_runway()` is pure trigonometry over exactly that data, so it
could move into `lib/radarcore`, become natively unit-tested alongside the rest
of the domain logic, and delete the Pi-side runway table entirely. The proxy
would then serve raw normalised weather and nothing else, which is a cleaner
boundary than the one this plan ships.

Not done here because it is a firmware change, and phase 1's entire safety
argument is that the only board change is a URL. Keep `pick_runway()` pure and
free of Pi-only assumptions so that move stays cheap.

**One pre-existing flaw is deliberately not fixed here.** `status_bar.cpp`
ages the METAR from `metar.lastFetchMs`, which is when the *board* fetched,
not when the observation was made. So a proxy serving a three-hour-old
observation still looks current on the panel. The envelope now carries
`stale` and `obs` so a later phase can use them, but changing the firmware's
staleness logic is out of scope for a task whose whole safety argument is
"the only board change is a URL".
