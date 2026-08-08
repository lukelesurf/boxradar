"""YAIXM source parsing: coordinates, arcs, circles, boundaries to rings.

Ported from tools/build_airspace.py. stdlib + math only, deliberately — this
is the half of the geometry pipeline that needs no shapely, and keeping it
separate is what makes it cheap to test.

Two behaviour changes from the original, both because the catalog walks all
703 UK features rather than a hand-picked dozen:

  * feature_rings() skips an unparseable boundary instead of raising SystemExit
  * feature_kind() is new — see its docstring
"""

import math
import re

# Arc interpolation resolution: points per full circle (36 = 10 degree steps).
ARC_RESOLUTION = 36

# Lat/lon DMS pattern: [D]DDMMSS[.sss]H
_DMS_RE = re.compile(
    r"(?P<d>[0-9]{2}|[01][0-9]{2})(?P<m>[0-5][0-9])"
    r"(?P<s>[0-5][0-9](?:\.[0-9]{1,3})?)(?P<h>[NESW])"
)


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def parse_latlon(s):
    """Parse a YAIXM coordinate string (e.g. '512345N 0001234W') to (lat, lon)."""
    parts = str(s).split()
    if len(parts) != 2:
        raise ValueError(f"bad latlon: {s!r}")
    return _parse_deg(parts[0]), _parse_deg(parts[1])


def _parse_deg(s):
    m = _DMS_RE.match(s)
    if m is None:
        raise ValueError(f"bad DMS: {s!r}")
    deg = int(m.group("d")) + int(m.group("m")) / 60 \
        + float(m.group("s")) / 3600
    if m.group("h") in "SW":
        deg = -deg
    return deg


def _nm_to_deg(nm):
    """Nautical miles to degrees of latitude (approximate)."""
    return nm / 60.0


def _deg_to_rad(d):
    return d * math.pi / 180.0


def _geojson_coord(lat, lon):
    """GeoJSON is [lon, lat]."""
    return [round(lon, 6), round(lat, 6)]


# ---------------------------------------------------------------------------
# Arcs and circles
# ---------------------------------------------------------------------------

def _interpolate_arc(from_lat, from_lon, to_lat, to_lon,
                     centre_lat, centre_lon, radius_nm, clockwise):
    """GeoJSON coords interpolating the arc between two points around a centre.

    Uses a simple equirectangular approximation — sufficient for small areas
    at UK latitudes. Points are appended at ARC_RESOLUTION steps per full
    circle.
    """
    # Work in "flat" coordinates scaled so that degrees-lat ~= degrees-lon.
    # Scale lon by cos(centre_lat) so equal angular steps produce roughly
    # equal arc lengths on the ground.
    cos_lat = math.cos(_deg_to_rad(centre_lat))

    def to_xy(lat, lon):
        return (lat - centre_lat, (lon - centre_lon) * cos_lat)

    def angle_of(lat, lon):
        x, y = to_xy(lat, lon)
        return math.atan2(y, x)

    # The YAIXM "radius" field is informational; the actual from-point
    # distance is the truth.
    r = math.sqrt((from_lat - centre_lat) ** 2
                  + ((from_lon - centre_lon) * cos_lat) ** 2)

    def from_angle(a):
        lat = centre_lat + r * math.cos(a)
        lon = centre_lon + r * math.sin(a) / cos_lat
        return _geojson_coord(lat, lon)

    a_from = angle_of(from_lat, from_lon)
    a_to = angle_of(to_lat, to_lon)

    if clockwise:
        # Bearing convention (atan2(east, north)): CW means increasing angle
        if a_to <= a_from:
            a_to += 2 * math.pi
    else:
        # CCW means decreasing angle
        if a_to >= a_from:
            a_to -= 2 * math.pi

    total_angle = abs(a_to - a_from)
    n_steps = max(2, int(math.ceil(total_angle / (2 * math.pi)
                                   * ARC_RESOLUTION)))
    step = (a_to - a_from) / n_steps
    return [from_angle(a_from + i * step) for i in range(n_steps + 1)]


def _interpolate_circle(centre_lat, centre_lon, radius_nm):
    """GeoJSON coords for a full circle, as a closed ring."""
    cos_lat = math.cos(_deg_to_rad(centre_lat))
    radius_lat = _nm_to_deg(radius_nm)
    radius_lon = radius_lat / cos_lat if cos_lat > 1e-9 else radius_lat

    coords = []
    for i in range(ARC_RESOLUTION):
        angle = 2 * math.pi * i / ARC_RESOLUTION
        lat = centre_lat + radius_lat * math.sin(angle)
        lon = centre_lon + radius_lon * math.cos(angle)
        coords.append(_geojson_coord(lat, lon))
    coords.append(coords[0])  # close the ring
    return coords


# ---------------------------------------------------------------------------
# Boundary -> polygon ring
# ---------------------------------------------------------------------------

def boundary_to_ring(boundary):
    """A YAIXM boundary list as a closed GeoJSON exterior ring of [lon, lat].

    Returns None if the boundary cannot be converted — which for the catalog
    is an ordinary outcome, not an error.
    """
    ring = []
    last_lat = None
    last_lon = None

    for segment in boundary or []:
        if not isinstance(segment, dict):
            continue
        try:
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
                    # No preceding line — skip (should not happen in valid data)
                    continue
                centre_lat, centre_lon = parse_latlon(arc["centre"])
                to_lat, to_lon = parse_latlon(arc["to"])
                clockwise = arc.get("dir", "cw") == "cw"
                arc_coords = _interpolate_arc(
                    last_lat, last_lon, to_lat, to_lon,
                    centre_lat, centre_lon,
                    float(str(arc.get("radius", "1 nm")).split()[0]),
                    clockwise,
                )
                # Skip the first point (already added by the preceding line)
                ring.extend(arc_coords[1:])
                last_lat, last_lon = to_lat, to_lon
        except (ValueError, KeyError, TypeError, IndexError):
            return None

    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def feature_rings(feature):
    """All volume boundaries of a feature as closed [lon, lat] rings.

    Unparseable volumes are skipped. The original raised SystemExit here, which
    was correct for a script that only ever saw hand-picked features and wrong
    for a catalog that walks the whole dataset.
    """
    rings = []
    for volume in feature.get("geometry", []) or []:
        if not isinstance(volume, dict):
            continue
        ring = boundary_to_ring(volume.get("boundary", []))
        if ring is None:
            continue
        rings.append(ring)
    return rings


def feature_kind(feature):
    """A single display string from (type, localtype, rules).

    type alone is not enough. The Stansted TMZ is type OTHER with localtype
    TMZ, and OTHER also holds a dozen MATZs, ILS feathers and gliding sites —
    so a picker that showed only `type` would present them as identical.
    """
    base = str(feature.get("type") or "") or "?"
    local = str(feature.get("localtype") or "")
    if not local:
        rules = feature.get("rules") or []
        if "TMZ" in rules:
            local = "TMZ"
    return f"{base}/{local}" if local else base
