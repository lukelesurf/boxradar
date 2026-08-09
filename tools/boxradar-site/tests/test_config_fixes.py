"""Enroute fixes: the curated table and the eAIP importer.

The importer is the interesting half. It reads a table pasted out of a browser,
so it cannot assume a layout — and a forgiving parser that quietly skipped the
rows it did not understand would be worse than a strict one, because forty
pasted rows yielding three fixes looks exactly like success.
"""

import pathlib
import tempfile
import unittest

from boxradar_config import fixes

# ABBOT, as location.h has it: 52.01611N 0.59958E.
#   52.01611 deg -> 52 00' 58.0"      -> 520058.00N
#   0.59958 deg  ->  0 35' 58.488"    -> 0003558.49E
ABBOT_ROW = "ABBOT\t520058.00N\t0003558.49E"


class TestShippedTable(unittest.TestCase):
    def test_the_shipped_file_is_readable(self):
        loaded = fixes.load()
        self.assertTrue(loaded)

    def test_the_whole_published_table_is_shipped(self):
        # ENR 4.4 carries a bit over a thousand UK significant points. A
        # sharply smaller number means the extraction silently half-worked,
        # which is the failure mode tools_import_eaip_fixes.py guards against
        # at write time and this guards against after the fact.
        self.assertGreater(len(fixes.load()), 900)

    def test_every_ident_fits_the_blob(self):
        # A label longer than the fixed-width name field cannot be stored, and
        # discovering that at publish time would abort a build already
        # committed to.
        for fix in fixes.load():
            self.assertLessEqual(len(fix.ident), fixes.MAX_IDENT, fix.ident)

    def test_every_row_has_plausible_coordinates(self):
        """Bounds the published table, not "the UK".

        The extremes are 45.0N, 61.0N and 15.0W exactly, which look like bad
        data until you notice they are round numbers: they are the Shanwick
        oceanic boundary, and the points sitting on it are real. A tighter
        rectangle drawn around the British Isles rejects legitimate rows.
        """
        for fix in fixes.load():
            self.assertTrue(44.0 <= fix.lat <= 62.0,
                            f"{fix.ident} lat {fix.lat}")
            self.assertTrue(-16.0 <= fix.lon <= 6.0,
                            f"{fix.ident} lon {fix.lon}")

    def test_notes_survive_the_annotation_column(self):
        by_ident = {f.ident: f for f in fixes.load()}
        self.assertIn("STAR", by_ident["ABBOT"].note.upper())

    def test_a_note_containing_a_comma_is_not_split(self):
        # csv quoting, not naive splitting: "FRA (A): EGJJ, EGJB" is one field.
        commas = [f for f in fixes.load() if "," in f.note]
        self.assertTrue(commas, "expected at least one note with a comma")
        for fix in commas:
            self.assertTrue(-35 < fix.lon < 15, f"{fix.ident} lon drifted")

    def test_it_carries_the_two_curated_holds(self):
        by_ident = {f.ident: f for f in fixes.load()}
        self.assertIn("LOREL", by_ident)
        self.assertIn("ABBOT", by_ident)

    def test_the_seeded_values_match_location_h(self):
        by_ident = {f.ident: f for f in fixes.load()}
        self.assertAlmostEqual(by_ident["LOREL"].lat, 52.01394, places=5)
        self.assertAlmostEqual(by_ident["LOREL"].lon, -0.05264, places=5)
        self.assertAlmostEqual(by_ident["ABBOT"].lat, 52.01611, places=5)
        self.assertAlmostEqual(by_ident["ABBOT"].lon, 0.59958, places=5)

    def test_comments_are_not_read_as_fixes(self):
        self.assertTrue(all(not f.ident.startswith("#")
                            for f in fixes.load()))


