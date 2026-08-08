"""The candidate list: what airspace is near me, and how would it look?

This is the module that replaces CURATED_AIRPORTS. That list was hard to
maintain not because choosing is hard but because *discovery* was: you had to
know which controlled airspace mattered near you and how the YAIXM source
spelled it. Listing every feature in the box, with the numbers a human decides
on, removes that entirely.

The columns are chosen from what the decision actually turns on:

  kind         (type, localtype, rules) collapsed — OTHER/TMZ is drawn,
               OTHER/MATZ is not, and `type` alone cannot tell them apart
  diag_px      on-screen extent at the overview scale. An outline larger than
               the panel cannot read as an enclosure, which is the recorded
               reason the London TMA was excluded by hand
  distance_nm  catches far-but-small: BOURNEMOUTH CTR is 43px and ~110nm away
  vertices     the only column with a device cost
"""

import math

from .yaixm import feature_kind, feature_rings

NM_PER_DEG_LAT = 60.0


class Candidate:
    def __init__(self, name, kind, rings, home_lat, home_lon):
        self.name = name
        self.kind = kind
        self.volumes = len(rings)
        self.vertices = sum(len(r) for r in rings)
        lats = [lat for r in rings for _, lat in r]
        lons = [lon for r in rings for lon, _ in r]
        self.min_lat, self.max_lat = min(lats), max(lats)
        self.min_lon, self.max_lon = min(lons), max(lons)
        mid_lat = (self.min_lat + self.max_lat) / 2.0
        mid_lon = (self.min_lon + self.max_lon) / 2.0
        scale = math.cos(math.radians(mid_lat))
        h_nm = (self.max_lat - self.min_lat) * NM_PER_DEG_LAT
        w_nm = (self.max_lon - self.min_lon) * NM_PER_DEG_LAT * scale
        self.diag_nm = math.hypot(h_nm, w_nm)
        d_lat = (mid_lat - home_lat) * NM_PER_DEG_LAT
        d_lon = (mid_lon - home_lon) * NM_PER_DEG_LAT \
            * math.cos(math.radians(home_lat))
        self.distance_nm = math.hypot(d_lat, d_lon)

    def diag_px(self, px_per_nm):
        return self.diag_nm * px_per_nm

    def intersects(self, south, north, west, east):
        return not (self.max_lat < south or self.min_lat > north
                    or self.max_lon < west or self.min_lon > east)

    def __repr__(self):
        return (f"<Candidate {self.name!r} {self.kind} "
                f"{self.diag_nm:.0f}nm @{self.distance_nm:.0f}nm "
                f"{self.vertices}v>")


def bbox_for(home_lat, home_lon, reach_nm):
    """(south, north, west, east) for a reach in nautical miles.

    Longitude is scaled by cos(latitude): a degree of longitude at 51.9N is
    only about 37nm, so reaching the same distance east needs more degrees
    than reaching the same distance north.
    """
    d_lat = reach_nm / NM_PER_DEG_LAT
    d_lon = d_lat / math.cos(math.radians(home_lat))
    return (home_lat - d_lat, home_lat + d_lat,
            home_lon - d_lon, home_lon + d_lon)


def catalog(features, home_lat, home_lon, reach_nm):
    """Every feature whose geometry intersects the box, nearest first."""
    south, north, west, east = bbox_for(home_lat, home_lon, reach_nm)
    out = []
    for feature in features:
        rings = feature_rings(feature)
        if not rings:
            continue  # unparseable or geometry-less; not our problem here
        cand = Candidate(str(feature.get("name") or "?"),
                         feature_kind(feature), rings, home_lat, home_lon)
        if cand.intersects(south, north, west, east):
            out.append(cand)
    out.sort(key=lambda c: c.distance_nm)
    return out
