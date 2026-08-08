#!/usr/bin/env python3
"""Generate src/ui/coastline_data.h from OpenStreetMap coastline data.

Offline codegen, same shape as boxradar_site.geo: fetch once, cache, emit a
committed header. Run it when relocating; never at build time.

Why filtering matters more than simplification here: the raw data for the
Essex coast is ~360k nodes, and simplifying alone barely helps because the
estuaries are full of tiny saltmarsh islets and creek rings — each a separate
closed way that a two-point simplify cannot reduce. Dropping features below
MIN_FEATURE_KM is what takes 143KB down to ~20KB, and it drops exactly the
detail that is sub-pixel at every range the scope offers.

The emitted header holds absolute lat/lon, NOT home-relative offsets. Storing
NM offsets would remove ~2600 projections per frame, but it would bake the
scope's centre into a committed file — and HOME_LAT/HOME_LON live in the
gitignored config.h precisely so they are never published. Runtime projection
is four float operations per point; the real per-frame cost is drawLine, which
scope.cpp trivially rejects off-screen instead.
"""

import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from shapely.affinity import scale
from shapely.geometry import LineString, Point, box
from shapely.ops import linemerge, unary_union

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = REPO_ROOT / "include" / "config.h"
OUTPUT_PATH = REPO_ROOT / "src" / "ui" / "coastline_data.h"

CACHE_DIR = Path(os.path.expanduser("~/.cache/boxradar-coastline"))
OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def cache_path(bbox) -> Path:
    """Cache file named for the query box.

    Keying on the bbox matters: a single fixed filename would happily serve
    the previous location's coastline after a move, and the failure is silent
    — you get a plausible coast that is simply somewhere else.
    """
    s, w, n, e = bbox
    return CACHE_DIR / f"coastline_{s:g}_{w:g}_{n:g}_{e:g}.json"

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
# every metre of tolerance buys back flash on a board at ~83% capacity.
SIMPLIFY_M = 500.0

# The query box is rounded outward to this many degrees. Clipping tightly
# around home would let the emitted extent give the scope centre away; a
# coarse box leaks no more than the airspace data already does.
BOX_ROUND_DEG = 0.5

M_PER_DEG = 111320.0


def read_home() -> tuple[float, float]:
    """HOME_LAT/HOME_LON out of the gitignored config.h."""
    if not CONFIG_PATH.exists():
        raise SystemExit(f"{CONFIG_PATH} not found — copy config.example.h first")
    text = CONFIG_PATH.read_text()
    out = {}
    for key in ("HOME_LAT", "HOME_LON"):
        m = re.search(rf"^#define\s+{key}\s+(-?[0-9.]+)", text, re.M)
        if not m:
            raise SystemExit(f"{key} not found in {CONFIG_PATH}")
        out[key] = float(m.group(1))
    return out["HOME_LAT"], out["HOME_LON"]


def query_box(lat: float, lon: float) -> tuple[float, float, float, float]:
    reach = MAX_RANGE_NM + MARGIN_NM
    dlat = reach / 60.0
    dlon = reach / (60.0 * math.cos(math.radians(lat)))
    r = BOX_ROUND_DEG

    def down(v):
        return math.floor(v / r) * r

    def up(v):
        return math.ceil(v / r) * r

    return down(lat - dlat), down(lon - dlon), up(lat + dlat), up(lon + dlon)


def fetch(bbox) -> dict:
    cache = cache_path(bbox)
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
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    print(f"cached {len(raw)} bytes -> {cache}", file=sys.stderr)
    return json.loads(raw)


def build_segments(data: dict, lat: float, lon: float):
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in data["elements"] if e["type"] == "node"}
    lines = [
        LineString([nodes[n] for n in w["nodes"]])
        for w in data["elements"]
        if w["type"] == "way" and len(w.get("nodes", [])) > 1
    ]
    if not lines:
        raise SystemExit("no coastline ways in response")
    merged = linemerge(unary_union(lines))
    parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    print(f"{len(lines)} ways -> {len(parts)} continuous features", file=sys.stderr)

    min_deg = MIN_FEATURE_KM * 1000.0 / M_PER_DEG
    parts = [p for p in parts if p.length >= min_deg]
    print(f"{len(parts)} features >= {MIN_FEATURE_KM}km", file=sys.stderr)

    # Clip to a circle at the scope's actual reach: the query box is square
    # and deliberately coarse, but there is no point emitting corners the
    # scope can never show.
    reach = MAX_RANGE_NM + MARGIN_NM
    circle = scale(
        Point(lon, lat).buffer(1.0),
        xfact=reach / (60.0 * math.cos(math.radians(lat))),
        yfact=reach / 60.0,
        origin=Point(lon, lat),
    )
    tol = SIMPLIFY_M / M_PER_DEG
    out = []
    for p in parts:
        clipped = p.intersection(circle)
        if clipped.is_empty:
            continue
        geoms = list(clipped.geoms) if clipped.geom_type == "MultiLineString" else [clipped]
        for g in geoms:
            if g.geom_type != "LineString" or len(g.coords) < 2:
                continue
            s = g.simplify(tol)
            if len(s.coords) < 2:
                continue
            out.append([(round(la, 5), round(lo, 5)) for lo, la in s.coords])
    return out


def emit(segments, path: Path) -> None:
    total = sum(len(s) for s in segments)
    lines = [
        "// GENERATED by tools/build_coastline.py — do not edit by hand.",
        "// Source: OpenStreetMap via Overpass (natural=coastline), ODbL.",
        f"// {len(segments)} segments, {total} points, "
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
    for i, seg in enumerate(segments):
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
    for i, seg in enumerate(segments):
        lats = [p[0] for p in seg]
        lons = [p[1] for p in seg]
        lines.append(
            f"    {{SEG_{i}_PTS, {len(seg)}, "
            f"{min(lats)}f, {max(lats)}f, {min(lons)}f, {max(lons)}f}},"
        )
    lines.append("};")
    lines.append("")
    lines.append("} // namespace coastline")
    lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    lat, lon = read_home()
    bbox = query_box(lat, lon)
    data = fetch(bbox)
    segments = build_segments(data, lat, lon)
    if not segments:
        raise SystemExit("nothing survived filtering — is the area landlocked?")
    total = sum(len(s) for s in segments)
    print(
        f"emitting {len(segments)} segments, {total} points "
        f"(~{total * 8 / 1024:.1f}KB of flash)",
        file=sys.stderr,
    )
    emit(segments, OUTPUT_PATH)
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