class TestUserOverlay(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = pathlib.Path(self.dir.name) / "fixes.csv"

    def test_an_imported_fix_is_merged_in(self):
        fixes.save(self.path, [fixes.Fix("TABOR", 51.5, 0.2, "", "imported")])
        by_ident = {f.ident: f for f in fixes.load(self.path)}
        self.assertIn("TABOR", by_ident)
        self.assertIn("LOREL", by_ident)  # shipped survives

    def test_a_user_row_wins_over_the_shipped_one(self):
        # So a stale shipped value can be corrected without editing the
        # installed tree.
        fixes.save(self.path, [fixes.Fix("LOREL", 1.0, 2.0, "", "imported")])
        by_ident = {f.ident: f for f in fixes.load(self.path)}
        self.assertAlmostEqual(by_ident["LOREL"].lat, 1.0)
        self.assertEqual(by_ident["LOREL"].source, "imported")

    def test_a_missing_user_file_is_not_an_error(self):
        self.assertTrue(fixes.load(self.path))

    def test_save_round_trips(self):
        original = [fixes.Fix("TABOR", 51.5, 0.2, "note", "imported")]
        fixes.save(self.path, original)
        back = {f.ident: f for f in fixes.load(self.path)}["TABOR"]
        self.assertAlmostEqual(back.lat, 51.5, places=5)
        self.assertEqual(back.note, "note")


class TestEaipImport(unittest.TestCase):
    def test_a_published_row_round_trips_to_the_curated_value(self):
        parsed, problems = fixes.parse_eaip(ABBOT_ROW)
        self.assertEqual(problems, [])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].ident, "ABBOT")
        self.assertAlmostEqual(parsed[0].lat, 52.01611, places=4)
        self.assertAlmostEqual(parsed[0].lon, 0.59958, places=4)

    def test_several_rows(self):
        parsed, problems = fixes.parse_eaip(
            "ABBOT\t520058.00N\t0003558.49E\n"
            "LOREL\t520050.18N\t0000309.50W\n")
        self.assertEqual(problems, [])
        self.assertEqual([f.ident for f in parsed], ["ABBOT", "LOREL"])

    def test_a_western_longitude_is_negative(self):
        parsed, _ = fixes.parse_eaip("LOREL\t520050.18N\t0000309.50W")
        self.assertLess(parsed[0].lon, 0)
        self.assertAlmostEqual(parsed[0].lat, 52.01394, places=4)

    def test_multiple_spaces_and_commas_are_tolerated(self):
        parsed, problems = fixes.parse_eaip("ABBOT   520058.00N, 0003558.49E")
        self.assertEqual(problems, [])
        self.assertEqual(parsed[0].ident, "ABBOT")

    def test_a_hemisphere_letter_is_not_taken_as_the_identifier(self):
        # The identifier is searched for before the coordinates precisely so
        # that the trailing N/S/E/W cannot win.
        parsed, _ = fixes.parse_eaip("ABBOT\t520058.00N\t0003558.49E")
        self.assertEqual(parsed[0].ident, "ABBOT")

    def test_a_row_with_no_coordinates_is_reported_not_dropped(self):
        parsed, problems = fixes.parse_eaip("ABBOT is a hold near Stansted")
        self.assertEqual(parsed, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("no coordinate pair", problems[0])

    def test_a_row_with_no_identifier_is_reported(self):
        parsed, problems = fixes.parse_eaip("520058.00N 0003558.49E")
        self.assertEqual(parsed, [])
        self.assertIn("no identifier", problems[0])

    def test_an_over_long_identifier_is_rejected(self):
        parsed, problems = fixes.parse_eaip(
            "TOOLONGIDENT 520058.00N 0003558.49E")
        self.assertEqual(parsed, [])
        self.assertTrue(problems)

    def test_blank_lines_and_comments_are_ignored_silently(self):
        parsed, problems = fixes.parse_eaip(
            "\n# a heading\n" + ABBOT_ROW + "\n\n")
        self.assertEqual(problems, [])
        self.assertEqual(len(parsed), 1)

    def test_a_good_paste_with_one_bad_row_keeps_the_good_ones(self):
        parsed, problems = fixes.parse_eaip(ABBOT_ROW + "\nnonsense row\n")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(len(problems), 1)


if __name__ == "__main__":
    unittest.main()
