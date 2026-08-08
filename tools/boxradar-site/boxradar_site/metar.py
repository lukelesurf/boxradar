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

    Kept pure and free of Pi-only assumptions on purpose: this is a candidate
    to move into lib/radarcore once the board loads runway axes from its
    geography blob, which would retire the Pi-side runway table entirely.
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
