import pathlib
import unittest

from boxradar_site.geo import blob, points, selection

EXAMPLE = (pathlib.Path(__file__).resolve().parents[1]
           / "boxradar_site" / "geo" / "selection.example.json")
REPO = pathlib.Path(__file__).resolve().parents[3]
LOCATION_H = REPO / "include" / "location.h"


class TestSelectionCarriesPoints(unittest.TestCase):
    def test_example_has_the_current_sites_references(self):
        sel = selection.load(EXAMPLE)
        self.assertEqual(len(sel.airfields), 10)
        self.assertEqual(len(sel.runways), 2)
        self.assertEqual(len(sel.waypoints), 4)
        self.assertEqual(len(sel.towns), 7)

    def test_every_name_fits_the_blob_field(self):
        sel = selection.load(EXAMPLE)
        for group in (sel.airfields, sel.waypoints, sel.towns):
            for name, _, _ in group:
                self.assertLessEqual(len(name), blob.MAX_NAME_CHARS, name)

    def test_points_default_to_empty(self):
        sel = selection.Selection(51.9, 0.0, 65.0, [])
        self.assertEqual(sel.airfields, [])
        self.assertEqual(sel.towns, [])

    def test_wrong_arity_is_rejected_naming_the_row(self):
        import json
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"home_lat": 51.9, "home_lon": 0.0,
                       "airfields": [["EGSS", 51.9]]}, f)
        self.addCleanup(os.unlink, path)
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("airfields[0]", str(cm.exception))


@unittest.skipUnless(LOCATION_H.exists(), "needs include/location.h")
class TestMatchesCommittedHeader(unittest.TestCase):
    def test_same_record_counts_as_the_committed_header(self):
        # The transcription must be faithful, so the first thing verified is
        # "nothing moved" rather than "did I remember everything". Counted off
        # the live arrays only — the file also carries a commented-out
        # alternative profile that must not be counted.
        text = LOCATION_H.read_text()
        sel = selection.load(EXAMPLE)
        for marker, group in (("AirfieldRef AIRFIELDS[] = {", sel.airfields),
                              ("RunwayAxis RUNWAYS[] = {", sel.runways),
                              ("Waypoint WAYPOINTS[] = {", sel.waypoints),
                              ("TownRef TOWNS[] = {", sel.towns)):
            self.assertIn(marker, text)
            block = text.split(marker, 1)[1].split("};", 1)[0]
            live = [ln for ln in block.splitlines()
                    if ln.strip().startswith("{")]
            self.assertEqual(len(live), len(group), marker)

    def test_every_transcribed_coordinate_appears_in_the_header(self):
        # Catches a digit typed wrong, which no count check would find.
        text = LOCATION_H.read_text()
        sel = selection.load(EXAMPLE)
        for name, lat, lon in (sel.airfields + sel.waypoints + sel.towns):
            self.assertIn(f'"{name}"', text, name)
            self.assertIn(f"{lat:.5f}f", text, f"{name} lat {lat}")
            self.assertIn(f"{lon:.5f}f", text, f"{name} lon {lon}")

    def test_generated_header_declares_the_same_arrays(self):
        sel = selection.load(EXAMPLE)
        generated = points.render_header(sel)
        for marker in ("AIRFIELDS[]", "RUNWAYS[]", "WAYPOINTS[]", "TOWNS[]"):
            self.assertIn(marker, generated)

    def test_generated_header_keeps_the_true_not_magnetic_warning(self):
        # The trap the README documents. Losing it to a generator would be a
        # regression in the thing most likely to be got wrong.
        generated = points.render_header(selection.load(EXAMPLE))
        self.assertIn("MAGNETIC", generated)


class TestBlobSections(unittest.TestCase):
    def test_round_trips_through_the_blob(self):
        sel = selection.load(EXAMPLE)
        data = blob.write(sel.home_lat, sel.home_lon, {
            blob.KIND_AIRFIELDS: sel.airfields,
            blob.KIND_RUNWAYS: sel.runways,
            blob.KIND_WAYPOINTS: sel.waypoints,
            blob.KIND_TOWNS: sel.towns,
        })
        got = blob.read(data)["sections"]
        self.assertEqual([n for n, _, _ in got[blob.KIND_AIRFIELDS]],
                         [n for n, _, _ in sel.airfields])
        self.assertEqual(len(got[blob.KIND_TOWNS]), len(sel.towns))
        self.assertEqual(len(got[blob.KIND_RUNWAYS]), len(sel.runways))

    def test_five_character_fix_names_survive_intact(self):
        # LOREL and ABBOT are real 5-letter identifiers and must not be
        # mangled into four — a wrong label costs more than six pixels.
        sel = selection.load(EXAMPLE)
        data = blob.write(sel.home_lat, sel.home_lon,
                          {blob.KIND_WAYPOINTS: sel.waypoints})
        names = [n for n, _, _ in blob.read(data)["sections"][
            blob.KIND_WAYPOINTS]]
        self.assertIn("LOREL", names)
        self.assertIn("ABBOT", names)


if __name__ == "__main__":
    unittest.main()
