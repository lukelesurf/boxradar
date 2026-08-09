"""The selection store.

The test that matters most here is round-trip fidelity of the point sections.
The airspace picker touches `airspace` only, but it rewrites the whole file, so
a bug that dropped the curated airfields and towns would look like a working
save and would only be noticed when the map came back missing its labels.
"""

import json
import pathlib
import tempfile
import unittest

from boxradar_config import store
from boxradar_site.geo import selection

HOME_LAT, HOME_LON = 51.8850, 0.2350


def curated(groups=()):
    return selection.Selection(
        HOME_LAT, HOME_LON, 65.0, list(groups),
        airfields=[("EGSS", 51.885, 0.235), ("EGGW", 51.87472, -0.36833)],
        runways=[(51.875081, 0.219933, 51.895166, 0.25005)],
        waypoints=[("BKY", 51.9897, 0.06194)],
        towns=[("STVG", 51.90167, -0.20272)])


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = pathlib.Path(self.dir.name) / "selection.json"

    def test_point_sections_survive_a_save(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR",
                                       ["LONDON STANSTED CTA"])])
        store.save(self.path, sel)
        back = store.load(self.path)
        self.assertEqual(back.airfields, sel.airfields)
        self.assertEqual(back.runways, sel.runways)
        self.assertEqual(back.waypoints, sel.waypoints)
        self.assertEqual(back.towns, sel.towns)

    def test_envelope_grouping_survives_a_save(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR",
                                       ["LONDON STANSTED CTA"])])
        store.save(self.path, sel)
        back = store.load(self.path)
        self.assertEqual([g.name for g in back.groups], ["STANSTED"])
        self.assertEqual(back.groups[0].envelope, ["LONDON STANSTED CTA"])

    def test_home_survives_a_save(self):
        store.save(self.path, curated())
        back = store.load(self.path)
        self.assertAlmostEqual(back.home_lat, HOME_LAT)
        self.assertAlmostEqual(back.home_lon, HOME_LON)
        self.assertAlmostEqual(back.reach_nm, 65.0)

    def test_written_file_is_the_documented_shape(self):
        store.save(self.path, curated())
        raw = json.loads(self.path.read_text())
        self.assertEqual(sorted(raw), ["airfields", "airspace", "home_lat",
                                       "home_lon", "reach_nm", "runways",
                                       "towns", "waypoints"])

    def test_load_returns_none_when_there_is_no_file(self):
        self.assertIsNone(store.load(self.path))

    def test_save_replaces_rather_than_appends(self):
        store.save(self.path, curated())
        store.save(self.path, curated())
        json.loads(self.path.read_text())  # would raise on a doubled document

    def test_no_temporary_files_are_left_behind(self):
        store.save(self.path, curated())
        self.assertEqual([p.name for p in self.path.parent.iterdir()],
                         ["selection.json"])


class TestWriteAtomic(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)

    def test_writes_bytes(self):
        path = self.root / "site.bin"
        store.write_atomic(path, b"\x00\x01\x02")
        self.assertEqual(path.read_bytes(), b"\x00\x01\x02")

    def test_creates_missing_parents(self):
        path = self.root / "a" / "b" / "site.bin"
        store.write_atomic(path, b"x")
        self.assertTrue(path.exists())

    def test_an_existing_file_survives_a_failed_write(self):
        path = self.root / "site.bin"
        store.write_atomic(path, b"good")
        with self.assertRaises(TypeError):
            store.write_atomic(path, 12345)  # neither str nor bytes
        self.assertEqual(path.read_bytes(), b"good")
        self.assertEqual([p.name for p in self.root.iterdir()], ["site.bin"])


class TestGroupNames(unittest.TestCase):
    def test_class_suffix_is_stripped(self):
        self.assertEqual(store.group_name_for("LONDON STANSTED CTR"),
                         "LONDON_STANSTED")

    def test_a_bare_class_name_is_not_stripped_to_nothing(self):
        # LONDON CTR is Heathrow's zone — the whole name is meaningful.
        self.assertEqual(store.group_name_for("LONDON CTR"), "LONDON")
        self.assertEqual(store.group_name_for("CTR"), "CTR")

    def test_punctuation_becomes_an_identifier(self):
        name = store.group_name_for("ST. MARY'S ATZ")
        self.assertTrue(name.replace("_", "").isalnum(), name)
        self.assertFalse(name.startswith("_"))

    def test_a_leading_digit_is_prefixed(self):
        self.assertTrue(store.group_name_for("2 SIDED CTA")[0].isalpha())

    def test_collisions_get_a_suffix(self):
        taken = {"LONDON_STANSTED"}
        self.assertEqual(store.group_name_for("LONDON STANSTED CTA", taken),
                         "LONDON_STANSTED_2")


class TestApplyAirspace(unittest.TestCase):
    def test_ticking_a_new_feature_adds_a_group(self):
        out = store.apply_airspace(curated(), ["LONDON STANSTED CTR"])
        self.assertEqual([g.primary for g in out.groups],
                         ["LONDON STANSTED CTR"])

    def test_an_existing_envelope_group_is_preserved(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR",
                                       ["LONDON STANSTED CTA"])])
        out = store.apply_airspace(sel, ["LONDON STANSTED CTR",
                                         "LONDON STANSTED CTA"])
        self.assertEqual(len(out.groups), 1)
        self.assertEqual(out.groups[0].name, "STANSTED")
        self.assertEqual(out.groups[0].envelope, ["LONDON STANSTED CTA"])

    def test_unticking_an_envelope_member_drops_it_from_the_envelope(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR",
                                       ["LONDON STANSTED CTA"])])
        out = store.apply_airspace(sel, ["LONDON STANSTED CTR"])
        self.assertEqual(out.groups[0].envelope, [])

    def test_unticking_a_primary_promotes_its_ticked_envelope(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR",
                                       ["LONDON STANSTED CTA"])])
        out = store.apply_airspace(sel, ["LONDON STANSTED CTA"])
        self.assertEqual([g.primary for g in out.groups],
                         ["LONDON STANSTED CTA"])

    def test_unticking_everything_empties_the_airspace(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR")])
        self.assertEqual(store.apply_airspace(sel, []).groups, [])

    def test_point_sections_are_untouched(self):
        sel = curated([selection.Group("STANSTED", "LONDON STANSTED CTR")])
        out = store.apply_airspace(sel, [])
        self.assertEqual(out.airfields, sel.airfields)
        self.assertEqual(out.towns, sel.towns)

    def test_the_result_is_loadable(self):
        # selection.load() rejects duplicate group names, so this is the test
        # that the auto-derived names cannot collide.
        sel = curated()
        out = store.apply_airspace(sel, ["LONDON STANSTED CTR",
                                         "LONDON STANSTED CTA",
                                         "LONDON STANSTED TMZ"])
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "s.json"
            store.save(path, out)
            back = store.load(path)
        self.assertEqual(len(back.groups), 3)

    def test_duplicate_ticks_do_not_produce_duplicate_groups(self):
        out = store.apply_airspace(curated(), ["LONDON STANSTED CTR"] * 2)
        self.assertEqual(len(out.groups), 1)


if __name__ == "__main__":
    unittest.main()
