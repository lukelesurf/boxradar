"""What the scope would look like, before flashing anything.

The question this answers is "are these labels too crowded?", which today is
answered by regenerating, flashing, and squinting at the shelf. It draws the
selected markers, labels and outlines at the panel's real geometry and scales,
and nothing else.

**No traffic, deliberately.** The scoping note warns against reimplementing
`datablock.cpp`, and it is right: that file places aircraft labels with an
occupancy grid, and a second copy of it would drift from the firmware silently.

But that warning does not extend to the fixed references, and this is the part
worth knowing. `drawFixedRefs()` in src/ui/scope.cpp places airfield, fix and
town labels at a flat `(x + 5, y - 3)` offset with **no collision avoidance at
all** — the occupancy grid exists only for traffic. So the crowding this page
has to reveal is exactly that fixed-offset overlap, and reproducing it is a
matter of copying two integers rather than a placement algorithm. Within what
it draws, this is faithful; the roughness is in what it leaves out.

Everything below mirrors constants that live in the firmware. That is a real
duplication and it is guarded rather than hoped about: test_config_preview.py
parses src/ui/layout.h and fails if these drift from it.
"""

import math
from collections import namedtuple

# ------------------------------------------------------------------ mirrored
# src/ui/layout.h. Checked against that file by the tests.
SCOPE_W, SCOPE_H = 320, 240
SCOPE_CX, SCOPE_CY = 160, 116
SCOPE_MARGIN = 6
STATUS_H = 10
STATUS_Y = SCOPE_H - STATUS_H
OVERVIEW_NM = 50.0
DETAIL_RANGES_NM = (10.0, 5.0)

# src/ui/scope.cpp
CENTRELINE_NM = 6.5      # extension beyond each threshold
DASH_ON, DASH_OFF = 6, 5
MARKER = 5               # airfields fillRect(x-2, y-2, 5, 5); towns drawRect
LABEL_DX, LABEL_DY = 5, -3
FONT_W, FONT_H = 6, 8    # TFT_eSPI font 1 — the "every character is 6px" note

NM_PER_DEG_LAT = 60.0

# src/ui/palette.h, resolved out of RGB332. The sprite is 8-bit, so these are
# the colours that actually survive quantisation — writing 565 literals here
# would show shades the panel cannot produce.
def _rgb332(r3, g3, b2):
    return "#%02x%02x%02x" % (round(r3 * 255 / 7), round(g3 * 255 / 7),
                              round(b2 * 255 / 3))


AIRSPACE_LINE = _rgb332(2, 2, 1)
CENTRELINE = AIRSPACE_LINE
AIRFIELD_MARK = _rgb332(3, 3, 1)
COASTLINE = _rgb332(1, 1, 0)
RING = "#005000"          # TFT_DARKGREEN
BACKGROUND = "#000000"

Shape = namedtuple("Shape", "kind args colour label")


def lon_scale_nm(home_lat):
    """NM per degree of longitude at that latitude. radar::lonScaleNm."""
    return NM_PER_DEG_LAT * math.cos(math.radians(home_lat))


def project(home_lat, home_lon, lat, lon, scale=None):
    """(east NM, north NM) from home. radar::projectWith."""
    scale = lon_scale_nm(home_lat) if scale is None else scale
    return ((lon - home_lon) * scale, (lat - home_lat) * NM_PER_DEG_LAT)


def px_per_nm(range_nm):
    """layout.h scopePxPerNm — height-bound, so the ring fits vertically."""
    return (SCOPE_CY - SCOPE_MARGIN) / range_nm


class View:
    """Viewport, home-centred. The firmware's detail view can be panned; this
    one never is, because the question is about the map rather than about
    where you last tapped."""

    def __init__(self, range_nm):
        self.range_nm = range_nm
        self.scale = px_per_nm(range_nm)

    def x(self, east_nm):
        return SCOPE_CX + east_nm * self.scale

    def y(self, north_nm):
        return SCOPE_CY - north_nm * self.scale

    def visible(self, x, y):
        """scope.cpp's cull for fixed references, exactly."""
        return not (x < -4 or x >= SCOPE_W or y < 4 or y >= STATUS_Y - 4)


