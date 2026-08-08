import json
import os
import pathlib
import tempfile
import unittest

from boxradar_site.geo import selection

EXAMPLE = (pathlib.Path(__file__).resolve().parents[1]
           / "boxradar_site" / "geo" / "selection.example.json")


class SelectionTest(unittest.TestCase):
    def write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        self.addCleanup(os.unlink, path)
        return path


class TestLoadExample(unittest.TestCase):
    def test_example_transcribes_curated_airports(self):
        sel = selection.load(EXAMPLE)
        self.assertEqual(len(sel.groups), 7)
        by_name = {g.name: g for g in sel.groups}
        self.assertEqual(by_name["STANSTED"].primary, "LONDON STANSTED CTR")
        self.assertEqual(by_name["STANSTED"].envelope,
                         ["LONDON STANSTED CTA"])
        # Heathrow has no CTA of its own: its zone is LONDON CTR and its CTA
        # is the TMA. An empty envelope is the whole representation.
        self.assertEqual(by_name["HEATHROW"].envelope, [])
        self.assertAlmostEqual(sel.reach_nm, 65.0)


class TestLoadErrors(SelectionTest):
    def test_missing_file(self):
        with self.assertRaises(ValueError) as cm:
            selection.load("/nonexistent/selection.json")
        self.assertIn("nonexistent", str(cm.exception))

    def test_malformed_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{nope")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(ValueError):
            selection.load(path)

    def test_missing_home_is_rejected(self):
        path = self.write({"airspace": []})
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("home_lat", str(cm.exception))

    def test_group_without_primary_is_rejected(self):
        path = self.write({"home_lat": 51.9, "home_lon": 0.0,
                           "airspace": [{"name": "X"}]})
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("primary", str(cm.exception))

    def test_duplicate_group_names_are_rejected(self):
        # Two groups with one name would silently overwrite each other's
        # generated symbols.
        path = self.write({"home_lat": 51.9, "home_lon": 0.0, "airspace": [
            {"name": "X", "primary": "A"}, {"name": "X", "primary": "B"}]})
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_envelope_defaults_to_empty(self):
        path = self.write({"home_lat": 51.9, "home_lon": 0.0,
                           "airspace": [{"name": "X", "primary": "A"}]})
        self.assertEqual(selection.load(path).groups[0].envelope, [])

    def test_reach_defaults(self):
        path = self.write({"home_lat": 51.9, "home_lon": 0.0,
                           "airspace": []})
        self.assertEqual(selection.load(path).reach_nm,
                         selection.DEFAULT_REACH_NM)


class TestMissingFeatures(unittest.TestCase):
    def test_reports_names_absent_from_the_dataset(self):
        sel = selection.Selection(51.9, 0.0, 65.0, [
            selection.Group("X", "GONE CTR", ["STILL HERE CTA"])])
        features = [{"name": "STILL HERE CTA"}]
        self.assertEqual(selection.missing_features(sel, features),
                         ["GONE CTR"])

    def test_nothing_missing_is_empty(self):
        sel = selection.Selection(51.9, 0.0, 65.0, [
            selection.Group("X", "A", [])])
        self.assertEqual(selection.missing_features(sel, [{"name": "A"}]), [])


if __name__ == "__main__":
    unittest.main()
