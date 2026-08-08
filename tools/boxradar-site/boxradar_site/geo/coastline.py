"""Coastline selection: fetch from Overpass, filter, clip, simplify.

Moved from tools/build_coastline.py. There was no curation to remove — this
already selected purely by bounding box — so the changes are structural:
fetch() takes an explicit cache directory so tests never touch the real cache,
and home comes from arguments rather than being read out of config.h, which is
what lets the Pi generate for any site.

Why filtering matters more than simplification here: the raw data for the
Essex coast is ~360k nodes, and simplifying alone barely helps because the
estuaries are full of tiny saltmarsh islets and creek rings — each a separate
closed way that a two-point simplify cannot reduce. Dropping features below
MIN_FEATURE_KM is what takes 143KB down to ~20KB, and it drops exactly the
detail that is sub-pixel at every range the scope offers.

Absolute lat/lon, NOT home-relative offsets. Storing NM offsets would remove
~2600 projections per frame, but it would bake the scope's centre into a
committed file — and HOME_LAT/HOME_LON live in the gitignored config.h
precisely so they are never published. Runtime projection is four float
operations per point; the real per-frame cost is drawLine, which scope.cpp
trivially rejects off-screen instead.
"""

import json
import math
import sys
import urllib.error
import urllib.request

from shapely.affinity import scale
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, unary_union

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Must cover the largest entry in RANGES_NM, plus slack for traffic drawn in
# the wide left/right margins beyond the outer ring.
MAX_RANGE_NM = 50
MARGIN_NM = 15

# Coastline features shorter than this are dropped. 2km keeps the mainland,
# the major estuaries and the substantial islands (Mersea, Foulness, Canvey)
# while discarding creek-level detail.
#
# This is the knob that actually controls size. Simplification cannot reduce
# a two-point line, so tightening SIMPLIFY_M alone barely helps against
# thousands of tiny saltmarsh rings — see the module docstring.
MIN_FEATURE_KM = 2.0

# Simplification tolerance. 500m is ~5.9px at the closest 5nm range and well
# under a pixel at 50nm. Judged on hardware: the coast reads fine coarse, and
# every metre of tolerance buys back flash.
SIMPLIFY_M = 500.0

# The query box is rounded outward to this many degrees. Clipping tightly
# around home would let the emitted extent give the scope centre away; a
# coarse box leaks no more than the airspace data already does.
BOX_ROUND_DEG = 0.5

M_PER_DEG = 111320.0


def query_box(lat, lon):
    """(south, west, north, east) — Overpass order, rounded outward."""
    reach = MAX_RANGE_NM + MARGIN_NM
    dlat = reach / 60.0
    dlon = reach / (60.0 * math.cos(math.radians(lat)))
    r = BOX_ROUND_DEG

    def down(v):
        return math.floor(v / r) * r

    def up(v):
        return math.ceil(v / r) * r

    return down(lat - dlat), down(lon - dlon), up(lat + dlat), up(lon + dlon)


def cache_path(bbox, cache_dir):
    """Cache file named for the query box.

    Keying on the bbox matters: a single fixed filename would happily serve
    the previous location's coastline after a move, and the failure is silent
    — you get a plausible coast that is simply somewhere else.
    """
    s, w, n, e = bbox
    return cache_dir / f"coastline_{s:g}_{w:g}_{n:g}_{e:g}.json"