def _polyline(view, points, scale, home_lat, home_lon, colour):
    """A ring or segment as one shape, or None if it is entirely off-panel."""
    pts, on = [], False
    for lat, lon in points:
        east, north = project(home_lat, home_lon, lat, lon, scale)
        x, y = view.x(east), view.y(north)
        pts.append((x, y))
        # Kept whole rather than clipped: an outline that leaves the panel and
        # comes back is one shape, and clipping each span would turn a CTR
        # into confetti. One point inside is enough to draw it.
        on = on or (-SCOPE_W <= x <= 2 * SCOPE_W and -SCOPE_H <= y
                    <= 2 * SCOPE_H)
    if not on or len(pts) < 2:
        return None
    return Shape("polyline", pts, colour, None)


def _dashes(x0, y0, x1, y1):
    """scope.cpp drawDashedLine, in pixel space."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1.0:
        return []
    ux, uy = dx / length, dy / length
    out, d = [], 0.0
    while d < length:
        e = min(d + DASH_ON, length)
        out.append(((x0 + ux * d, y0 + uy * d), (x0 + ux * e, y0 + uy * e)))
        d += DASH_ON + DASH_OFF
    return out


def scene(build, sel, range_nm):
    """Every shape the scope would draw for this selection, in draw order.

    Order matters and follows scope.cpp: coastline underneath, then airspace
    and centrelines as one background layer, then markers on top. It is why
    the palette puts the coast a rung below the airspace lines.
    """
    home_lat, home_lon = sel.home_lat, sel.home_lon
    scale = lon_scale_nm(home_lat)
    view = View(range_nm)
    shapes = []

    for segment in build.coast:
        shape = _polyline(view, segment, scale, home_lat, home_lon, COASTLINE)
        if shape:
            shapes.append(shape)

    for _, ring in build.outlines:
        # emit stores [lon, lat]; everything here is (lat, lon).
        shape = _polyline(view, [(lat, lon) for lon, lat in ring], scale,
                          home_lat, home_lon, AIRSPACE_LINE)
        if shape:
            shapes.append(shape)

    for lat0, lon0, lat1, lon1 in sel.runways:
        ax, ay = project(home_lat, home_lon, lat0, lon0, scale)
        bx, by = project(home_lat, home_lon, lat1, lon1, scale)
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1e-4:
            continue  # degenerate entry: skip rather than divide
        ux, uy = dx / length, dy / length
        # Extended past BOTH thresholds — the stretch between them is under
        # 2nm and is not the interesting part; the approach paths are.
        for a, b in _dashes(view.x(ax - ux * CENTRELINE_NM),
                            view.y(ay - uy * CENTRELINE_NM),
                            view.x(bx + ux * CENTRELINE_NM),
                            view.y(by + uy * CENTRELINE_NM)):
            shapes.append(Shape("line", (a, b), CENTRELINE, None))

    # Rings at 1/2 and full range. Only honest on a home-centred view, which
    # this always is.
    for i in (1, 2):
        shapes.append(Shape("circle",
                            (view.x(0), view.y(0),
                             view.scale * range_nm * i / 2.0), RING, None))

    for name, lat, lon in sel.airfields:
        shapes.extend(_marker(view, scale, home_lat, home_lon, lat, lon, name,
                              "square-solid", AIRFIELD_MARK))
    for name, lat, lon in sel.waypoints:
        shapes.extend(_marker(view, scale, home_lat, home_lon, lat, lon, name,
                              "triangle", AIRSPACE_LINE))
    for name, lat, lon in sel.towns:
        shapes.extend(_marker(view, scale, home_lat, home_lon, lat, lon, name,
                              "square-hollow", AIRSPACE_LINE))
    return shapes


def _marker(view, scale, home_lat, home_lon, lat, lon, name, kind, colour):
    east, north = project(home_lat, home_lon, lat, lon, scale)
    x, y = view.x(east), view.y(north)
    if not view.visible(x, y):
        return []
    return [Shape(kind, (x, y), colour, None),
            Shape("label", (x + LABEL_DX, y + LABEL_DY), colour, str(name))]


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def to_svg(shapes, scale_factor=2):
    """The scene as SVG at the panel's true pixel geometry.

    `scale_factor` only enlarges the rendered box; the viewBox stays 320x240,
    so every coordinate, marker and label is still the size it will be on the
    panel relative to everything else. Zooming the picture must not quietly
    make the labels roomier than they really are — that would answer the
    question wrongly and reassuringly.
    """
    out = [f'<svg class="scope" viewBox="0 0 {SCOPE_W} {SCOPE_H}" '
           f'width="{SCOPE_W * scale_factor}" '
           f'height="{SCOPE_H * scale_factor}" '
           f'xmlns="http://www.w3.org/2000/svg" role="img" '
           f'aria-label="scope preview">',
           f'<rect width="{SCOPE_W}" height="{SCOPE_H}" fill="{BACKGROUND}"/>']
    for shape in shapes:
        colour = shape.colour
        if shape.kind == "polyline":
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in shape.args)
            out.append(f'<polyline points="{pts}" fill="none" '
                       f'stroke="{colour}" stroke-width="1"/>')
        elif shape.kind == "line":
            (x0, y0), (x1, y1) = shape.args
            out.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" '
                       f'y2="{y1:.1f}" stroke="{colour}" stroke-width="1"/>')
        elif shape.kind == "circle":
            x, y, r = shape.args
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                       f'fill="none" stroke="{colour}" stroke-width="1"/>')
        elif shape.kind in ("square-solid", "square-hollow"):
            x, y = shape.args
            fill = colour if shape.kind == "square-solid" else "none"
            stroke = "none" if shape.kind == "square-solid" else colour
            out.append(f'<rect x="{x - 2:.1f}" y="{y - 2:.1f}" '
                       f'width="{MARKER}" height="{MARKER}" fill="{fill}" '
                       f'stroke="{stroke}" stroke-width="1"/>')
        elif shape.kind == "triangle":
            x, y = shape.args
            out.append(f'<polygon points="{x:.1f},{y - 3:.1f} '
                       f'{x - 3:.1f},{y + 2:.1f} {x + 3:.1f},{y + 2:.1f}" '
                       f'fill="none" stroke="{colour}" stroke-width="1"/>')
        elif shape.kind == "label":
            x, y = shape.args
            # textLength pins the advance to the firmware's fixed 6px a
            # character, so what you see is what label_boxes() measured.
            out.append(f'<text x="{x:.1f}" y="{y + FONT_H - 1:.1f}" '
                       f'fill="{colour}" font-family="monospace" '
                       f'font-size="{FONT_H}" '
                       f'textLength="{FONT_W * len(shape.label)}" '
                       f'lengthAdjust="spacingAndGlyphs">'
                       f'{_esc(shape.label)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def label_boxes(shapes):
    """Pixel rectangles the labels occupy, for the crowding report."""
    out = []
    for shape in shapes:
        if shape.kind != "label":
            continue
        x, y = shape.args
        out.append((x, y, x + FONT_W * len(shape.label), y + FONT_H,
                    shape.label))
    return out


def collisions(shapes):
    """Pairs of labels whose boxes overlap.

    This is the number the page exists to produce. The firmware does not move
    these labels out of each other's way — it has no mechanism to — so an
    overlap here is an overlap on the shelf.
    """
    boxes = label_boxes(shapes)
    out = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                out.append((a[4], b[4]))
    return out
