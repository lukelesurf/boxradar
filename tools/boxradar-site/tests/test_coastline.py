import math
import pathlib
import unittest

from boxradar_site.geo import coastline

REACH_DEG = (coastline.MAX_RANGE_NM + coastline.MARGIN_NM) / 60.0


class TestQueryBox(unittest.TestCase):
    def test_box_sits_on_the_half_degree_grid(self):
        for v in coastline.query_box(51.9, 0.0):
            self.assertAlmostEqual(v % coastline.BOX_ROUND_DEG, 0.0, places=6,
                                   msg=f"{v} is not on the grid")

    def test_box_contains_home_plus_full_reach(self):
        lat, lon = 51.9, 0.0
        s, w, n, e = coastline.query_box(lat, lon)
        dlon = REACH_DEG / math.cos(math.radians(lat))
        self.assertLessEqual(s, lat - REACH_DEG)
        self.assertGreaterEqual(n, lat + REACH_DEG)
        self.assertLessEqual(w, lon - dlon)
        self.assertGreaterEqual(e, lon + dlon)

    def test_longitude_span_is_wider_than_latitude_span(self):
        # A degree of longitude at 51.9N is only ~37nm, so reaching the same
        # distance east takes more degrees than reaching it north.
        s, w, n, e = coastline.query_box(51.9, 0.0)
        self.assertGreater(e - w, n - s)

    def test_nearby_homes_share_a_box(self):
        # BOX_ROUND_DEG exists so the emitted extent cannot give the scope
        # centre away. Rounding outward is what makes that true.
        self.assertEqual(coastline.query_box(51.90, 0.03),
                         coastline.query_box(51.91, 0.04))


class TestBboxOf(unittest.TestCase):
    def test_bounds_a_segment(self):
        seg = [(51.0, -0.5), (52.0, 0.5), (51.5, 0.0)]
        self.assertEqual(coastline.bbox_of(seg), (51.0, 52.0, -0.5, 0.5))

    def test_single_point(self):
        self.assertEqual(coastline.bbox_of([(51.0, 0.0)]),
                         (51.0, 51.0, 0.0, 0.0))


class TestRenderHeader(unittest.TestCase):
    SEGS = [[(51.0, -0.5), (52.0, 0.5)], [(50.5, 1.0), (50.6, 1.1)]]

    def test_emits_one_array_per_segment(self):
        text = coastline.render_header(self.SEGS)
        self.assertIn("SEG_0_PTS", text)
        self.assertIn("SEG_1_PTS", text)
        self.assertNotIn("SEG_2_PTS", text)

    def test_declares_the_segment_table(self):
        text = coastline.render_header(self.SEGS)
        self.assertIn("static const Outline SEGMENTS[]", text)

    def test_header_carries_bboxes_even_though_the_blob_does_not(self):
        # The blob computes them at load, because a stored bbox can disagree
        # with its own points. The header keeps them because the current
        # firmware's Outline struct has the fields.
        text = coastline.render_header(self.SEGS)
        self.assertIn("minLat", text)
        self.assertIn("{SEG_0_PTS, 2, 51.0f, 52.0f, -0.5f, 0.5f}", text)

    def test_counts_are_in_the_provenance_comment(self):
        text = coastline.render_header(self.SEGS)
        self.assertIn("2 segments, 4 points", text)

    def test_empty_input_still_produces_a_valid_header(self):
        text = coastline.render_header([])
        self.assertIn("namespace coastline", text)
        self.assertIn("static const Outline SEGMENTS[]", text)


if __name__ == "__main__":
    unittest.main()


class TestReducedCache(unittest.TestCase):
    """Caching the reduced segments, not just the Overpass response.

    fetch() already caches the raw extract, which saves the network but not
    the reduction — and on a Pi the reduction is ~29s against ~0.1s to build
    the airspace, so a service restart used to cost half a minute on the first
    page that wanted a coast.
    """

    BBOX = (51.0, -0.5, 52.5, 1.5)
    HOME = (51.8850, 0.2350)

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache = pathlib.Path(self.dir.name)
        self.built = []

    def patched(self):
        """segments_cached with the expensive halves counted, not run."""
        from unittest import mock
        from boxradar_site.geo import coastline

        def fake_segments(data, lat, lon):
            self.built.append((lat, lon))
            return [[(51.9, 0.9), (51.95, 1.0)]]

        return mock.patch.multiple(coastline, segments=fake_segments,
                                   fetch=lambda bbox, d: {"elements": []})

    def call(self, home=None):
        from boxradar_site.geo import coastline
        lat, lon = home or self.HOME
        with self.patched():
            return coastline.segments_cached(self.BBOX, self.cache, lat, lon)

    def test_the_first_call_reduces(self):
        self.assertEqual(len(self.call()), 1)
        self.assertEqual(len(self.built), 1)

    def test_the_second_call_does_not(self):
        self.call()
        got = self.call()
        self.assertEqual(len(self.built), 1, "reduced twice")
        self.assertEqual(got, [[(51.9, 0.9), (51.95, 1.0)]])

    def test_tuples_survive_the_json_round_trip(self):
        self.call()
        for segment in self.call():
            for point in segment:
                self.assertIsInstance(point, tuple)

    def test_moving_home_invalidates_it(self):
        # The clip circle is centred on home, so the cached segments are
        # simply wrong for a new position rather than merely stale.
        self.call()
        self.call(home=(52.5, -1.0))
        self.assertEqual(len(self.built), 2)

    def test_changing_a_reduction_constant_invalidates_it(self):
        from unittest import mock
        from boxradar_site.geo import coastline
        self.call()
        with mock.patch.object(coastline, "SIMPLIFY_M", 250.0):
            self.call()
        self.assertEqual(len(self.built), 2)

    def test_a_corrupt_cache_is_rebuilt_rather_than_raising(self):
        from boxradar_site.geo import coastline
        self.call()
        coastline.reduced_cache_path(self.BBOX, self.cache).write_text("{nope")
        self.assertEqual(len(self.call()), 1)
        self.assertEqual(len(self.built), 2)

    def test_the_filename_does_not_carry_home(self):
        # The raw cache is named for a deliberately coarse box so it does not
        # give the scope centre away; the reduced one must not undo that.
        from boxradar_site.geo import coastline
        name = coastline.reduced_cache_path(self.BBOX, self.cache).name
        self.assertNotIn("51.8850", name)
        self.assertNotIn("0.2350", name)

    def test_home_is_recorded_inside_the_file(self):
        import json
        from boxradar_site.geo import coastline
        self.call()
        payload = json.loads(
            coastline.reduced_cache_path(self.BBOX, self.cache).read_text())
        self.assertAlmostEqual(payload["home"][0], self.HOME[0])

    def test_no_partial_file_is_left_beside_the_real_one(self):
        from boxradar_site.geo import coastline
        self.call()
        names = sorted(p.name for p in self.cache.iterdir())
        self.assertEqual(
            names, [coastline.reduced_cache_path(self.BBOX, self.cache).name])