def fetch(bbox, cache_dir):
    cache = cache_path(bbox, cache_dir)
    if cache.exists():
        print(f"using cached {cache}", file=sys.stderr)
        return json.loads(cache.read_text())
    s, w, n, e = bbox
    q = (
        "[out:json][timeout:180];"
        f'way["natural"="coastline"]({s},{w},{n},{e});'
        "(._;>;);out;"
    )
    print(f"querying overpass for {bbox} (cached afterwards)", file=sys.stderr)
    req = urllib.request.Request(
        OVERPASS_URL,
        data=q.encode(),
        headers={"User-Agent": "boxradar-coastline/1 (+local desk toy)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SystemExit(f"overpass fetch failed: {exc}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    print(f"cached {len(raw)} bytes -> {cache}", file=sys.stderr)
    return json.loads(raw)


def segments(data, home_lat, home_lon):
    """Filtered, clipped, simplified coastline as [(lat, lon), ...] lists."""
    nodes = {e["id"]: (e["lon"], e["lat"])
             for e in data["elements"] if e["type"] == "node"}
    lines = [
        LineString([nodes[n] for n in w["nodes"]])
        for w in data["elements"]
        if w["type"] == "way" and len(w.get("nodes", [])) > 1
    ]
    if not lines:
        raise SystemExit("no coastline ways in response")
    merged = linemerge(unary_union(lines))
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" \
        else [merged]
    print(f"{len(lines)} ways -> {len(parts)} continuous features",
          file=sys.stderr)

    min_deg = MIN_FEATURE_KM * 1000.0 / M_PER_DEG
    parts = [p for p in parts if p.length >= min_deg]
    print(f"{len(parts)} features >= {MIN_FEATURE_KM}km", file=sys.stderr)

    # Clip to a circle at the scope's actual reach: the query box is square
    # and deliberately coarse, but there is no point emitting corners the
    # scope can never show.
    reach = MAX_RANGE_NM + MARGIN_NM
    circle = scale(
        Point(home_lon, home_lat).buffer(1.0),
        xfact=reach / (60.0 * math.cos(math.radians(home_lat))),
        yfact=reach / 60.0,
        origin=Point(home_lon, home_lat),
    )
    tol = SIMPLIFY_M / M_PER_DEG
    out = []
    for p in parts:
        clipped = p.intersection(circle)
        if clipped.is_empty:
            continue
        geoms = list(clipped.geoms) \
            if clipped.geom_type == "MultiLineString" else [clipped]
        for g in geoms:
            if g.geom_type != "LineString" or len(g.coords) < 2:
                continue
            s = g.simplify(tol)
            if len(s.coords) < 2:
                continue
            out.append([(round(la, 5), round(lo, 5)) for lo, la in s.coords])
    return out


def bbox_of(segment):
    """(minLat, maxLat, minLon, maxLon) for one segment.

    Computed rather than stored in the blob: a bbox that disagreed with its own
    points would make the renderer reject segments and the coast would silently
    vanish. The C header carries them only because the current firmware expects
    them there.
    """
    lats = [p[0] for p in segment]
    lons = [p[1] for p in segment]
    return min(lats), max(lats), min(lons), max(lons)


def render_header(segs):
    total = sum(len(s) for s in segs)
    lines = [
        "// GENERATED by boxradar_site.geo — do not edit by hand.",
        "// Source: OpenStreetMap via Overpass (natural=coastline), ODbL.",
        f"// {len(segs)} segments, {total} points, "
        f"features >= {MIN_FEATURE_KM}km, simplified to {SIMPLIFY_M:.0f}m.",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "namespace coastline {",
        "",
        "struct Vertex { float lat, lon; };",
        "",
        "// The bounding box lets the renderer reject an entire segment with",
        "// four comparisons instead of projecting every one of its points",
        "// and discarding them individually. At close ranges nearly all of",
        "// the coast is off-panel, so this is most of the cost.",
        "struct Outline {",
        "  const Vertex *pts;",
        "  uint16_t count;",
        "  float minLat, maxLat, minLon, maxLon;",
        "};",
        "",
    ]
    for i, seg in enumerate(segs):
        lines.append(f"static const Vertex SEG_{i}_PTS[] = {{")
        row = "    "
        for la, lo in seg:
            token = f"{{{la}f, {lo}f}}, "
            if len(row) + len(token) > 78:
                lines.append(row.rstrip())
                row = "    "
            row += token
        lines.append(row.rstrip().rstrip(","))
        lines.append("};")
    lines.append("")
    lines.append("static const Outline SEGMENTS[] = {")
    for i, seg in enumerate(segs):
        min_lat, max_lat, min_lon, max_lon = bbox_of(seg)
        lines.append(
            f"    {{SEG_{i}_PTS, {len(seg)}, "
            f"{min_lat}f, {max_lat}f, {min_lon}f, {max_lon}f}},"
        )
    lines.append("};")
    lines.append("")
    lines.append("} // namespace coastline")
    lines.append("")
    return "\n".join(lines)
