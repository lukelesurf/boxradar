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
