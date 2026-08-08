import unittest

from boxradar_site.geo import yaixm


class TestParseLatLon(unittest.TestCase):
    def test_north_east(self):
        lat, lon = yaixm.parse_latlon("515152N 0000345E")
        self.assertAlmostEqual(lat, 51.86444, places=4)
        self.assertAlmostEqual(lon, 0.06250, places=4)

    def test_south_west_are_negative(self):
        lat, lon = yaixm.parse_latlon("515152S 0000345W")
        self.assertAlmostEqual(lat, -51.86444, places=4)
        self.assertAlmostEqual(lon, -0.06250, places=4)

    def test_three_digit_longitude_degrees(self):
        lat, lon = yaixm.parse_latlon("515152N 1000345W")
        self.assertAlmostEqual(lon, -100.06250, places=4)

    def test_fractional_seconds(self):
        lat, _ = yaixm.parse_latlon("515152.50N 0000345E")
        self.assertAlmostEqual(lat, 51.864583, places=5)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            yaixm.parse_latlon("not a coordinate")


class TestFeatureKind(unittest.TestCase):
    def test_plain_type(self):
        self.assertEqual(yaixm.feature_kind({"type": "CTR"}), "CTR")

    def test_localtype_qualifies_other(self):
        # The reason type alone is not enough: OTHER holds both the Stansted
        # TMZ we draw and a dozen MATZs we do not.
        self.assertEqual(
            yaixm.feature_kind({"type": "OTHER", "localtype": "TMZ"}),
            "OTHER/TMZ")
        self.assertEqual(
            yaixm.feature_kind({"type": "OTHER", "localtype": "MATZ"}),
            "OTHER/MATZ")

    def test_tmz_rule_without_localtype_still_shows_as_tmz(self):
        self.assertEqual(
            yaixm.feature_kind({"type": "OTHER", "rules": ["TMZ"]}),
            "OTHER/TMZ")

    def test_missing_type(self):
        self.assertEqual(yaixm.feature_kind({}), "?")


class TestBoundaryToRing(unittest.TestCase):
    def test_simple_polygon_closes_itself(self):
        ring = yaixm.boundary_to_ring([
            {"line": ["515152N 0000345E", "520000N 0001500E",
                      "515000N 0001500E"]}])
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 4)

    def test_circle_is_interpolated(self):
        ring = yaixm.boundary_to_ring([
            {"circle": {"centre": "515152N 0000345E", "radius": "2 nm"}}])
        self.assertEqual(len(ring), yaixm.ARC_RESOLUTION + 1)
        self.assertEqual(ring[0], ring[-1])

    def test_unparseable_returns_none(self):
        self.assertIsNone(yaixm.boundary_to_ring([{"nonsense": 1}]))

    def test_empty_returns_none(self):
        self.assertIsNone(yaixm.boundary_to_ring([]))

    def test_bad_coordinate_returns_none_rather_than_raising(self):
        # The catalog walks 703 features; one bad boundary must not stop it.
        self.assertIsNone(yaixm.boundary_to_ring([{"line": ["nope", "also no"]}]))

    def test_arc_without_a_preceding_line_is_skipped(self):
        self.assertIsNone(yaixm.boundary_to_ring([
            {"arc": {"centre": "515152N 0000345E", "to": "520000N 0001500E"}}]))


class TestFeatureRings(unittest.TestCase):
    def test_one_ring_per_volume(self):
        feature = {"geometry": [
            {"boundary": [{"circle": {"centre": "515152N 0000345E",
                                      "radius": "2 nm"}}]},
            {"boundary": [{"circle": {"centre": "520000N 0001500E",
                                      "radius": "3 nm"}}]},
        ]}
        self.assertEqual(len(yaixm.feature_rings(feature)), 2)

    def test_no_geometry_is_empty_not_an_error(self):
        self.assertEqual(yaixm.feature_rings({}), [])

    def test_unparseable_volume_is_skipped_not_fatal(self):
        feature = {"geometry": [
            {"boundary": [{"nonsense": 1}]},
            {"boundary": [{"circle": {"centre": "515152N 0000345E",
                                      "radius": "2 nm"}}]},
        ]}
        self.assertEqual(len(yaixm.feature_rings(feature)), 1)


if __name__ == "__main__":
    unittest.main()
