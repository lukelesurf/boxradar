#!/usr/bin/env python3
"""Fetch METAR for the local airfields and publish a small JSON file.

Runs on the RECEIVER Pi, not on the display and not on a separate server.
Three reasons: the Pi already has outbound internet (it feeds ADSBExchange
and FR24), it already runs lighttpd serving aircraft.json over plain HTTP,
and TLS is free here — an ESP32 TLS handshake wants ~40KB of heap against a
board whose floor is ~43KB with the render sprite live.

The upstream API is loose in ways that would silently corrupt an embedded
parse: `visib` may be the string "6+", `wdir` may be "VRB", `wgst` may be
null, `clouds` may be []. Everything below normalises to fixed-type,
always-present fields so the firmware can never coerce a surprise into a
plausible-looking zero.

stdlib only — Debian's Python is externally managed (PEP 668) and this
should not need a venv or pip on a receiver box.
"""

import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------- config
# Edit for your location, then re-run install.sh. Runway headings are TRUE,
# not magnetic — take them from the AIP or derive from threshold coords.
STATIONS = {
    "EGSS": [("04", 43), ("22", 223)],
    "EGGW": [("07", 74), ("25", 254)],
}

# Overridable so the script can be exercised anywhere without a web root.
OUT_PATH = os.environ.get("METAR_OUT", "/var/www/html/metar.json")
API = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json"
TIMEOUT_S = 20
# Below this the wind is not choosing the runway; the airfield will be using
# its noise-preferential or default direction instead. Set at 7 rather than 5
# because observations here routinely sit at 4-5kt with 60-80 degrees of
# variability (e.g. "14005KT 120V180"), and calling that confident overstates
# what is known. The API does not expose the variable range as a field, so
# speed is the only proxy available without parsing rawOb.
CALM_KT = 7


def fetch(ids):
    req = urllib.request.Request(
        API.format(ids=",".join(ids)),
        headers={"User-Agent": "boxradar-metar-feed/1 (+local desk toy)"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.load(r)


def as_int(v, default=0):
    """Coerce the API's mixed types to an int, without inventing data."""
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    return default


def visibility_m(v):
    """API reports statute miles, sometimes as the string '6+'.

    9999 is the METAR convention for '10km or more' and is what the raw
    observation carries, so unlimited maps back to that rather than to a
    made-up large number.
    """
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("+"):
            return 9999
        try:
            v = float(s)
        except ValueError:
            return 9999
    if isinstance(v, (int, float)):
        return min(9999, int(v * 1609))
    return 9999


def ceiling(clouds):
    """Lowest broken/overcast layer in feet, plus the cover of the lowest
    layer of any kind. 0 feet means no ceiling, which is not the same as
    no cloud — hence returning the cover string separately."""
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


def pick_runway(wdir, wspd, runways):
    """Runway whose heading gives the greatest headwind component.

    Returns (name, confident). Confidence is NOT about the arithmetic — it
    is about whether wind is the deciding factor at all. In light or
    variable conditions the answer is a guess, and the display should say
    so rather than assert a runway the airfield isn't using.
    """
    if not isinstance(wdir, (int, float)) or isinstance(wdir, bool):
        return "", False  # "VRB" or missing
    best = max(runways, key=lambda r: math.cos(math.radians(wdir - r[1])))
    return best[0], wspd >= CALM_KT


def build(raw):
    out = []
    for obs in raw:
        icao = str(obs.get("icaoId") or "")
        runways = STATIONS.get(icao)
        if runways is None:
            continue
        wdir_raw = obs.get("wdir")
        wspd = as_int(obs.get("wspd"))
        rwy, confident = pick_runway(wdir_raw, wspd, runways)
        ceil_ft, cover = ceiling(obs.get("clouds"))
        out.append(
            {
                "id": icao,
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
        )
    return {"t": int(time.time()), "stations": out}


def write_atomic(path, payload):
    """Temp file plus rename, so lighttpd can never serve a half-written
    document to a board polling every few seconds."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".metar-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, separators=(",", ":"))
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    try:
        raw = fetch(list(STATIONS))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # Leave the previous file in place. A stale METAR is far better than
        # none, and the firmware ages it via the "t" field anyway.
        print(f"metar-feed: fetch failed: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"metar-feed: bad JSON upstream: {e}", file=sys.stderr)
        return 1

    payload = build(raw)
    if not payload["stations"]:
        print("metar-feed: no configured stations in response", file=sys.stderr)
        return 1
    write_atomic(OUT_PATH, payload)
    ids = " ".join(f"{s['id']}={s['rwy'] or '??'}" for s in payload["stations"])
    print(f"metar-feed: wrote {OUT_PATH} ({ids})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
