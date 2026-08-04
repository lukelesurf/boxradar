#!/usr/bin/env python3
"""
Generate src/ui/airspace_data.h from the ahsparrow/airspace YAIXM source,
for the BOXRADAR firmware.

Curated to a fixed set of airports (see CURATED_AIRPORTS): for each, emits
the CTR boundary plus an envelope (union of CTR + CTA volumes) outline.

NOTE: The `yaixm` PyPI package does not exist. This script implements the
YAIXM parsing directly using only PyYAML + shapely + stdlib.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml
from shapely.geometry import Polygon
from shapely.ops import unary_union

REPO_URL = "https://github.com/ahsparrow/airspace"
CACHE_DIR = Path(os.path.expanduser("~/.cache/boxradar-airspace"))
REPO_DIR = CACHE_DIR / "airspace"
YAML_PATH = REPO_DIR / "airspace.yaml"

# Output path is resolved relative to the repo root, which we assume is the
# parent of this script's directory.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
OUTPUT_PATH = REPO_ROOT / "src" / "ui" / "airspace_data.h"

# (output name prefix, CTR feature name, CTA feature name)
CURATED_AIRPORTS = [
    ("STANSTED", "LONDON STANSTED CTR", "LONDON STANSTED CTA"),
    ("LUTON", "LONDON LUTON CTR", "LONDON LUTON CTA"),
]

BUFFER_DEG = 0.001     # ~60m: merges near-coincident arc discretisations
SIMPLIFY_DEG = 0.0005  # ~35m: invisible at scope scale, trims point count

# Arc interpolation resolution: points per full circle (36 = 10° steps).
ARC_RESOLUTION = 36

# Lat/lon DMS pattern: [D]DDMMSS[.sss]H
_DMS_RE = re.compile(
    r"(?P<d>[0-9]{2}|[01][0-9]{2})(?P<m>[0-5][0-9])"
    r"(?P<s>[0-5][0-9](?:\.[0-9]{1,3})?)(?P<h>[NESW])"
)


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def parse_latlon(s: str) -> tuple[float, float]:
    """Parse a YAIXM coordinate string (e.g. '512345N 0001234W') to (lat, lon)."""
    parts = s.split()
    if len(parts) != 2:
        raise ValueError(f"bad latlon: {s!r}")
    lat = _parse_deg(parts[0])
    lon = _parse_deg(parts[1])
    return lat, lon


def _parse_deg(s: str) -> float:
    m = _DMS_RE.match(s)
    if m is None:
        raise ValueError(f"bad DMS: {s!r}")
    deg = int(m.group("d")) + int(m.group("m")) / 60 + float(m.group("s")) / 3600
    if m.group("h") in "SW":
        deg = -deg
    return deg


def _nm_to_deg(nm: float) -> float:
    """Convert nautical miles to degrees of latitude (approximate)."""
    return nm / 60.0


def _deg_to_rad(d: float) -> float:
    return d * math.pi / 180.0


def _rad_to_deg(r: float) -> float:
    return r * 180.0 / math.pi


# ---------------------------------------------------------------------------
# GeoJSON coordinate list helpers
# ---------------------------------------------------------------------------

def _geojson_coord(lat: float, lon: float) -> list[float]:
    """GeoJSON is [lon, lat]."""
    return [round(lon, 6), round(lat, 6)]


def _interpolate_arc(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
    centre_lat: float,
    centre_lon: float,
    radius_nm: float,
    clockwise: bool,
) -> list[list[float]]:
    """
    Return a list of GeoJSON coords interpolating the arc from (from_lat,from_lon)
    to (to_lat,to_lon) around centre, in the given direction.

    Uses a simple equirectangular approximation — sufficient for small areas
    at UK latitudes. Points are appended at ARC_RESOLUTION steps per full circle.
    """
    # Work in "flat" coordinates scaled so that degrees-lat ≈ degrees-lon.
    # Scale lon by cos(centre_lat) so that equal angular steps produce
    # roughly equal arc lengths on the ground.
    cos_lat = math.cos(_deg_to_rad(centre_lat))

    def to_xy(lat: float, lon: float) -> tuple[float, float]:
        return (lat - centre_lat, (lon - centre_lon) * cos_lat)

    def angle_of(lat: float, lon: float) -> float:
        x, y = to_xy(lat, lon)
        return math.atan2(y, x)

    # YAIXM "radius" field is informational; actual from-point distance is the truth.
    r = math.sqrt(
        (from_lat - centre_lat) ** 2
        + ((from_lon - centre_lon) * cos_lat) ** 2
    )

    def from_angle(a: float) -> list[float]:
        lat = centre_lat + r * math.cos(a)
        lon = centre_lon + r * math.sin(a) / cos_lat
        return _geojson_coord(lat, lon)

    a_from = angle_of(from_lat, from_lon)
    a_to = angle_of(to_lat, to_lon)

    if clockwise:
        # CW means decreasing angle in standard math orientation
        if a_to >= a_from:
            a_to -= 2 * math.pi
    else:
        # CCW means increasing angle
        if a_to <= a_from:
            a_to += 2 * math.pi

    total_angle = abs(a_to - a_from)
    n_steps = max(2, int(math.ceil(total_angle / (2 * math.pi) * ARC_RESOLUTION)))
    step = (a_to - a_from) / n_steps

    coords = []
    for i in range(n_steps + 1):
        a = a_from + i * step
        coords.append(from_angle(a))
    return coords


def _interpolate_circle(
    centre_lat: float,
    centre_lon: float,
    radius_nm: float,
) -> list[list[float]]:
    """Return GeoJSON coords for a full circle (closed polygon ring)."""
    cos_lat = math.cos(_deg_to_rad(centre_lat))
    radius_lat = _nm_to_deg(radius_nm)
    radius_lon = radius_lat / cos_lat if cos_lat > 1e-9 else radius_lat

    coords = []
    for i in range(ARC_RESOLUTION):
        angle = 2 * math.pi * i / ARC_RESOLUTION
        lat = centre_lat + radius_lat * math.sin(angle)
        lon = centre_lon + radius_lon * math.cos(angle)
        coords.append(_geojson_coord(lat, lon))
    # close the ring
    coords.append(coords[0])
    return coords


# ---------------------------------------------------------------------------
# Boundary → polygon ring
# ---------------------------------------------------------------------------

def _boundary_to_ring(boundary: list[dict]) -> list[list[float]] | None:
    """
    Convert a YAIXM boundary list to a GeoJSON exterior ring (list of [lon,lat]).
    Returns None if conversion fails.
    """
    ring: list[list[float]] = []
    last_lat: float | None = None
    last_lon: float | None = None

    for segment in boundary:
        if "circle" in segment:
            circ = segment["circle"]
            centre_lat, centre_lon = parse_latlon(circ["centre"])
            radius_nm = float(str(circ["radius"]).split()[0])
            # A circle is self-contained — just return it
            return _interpolate_circle(centre_lat, centre_lon, radius_nm)

        elif "line" in segment:
            for pt_str in segment["line"]:
                lat, lon = parse_latlon(pt_str)
                ring.append(_geojson_coord(lat, lon))
                last_lat, last_lon = lat, lon

        elif "arc" in segment:
            arc = segment["arc"]
            if last_lat is None:
                # No preceding line — skip arc (shouldn't happen in valid data)
                continue
            centre_lat, centre_lon = parse_latlon(arc["centre"])
            to_lat, to_lon = parse_latlon(arc["to"])
            clockwise = arc.get("dir", "cw") == "cw"
            arc_coords = _interpolate_arc(
                last_lat, last_lon,
                to_lat, to_lon,
                centre_lat, centre_lon,
                float(str(arc.get("radius", "1 nm")).split()[0]),
                clockwise,
            )
            # Skip the first point (already added by the preceding line)
            ring.extend(arc_coords[1:])
            last_lat, last_lon = to_lat, to_lon

    if len(ring) < 3:
        return None

    # Close the ring
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    return ring


# ---------------------------------------------------------------------------
# YAIXM data → curated outlines
# ---------------------------------------------------------------------------

def find_feature(airspace_data: list[dict], name: str) -> dict:
    for feature in airspace_data:
        if feature.get("name") == name:
            return feature
    raise SystemExit(f"feature {name!r} not found in airspace.yaml")


def feature_rings(feature: dict) -> list[list[list[float]]]:
    """All volume boundaries of a feature as closed [lon,lat] rings."""
    rings = []
    for volume in feature.get("geometry", []):
        ring = _boundary_to_ring(volume["boundary"])
        if ring is None:
            raise SystemExit(f"unparseable boundary in {feature.get('name')!r}")
        rings.append(ring)
    return rings


def envelope_ring(rings: list[list[list[float]]]) -> list[list[float]]:
    """Exterior ring of the union of all rings, as a closed [lon,lat] ring.

    Adjacent volumes discretise shared arcs from different endpoints, so
    their edges are near- but not exactly coincident; the buffer in/out
    absorbs those slivers before taking the exterior.
    """
    polys = [Polygon(r).buffer(BUFFER_DEG) for r in rings]
    merged = unary_union(polys).buffer(-BUFFER_DEG).simplify(SIMPLIFY_DEG)
    if merged.geom_type != "Polygon":
        raise SystemExit(f"union produced {merged.geom_type}, expected Polygon")
    return [[round(lon, 6), round(lat, 6)] for lon, lat in merged.exterior.coords]


def check_ring(name: str, ring: list[list[float]]) -> None:
    if len(ring) < 4:
        raise SystemExit(f"{name}: only {len(ring)} points")
    for lon, lat in ring:
        if not (51.0 <= lat <= 53.0 and -1.2 <= lon <= 1.2):
            raise SystemExit(f"{name}: ({lat}, {lon}) outside local bounds")


def emit_header(outlines: list[tuple[str, list[list[float]]]], path: Path) -> None:
    out = [
        "// GENERATED by tools/build_airspace.py — do not edit by hand.",
        "// Source: https://github.com/ahsparrow/airspace (airspace.yaml)",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "namespace airspace {",
        "",
        "struct Vertex { float lat, lon; };",
        "struct Outline { const Vertex *pts; uint16_t count; };",
        "",
    ]
    for name, ring in outlines:
        out.append(f"static const Vertex {name}_PTS[] = {{")
        for lon, lat in ring:
            out.append(f"    {{{lat:.5f}f, {lon:.5f}f}},")
        out.append("};")
        out.append("")
    out.append("static const Outline OUTLINES[] = {")
    for name, ring in outlines:
        out.append(f"    {{{name}_PTS, {len(ring)}}},")
    out.append("};")
    out.append("")
    out.append("} // namespace airspace")
    path.write_text("\n".join(out) + "\n")


# ---------------------------------------------------------------------------
# Git fetch
# ---------------------------------------------------------------------------

def fetch_source() -> None:
    """Clone ahsparrow/airspace if absent, otherwise pull."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if REPO_DIR.exists():
        print(f"updating {REPO_DIR}", file=sys.stderr)
        subprocess.run(
            ["git", "-C", str(REPO_DIR), "pull", "--ff-only"],
            check=True,
        )
    else:
        print(f"cloning {REPO_URL} -> {REPO_DIR}", file=sys.stderr)
        subprocess.run(
            ["git", "clone", "--depth", "1", REPO_URL, str(REPO_DIR)],
            check=True,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    fetch_source()
    if not YAML_PATH.exists():
        print(f"expected {YAML_PATH} after clone, not found", file=sys.stderr)
        return 1

    with YAML_PATH.open() as f:
        airspace_data = yaml.safe_load(f).get("airspace", [])
    print(f"loaded {len(airspace_data)} YAIXM entries", file=sys.stderr)

    outlines = []
    for prefix, ctr_name, cta_name in CURATED_AIRPORTS:
        ctr_rings = feature_rings(find_feature(airspace_data, ctr_name))
        if len(ctr_rings) != 1:
            raise SystemExit(f"{ctr_name!r}: expected 1 volume, got {len(ctr_rings)}")
        cta_rings = feature_rings(find_feature(airspace_data, cta_name))
        outlines.append((f"{prefix}_CTR", ctr_rings[0]))
        outlines.append((f"{prefix}_ENV", envelope_ring(ctr_rings + cta_rings)))

    for name, ring in outlines:
        check_ring(name, ring)
        print(f"{name}: {len(ring)} points", file=sys.stderr)

    emit_header(outlines, OUTPUT_PATH)
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
