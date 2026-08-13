"""METAR runway headings, derived from runway thresholds.

/etc/boxradar-site/config.json used to be written by hand: a designator and a
TRUE heading per runway end, read by metar.pick_runway() to choose the active
runway from the wind. Sourcing those for an unfamiliar airport means reading
the AIP, and mistaking magnetic for true gives a wrong answer with no visible
error — not a reasonable thing to ask of someone setting up a second unit.

The axis is the one datasets.runways() already returns for drawing
centrelines, under the rule its docstring states: published headings sometimes
disagree with their own threshold coordinates by more than a degree, so the
coordinates win. Checked against the table curated by hand for EGSS, EGGW and
EGMC — all three agree, including EGSS 04, where the dataset publishes 44 and
the thresholds give 43.
"""

import json
import math
import pathlib

from boxradar_site.metar import DEFAULT_CALM_KT

from . import datasets


def bearing(lat0, lon0, lat1, lon1):
    """Initial true bearing from the first point to the second, 0-360."""
    phi0, phi1 = math.radians(lat0), math.radians(lat1)
    dlon = math.radians(lon1 - lon0)
    y = math.sin(dlon) * math.cos(phi1)
    x = (math.cos(phi0) * math.sin(phi1)
         - math.sin(phi0) * math.cos(phi1) * math.cos(dlon))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def metar_runways(cache_dir, icao):
    """[(designator, true heading), ...] for one station, both ends of each.

    Ordered as the dataset gives them — longest runway first, since
    datasets.runways() sorts that way and the longest is the one most likely
    to be in use.
    """
    out = []
    for runway in datasets.runways(cache_dir, [icao]):
        low, _, high = runway.ident.partition("/")
        heading = bearing(runway.lat0, runway.lon0, runway.lat1, runway.lon1)
        if low and low != "?":
            out.append((low, int(round(heading)) % 360))
        if high and high != "?":
            out.append((high, int(round(heading + 180.0)) % 360))
    return out


def site_config(cache_dir, icao, calm_kt=None):
    """The /etc/boxradar-site/config.json document for one station.

    A station with no runways in the dataset still yields a valid document.
    pick_runway() degrades to no-runway on an empty table, and wind, cloud and
    visibility do not depend on it.
    """
    calm = DEFAULT_CALM_KT if calm_kt is None else int(calm_kt)
    pairs = metar_runways(cache_dir, icao)
    table = {icao.upper(): [[d, h] for d, h in pairs]} if pairs else {}
    return {"runways": table, "calm_kt": calm}


def write_site_config(path, cache_dir, icao, calm_kt=None):
    """Write the document, atomically. Returns what was written."""
    doc = site_config(cache_dir, icao, calm_kt)
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same directory so the rename is atomic: boxradar-site reads this file at
    # startup, and a half-written one would be ignored as unparseable.
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(path)
    return doc
