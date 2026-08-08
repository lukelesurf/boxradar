"""Ring merging and validation. The only shapely-dependent module.

Ported from tools/build_airspace.py. One behaviour change: check_ring()
returns a list of problems instead of raising SystemExit, because these
messages now have to reach a user in a browser rather than a terminal.
"""

from shapely.geometry import LinearRing, Polygon
from shapely.ops import unary_union

# ~60m: merges near-coincident arc discretisations. Adjacent volumes
# discretise shared arcs from different endpoints, so their edges are near-
# but not exactly coincident; the buffer in/out absorbs those slivers before
# taking the exterior.
BUFFER_DEG = 0.001
# ~35m: invisible at scope scale, trims point count.
SIMPLIFY_DEG = 0.0005

MIN_RING_POINTS = 4


def merge_rings(rings):
    """Exterior ring(s) of the union of all rings, as closed [lon,lat] rings.

    Returns ONE ring when the volumes touch or overlap — the common case,
    where a CTR and its CTA shelves form a single envelope. Returns several
    when they are genuinely disjoint, which is not an error: the Stansted TMZ
    is two separate lobes either side of the field, under the 04 and 22
    approaches, and merging them would invent airspace between them.
    """
    polys = [Polygon(r).buffer(BUFFER_DEG) for r in rings]
    merged = unary_union(polys).buffer(-BUFFER_DEG).simplify(SIMPLIFY_DEG)
    geoms = list(merged.geoms) if merged.geom_type == "MultiPolygon" \
        else [merged]
    out = []
    for g in geoms:
        if g.geom_type != "Polygon":
            continue
        out.append([[round(lon, 6), round(lat, 6)]
                    for lon, lat in g.exterior.coords])
    return out


def build_outlines(name, rings):
    """One outline, or several suffixed ones if the volumes are disjoint."""
    merged = merge_rings(rings)
    if len(merged) == 1:
        return [(name, merged[0])]
    return [(f"{name}{i}", r) for i, r in enumerate(merged)]


def check_ring(name, ring):
    """Problems with a ring, as human-readable strings. Empty means fine."""
    problems = []
    if len(ring) < MIN_RING_POINTS:
        problems.append(f"{name}: only {len(ring)} points")
        return problems  # the geometry checks below would raise on this
    try:
        if not LinearRing([(lon, lat) for lon, lat in ring]).is_simple:
            problems.append(f"{name}: ring self-intersects")
    except Exception as e:  # shapely raises various things on degenerate input
        problems.append(f"{name}: unusable ring ({e})")
    return problems
