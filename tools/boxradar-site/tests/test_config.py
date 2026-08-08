import json
import os
import tempfile
import unittest

from boxradar_site import config


class ConfigTest(unittest.TestCase):
    def write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        self.addCleanup(os.unlink, path)
        return path


class TestLoad(ConfigTest):
    def test_missing_file_is_not_an_error(self):
        # The proxy must serve wind and cloud for any station even with no
        # config at all; only the runway recommendation needs one.
        cfg = config.load("/nonexistent/boxradar/config.json")
        self.assertEqual(cfg.runways, {})
        self.assertEqual(cfg.calm_kt, 7)

    def test_malformed_json_is_not_an_error(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{not json")
        self.addCleanup(os.unlink, path)
        cfg = config.load(path)
        self.assertEqual(cfg.runways, {})

    def test_reads_runways_and_calm_kt(self):
        path = self.write({"runways": {"EGSS": [["04", 43], ["22", 223]]},
                           "calm_kt": 9})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("EGSS"), [("04", 43), ("22", 223)])
        self.assertEqual(cfg.calm_kt, 9)

    def test_icao_lookup_is_case_insensitive(self):
        path = self.write({"runways": {"EGSS": [["04", 43]]}})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("egss"), [("04", 43)])

    def test_unknown_station_has_no_runways(self):
        path = self.write({"runways": {"EGSS": [["04", 43]]}})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("EGLL"), [])

    def test_malformed_runway_entries_are_dropped_not_fatal(self):
        path = self.write({"runways": {
            "EGSS": [["04", 43], ["22"], "nonsense", ["23", "not a number"]],
        }})
        cfg = config.load(path)
        self.assertEqual(cfg.runways_for("EGSS"), [("04", 43)])

    def test_non_integer_calm_kt_falls_back_to_default(self):
        path = self.write({"calm_kt": "seven"})
        self.assertEqual(config.load(path).calm_kt, 7)


if __name__ == "__main__":
    unittest.main()
