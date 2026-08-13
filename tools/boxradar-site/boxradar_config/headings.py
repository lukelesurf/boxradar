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

import math

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
