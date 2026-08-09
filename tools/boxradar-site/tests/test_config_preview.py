"""The scope preview.

Two kinds of test here. Most are ordinary geometry, but the first class is the
one that matters most: preview.py mirrors constants that really live in the
firmware, and a mirror nobody checks is just a copy waiting to be wrong. Those
tests parse src/ui/layout.h and fail if the two disagree — so changing the
panel geometry breaks this suite rather than quietly producing a preview of a
scope that no longer exists.
"""

import pathlib
import re
import unittest
import xml.etree.ElementTree as ET

from boxradar_config import preview
from boxradar_site.geo import selection

REPO = pathlib.Path(__file__).resolve().parents[3]
LAYOUT_H = REPO / "src" / "ui" / "layout.h"
SCOPE_CPP = REPO / "src" / "ui" / "scope.cpp"

HOME_LAT, HOME_LON = 51.8850, 0.2350


def constexpr_ints(text):
    """{name: value} for `constexpr int NAME = 123;` including comma lists."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*constexpr\s+int\s+(.*?);", line)
        if not m:
            continue
        for part in m.group(1).split(","):
            if "=" in part:
                name, value = part.split("=", 1)
                value = value.strip()
                if re.fullmatch(r"-?\d+", value):
                    out[name.strip()] = int(value)
    return out


def constexpr_floats(text):
    out = {}
    for name, value in re.findall(
            r"constexpr\s+float\s+(\w+)\s*=\s*(-?[\d.]+)f?;", text):
        out[name] = float(value)
    return out


@unittest.skipUnless(LAYOUT_H.exists(), "needs the firmware source")
class TestMirroredConstantsMatchTheFirmware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = LAYOUT_H.read_text()
        cls.ints = constexpr_ints(text)
        cls.floats = constexpr_floats(text)

    def test_panel_geometry(self):
        for name, mine in (("SCOPE_W", preview.SCOPE_W),
                           ("SCOPE_H", preview.SCOPE_H),
                           ("SCOPE_CX", preview.SCOPE_CX),
                           ("SCOPE_CY", preview.SCOPE_CY),
                           ("SCOPE_MARGIN", preview.SCOPE_MARGIN),
                           ("STATUS_H", preview.STATUS_H)):
            self.assertIn(name, self.ints, f"{name} vanished from layout.h")
            self.assertEqual(self.ints[name], mine, name)

    def test_the_panel_is_landscape(self):
        # The phase 4 note said "240x320". The scope is 320x240 — the panel is
        # rotated — and a portrait preview answers the crowding question for
        # the wrong aspect ratio.
        self.assertGreater(preview.SCOPE_W, preview.SCOPE_H)

    def test_overview_range(self):
        self.assertEqual(self.floats.get("OVERVIEW_NM"), preview.OVERVIEW_NM)

    def test_status_strip_position_is_derived_the_same_way(self):
        self.assertEqual(preview.STATUS_Y,
                         self.ints["SCOPE_H"] - self.ints["STATUS_H"])

    def test_the_documented_scales_come_out(self):
        # docs/viewport-design.md quotes 2.2 px/nm at the overview and
        # 11 px/nm at detail. If these stop holding, the doc or the panel
        # changed and this preview is drawing neither.
        self.assertAlmostEqual(preview.px_per_nm(50.0), 2.2, places=6)
        self.assertAlmostEqual(preview.px_per_nm(10.0), 11.0, places=6)

    @unittest.skipUnless(SCOPE_CPP.exists(), "needs scope.cpp")
    def test_centreline_extension_matches_scope_cpp(self):
        floats = constexpr_floats(SCOPE_CPP.read_text())
        self.assertEqual(floats.get("CENTRELINE_NM"), preview.CENTRELINE_NM)

    @unittest.skipUnless(SCOPE_CPP.exists(), "needs scope.cpp")
    def test_the_label_offset_still_has_no_collision_avoidance(self):
        """The premise of the whole page.

        Fixed references are drawn at a flat offset with nothing moving them
        apart, which is why an overlap here is an overlap on the panel. If
        scope.cpp ever grows placement logic for them, this preview starts
        lying and the omission has to be revisited.
        """
        text = SCOPE_CPP.read_text()
        block = text[text.index("drawFixedRefs"):]
        block = block[:block.index("drawRings")]
        self.assertEqual(block.count("drawString(f.name, x + 5, y - 3, 1)"), 1)
        self.assertNotIn("occupancy", block.lower())


def sel(**kwargs):
    return selection.Selection(HOME_LAT, HOME_LON, 65.0, [], **kwargs)


class Build:
    def __init__(self, outlines=(), coast=()):
        self.outlines = list(outlines)
        self.coast = list(coast)


class TestProjection(unittest.TestCase):
    def test_home_lands_at_the_scope_centre(self):
        shapes = preview.scene(Build(),
                               sel(airfields=[("HOME", HOME_LAT, HOME_LON)]),
                               50.0)
        marker = [s for s in shapes if s.kind == "square-solid"][0]
        self.assertAlmostEqual(marker.args[0], preview.SCOPE_CX, places=3)
        self.assertAlmostEqual(marker.args[1], preview.SCOPE_CY, places=3)

    def test_north_is_up(self):
        shapes = preview.scene(
            Build(), sel(airfields=[("N", HOME_LAT + 0.1, HOME_LON)]), 50.0)
        marker = [s for s in shapes if s.kind == "square-solid"][0]
        self.assertLess(marker.args[1], preview.SCOPE_CY)

    def test_east_is_right(self):
        shapes = preview.scene(
            Build(), sel(airfields=[("E", HOME_LAT, HOME_LON + 0.1)]), 50.0)
        marker = [s for s in shapes if s.kind == "square-solid"][0]
        self.assertGreater(marker.args[0], preview.SCOPE_CX)

    def test_longitude_is_scaled_by_latitude(self):
        # A degree of longitude at 51.9N is about 37nm, not 60.
        east, _ = preview.project(HOME_LAT, HOME_LON, HOME_LAT, HOME_LON + 1)
        self.assertAlmostEqual(east, 37.0, delta=0.6)

    def test_ten_nm_north_is_110_px_up_at_detail(self):
        # The whole usable radius is 110px, so 10nm at the 10nm range is it.
        _, north = preview.project(HOME_LAT, HOME_LON, HOME_LAT + 10 / 60.0,
                                   HOME_LON)
        view = preview.View(10.0)
        self.assertAlmostEqual(view.y(north), preview.SCOPE_CY - 110,
                               places=3)


class TestMarkers(unittest.TestCase):
    def test_shapes_distinguish_the_categories(self):
        shapes = preview.scene(Build(), sel(
            airfields=[("EGSS", 51.885, 0.235)],
            waypoints=[("BKY", 51.9897, 0.06194)],
            towns=[("STVG", 51.90167, -0.20272)]), 50.0)
        kinds = {s.kind for s in shapes}
        self.assertIn("square-solid", kinds)   # airfield
        self.assertIn("triangle", kinds)       # fix, chart convention
        self.assertIn("square-hollow", kinds)  # town

    def test_every_marker_gets_a_label(self):
        shapes = preview.scene(Build(), sel(
            airfields=[("EGSS", 51.885, 0.235)],
            towns=[("STVG", 51.90167, -0.20272)]), 50.0)
        self.assertEqual(len([s for s in shapes if s.kind == "label"]), 2)

    def test_the_label_sits_at_the_firmware_offset(self):
        shapes = preview.scene(Build(),
                               sel(airfields=[("HOME", HOME_LAT, HOME_LON)]),
                               50.0)
        marker = [s for s in shapes if s.kind == "square-solid"][0]
        label = [s for s in shapes if s.kind == "label"][0]
        self.assertAlmostEqual(label.args[0] - marker.args[0], 5)
        self.assertAlmostEqual(label.args[1] - marker.args[1], -3)

    def test_something_far_away_is_culled(self):
        shapes = preview.scene(
            Build(), sel(airfields=[("FAR", HOME_LAT + 5, HOME_LON)]), 50.0)
        self.assertEqual([s for s in shapes if s.kind == "square-solid"], [])

    def test_zooming_in_culls_what_leaves_the_panel(self):
        # 20nm north is on the 50nm overview and off the 10nm detail view.
        far = sel(airfields=[("N20", HOME_LAT + 20 / 60.0, HOME_LON)])
        self.assertTrue([s for s in preview.scene(Build(), far, 50.0)
                         if s.kind == "square-solid"])
        self.assertFalse([s for s in preview.scene(Build(), far, 10.0)
                          if s.kind == "square-solid"])


class TestCentrelines(unittest.TestCase):
    EGSS = (51.875081, 0.219933, 51.895166, 0.250050)

    def test_a_centreline_is_dashed(self):
        shapes = preview.scene(Build(), sel(runways=[self.EGSS]), 10.0)
        lines = [s for s in shapes if s.kind == "line"]
        self.assertGreater(len(lines), 4, "should be many dashes, not one line")

    def test_it_extends_well_past_both_thresholds(self):
        shapes = preview.scene(Build(), sel(runways=[self.EGSS]), 10.0)
        lines = [s for s in shapes if s.kind == "line"]
        xs = [p[0] for s in lines for p in s.args]
        ys = [p[1] for s in lines for p in s.args]
        view = preview.View(10.0)
        a = preview.project(HOME_LAT, HOME_LON, self.EGSS[0], self.EGSS[1])
        b = preview.project(HOME_LAT, HOME_LON, self.EGSS[2], self.EGSS[3])
        # The drawn span should be much longer than the runway itself.
        runway_px = math_hypot(view.x(a[0]) - view.x(b[0]),
                               view.y(a[1]) - view.y(b[1]))
        drawn = math_hypot(max(xs) - min(xs), max(ys) - min(ys))
        self.assertGreater(drawn, runway_px * 3)

    def test_a_degenerate_runway_is_skipped_not_divided_by(self):
        shapes = preview.scene(
            Build(), sel(runways=[(51.9, 0.03, 51.9, 0.03)]), 10.0)
        self.assertEqual([s for s in shapes if s.kind == "line"], [])


def math_hypot(a, b):
    return (a * a + b * b) ** 0.5


class TestCrowding(unittest.TestCase):
    def test_two_labels_on_top_of_each_other_collide(self):
        shapes = preview.scene(Build(), sel(towns=[
            ("AAAA", 51.95, 0.03), ("BBBB", 51.9501, 0.0301)]), 50.0)
        self.assertEqual(len(preview.collisions(shapes)), 1)

    def test_well_separated_labels_do_not(self):
        shapes = preview.scene(Build(), sel(towns=[
            ("AAAA", 51.95, -0.4), ("BBBB", 51.75, 0.5)]), 50.0)
        self.assertEqual(preview.collisions(shapes), [])

    def test_zooming_in_separates_them(self):
        """The point of showing both scales: crowding is a property of the
        scale, not of the selection.

        Two nautical miles apart north-south. A label box is 8px tall, so at
        the overview's 2.2 px/nm they are 4.4px apart and overlap; at the
        detail scale's 11 px/nm they are 22px apart and do not.
        """
        towns = sel(towns=[("AAAA", HOME_LAT, HOME_LON),
                           ("BBBB", HOME_LAT + 2 / 60.0, HOME_LON)])
        self.assertTrue(preview.collisions(preview.scene(Build(), towns, 50.0)))
        self.assertFalse(preview.collisions(preview.scene(Build(), towns,
                                                          10.0)))

    def test_a_label_box_is_six_pixels_a_character(self):
        shapes = preview.scene(Build(),
                               sel(towns=[("ABCDE", HOME_LAT, HOME_LON)]),
                               50.0)
        x0, _, x1, _, text = preview.label_boxes(shapes)[0]
        self.assertEqual(text, "ABCDE")
        self.assertAlmostEqual(x1 - x0, 30)  # 5 chars x 6px


class TestOutlinesAndCoast(unittest.TestCase):
    def test_an_outline_is_drawn(self):
        ring = [(0.0, 51.8), (0.2, 51.8), (0.2, 52.0), (0.0, 52.0),
                (0.0, 51.8)]  # emit's [lon, lat]
        shapes = preview.scene(Build(outlines=[("X", ring)]), sel(), 50.0)
        polys = [s for s in shapes if s.kind == "polyline"]
        self.assertEqual(len(polys), 1)
        self.assertEqual(len(polys[0].args), 5)

    def test_outlines_use_lon_lat_from_emit(self):
        # A ring read the wrong way round puts Essex airspace in the Atlantic,
        # and it still draws — so this is worth pinning.
        ring = [(0.2350, 52.3850), (0.2350, 52.3850), (0.2350, 52.3850)]
        shapes = preview.scene(Build(outlines=[("X", ring)]), sel(), 50.0)
        poly = [s for s in shapes if s.kind == "polyline"][0]
        # lon 0.2350 == home lon, so x must be the scope centre.
        self.assertAlmostEqual(poly.args[0][0], preview.SCOPE_CX, places=3)

    def test_the_coast_is_drawn_under_the_airspace(self):
        ring = [(0.0, 51.8), (0.2, 51.8), (0.2, 52.0)]
        coast = [[(51.9, 0.9), (51.95, 1.0)]]
        shapes = preview.scene(Build(outlines=[("X", ring)], coast=coast),
                               sel(), 50.0)
        polys = [s for s in shapes if s.kind == "polyline"]
        self.assertEqual(polys[0].colour, preview.COASTLINE)
        self.assertEqual(polys[1].colour, preview.AIRSPACE_LINE)

    def test_range_rings_are_drawn(self):
        shapes = preview.scene(Build(), sel(), 50.0)
        circles = [s for s in shapes if s.kind == "circle"]
        self.assertEqual(len(circles), 2)
        self.assertAlmostEqual(circles[1].args[2], 110.0, places=3)


class TestSvg(unittest.TestCase):
    def build_svg(self, **kwargs):
        return preview.to_svg(preview.scene(Build(), sel(**kwargs), 50.0))

    def test_the_output_is_well_formed_xml(self):
        ET.fromstring(self.build_svg(airfields=[("EGSS", 51.885, 0.235)]))

    def test_the_viewbox_is_the_panel(self):
        root = ET.fromstring(self.build_svg())
        self.assertEqual(root.get("viewBox"), "0 0 320 240")

    def test_enlarging_does_not_change_the_viewbox(self):
        # Otherwise the picture gets roomier as you zoom it and the crowding
        # answer becomes reassuringly wrong.
        svg = preview.to_svg(preview.scene(Build(), sel(), 50.0),
                             scale_factor=4)
        root = ET.fromstring(svg)
        self.assertEqual(root.get("viewBox"), "0 0 320 240")
        self.assertEqual(root.get("width"), "1280")

    def test_a_label_with_markup_characters_is_escaped(self):
        svg = self.build_svg(towns=[("A<B>", 51.92, 0.03)])
        ET.fromstring(svg)
        self.assertIn("A&lt;B&gt;", svg)

    def test_labels_are_pinned_to_the_fixed_advance(self):
        svg = self.build_svg(airfields=[("EGSS", 51.885, 0.235)])
        self.assertIn('textLength="24"', svg)  # 4 chars x 6px


if __name__ == "__main__":
    unittest.main()
