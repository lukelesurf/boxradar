import pathlib
import unittest

from boxradar_site.geo import catalog

# The real dataset, cached by the existing generator. Tests that need it skip
# rather than fail when it is absent, so the suite still runs on a machine
# that has never fetched it.
YAML_PATH = (pathlib.Path.home() / ".cache/boxradar-airspace/airspace"
             / "airspace.yaml")

HOME_LAT, HOME_LON = 51.88501837203816, 0.23502731659204137
REACH_NM = 65.0


def load_features():
    import yaml
    with YAML_PATH.open() as f:
        return yaml.safe_load(f).get("airspace", [])


class TestBboxFor(unittest.TestCase):
    def test_latitude_span_is_reach_in_both_directions(self):
        s, n, w, e = catalog.bbox_for(51.9, 0.0, 60.0)
        self.assertAlmostEqual(n - 51.9, 1.0, places=6)
        self.assertAlmostEqual(51.9 - s, 1.0, places=6)

    def test_longitude_span_widens_with_latitude(self):
        _, _, w, e = catalog.bbox_for(51.9, 0.0, 60.0)
        # 1 degree of latitude is 60nm; a degree of longitude at 51.9N is
        # only ~37nm, so the box must be wider in degrees to reach as far.
        self.assertGreater(e - w, 2.0)
        self.assertLess(e - w, 4.0)


@unittest.skipUnless(YAML_PATH.exists(), f"needs {YAML_PATH}")
class TestCatalogAgainstRealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = load_features()
        cls.cands = catalog.catalog(cls.features, HOME_LAT, HOME_LON, REACH_NM)
        cls.by_name = {c.name: c for c in cls.cands}

    def test_finds_the_measured_number_of_features(self):
        # Measured 2026-08-08: 250 of 703 UK features intersect this box.
        # A wide assertion, because the upstream dataset is updated.
        self.assertGreater(len(self.cands), 200)
        self.assertLess(len(self.cands), 320)

    def test_includes_the_local_ctrs(self):
        for name in ["LONDON STANSTED CTR", "LONDON LUTON CTR",
                     "LONDON CITY CTR", "SOUTHEND CTR", "LONDON CTR"]:
            self.assertIn(name, self.by_name)

    def test_excludes_far_away_airspace(self):
        self.assertNotIn("SCOTTISH TMA", self.by_name)

    def test_sorted_by_distance_from_home(self):
        distances = [c.distance_nm for c in self.cands]
        self.assertEqual(distances, sorted(distances))

    def test_kind_distinguishes_tmz_from_other(self):
        tmz = self.by_name["LONDON STANSTED TMZ"]
        self.assertEqual(tmz.kind, "OTHER/TMZ")

    def test_on_screen_size_identifies_the_oversize_ctas(self):
        # The London TMA is not even the worst: DAVENTRY CTA is larger.
        daventry = self.by_name["DAVENTRY CTA"].diag_px(2.2)
        tma = self.by_name["LONDON TMA"].diag_px(2.2)
        stansted_cta = self.by_name["LONDON STANSTED CTA"].diag_px(2.2)
        self.assertGreater(daventry, tma)
        self.assertGreater(tma, 250)
        self.assertLess(stansted_cta, 110)

    def test_vertex_counts_are_populated(self):
        self.assertGreater(self.by_name["LONDON STANSTED CTR"].vertices, 10)

    def test_atzs_are_present_but_tiny(self):
        atzs = [c for c in self.cands if c.kind == "ATZ"]
        self.assertGreater(len(atzs), 20)
        self.assertTrue(all(c.diag_px(2.2) < 30 for c in atzs))


if __name__ == "__main__":
    unittest.main()
