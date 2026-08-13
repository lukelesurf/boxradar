"""The airfield, fix and town pickers, through Flask's test client.

The tests that earn their place here are the round-trips. The selection stores
only what the blob needs — a runway is four bare floats, a town is a label and
a position — so re-ticking the right boxes on the next page load means matching
coordinates back to dataset rows. That is the part of the design that can
quietly stop working, and nothing else would notice: the map would still build,
it would just come back with the boxes cleared.
"""

import json
import pathlib
import re
import tempfile
import unittest

from tests.test_config_datasets import AIRPORTS, NAVAIDS, RUNWAYS, TOWNS

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

HOME_LAT, HOME_LON = 51.8850, 0.2350


def ticked(response, value):
    """Is the checkbox carrying this value rendered checked?

    A regex rather than a literal slice of markup, so that reindenting a
    template does not fail a test about selection state.
    """
    pattern = re.compile(r'value="' + re.escape(value) + r'"\s*checked')
    return bool(pattern.search(response.data.decode()))


@unittest.skipUnless(HAVE_FLASK, "needs flask (it is in the devShell)")
class PickerCase(unittest.TestCase):
    def setUp(self):
        from boxradar_config import datasets, store
        from boxradar_config.app import create_app
        from boxradar_config.settings import Settings
        from boxradar_site.geo import selection

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = pathlib.Path(self.dir.name)
        self.selection_path = root / "selection.json"
        self.cache = root / "cache"
        self.settings = Settings(self.selection_path, self.cache,
                                 root / "www" / "site.bin", 8082)

        store.save(self.selection_path,
                   selection.Selection(HOME_LAT, HOME_LON, 65.0, []))

        self.data_dir = datasets.dataset_dir(self.cache)
        self.data_dir.mkdir(parents=True)
        app = create_app(self.settings)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def install(self, **files):
        for name, body in files.items():
            filename = {"airports": "airports.csv", "runways": "runways.csv",
                        "navaids": "navaids.csv", "towns": "GB.txt"}[name]
            (self.data_dir / filename).write_text(body)

    def stored(self):
        return json.loads(self.selection_path.read_text())


class TestAirfields(PickerCase):
    def setUp(self):
        super().setUp()
        self.install(airports=AIRPORTS, runways=RUNWAYS)

    def test_a_missing_dataset_offers_the_download(self):
        (self.data_dir / "airports.csv").unlink()
        r = self.client.get("/points/airfields")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"not been downloaded yet", r.data)

    def test_fields_in_reach_are_listed(self):
        r = self.client.get("/points/airfields")
        self.assertIn(b"EGSS", r.data)
        self.assertIn(b"EGSC", r.data)

    def test_small_fields_are_hidden_by_default(self):
        self.assertNotIn(b"EGTR", self.client.get("/points/airfields").data)
        self.assertIn(b"EGTR", self.client.get("/points/airfields?small=1").data)

    def test_searching_is_no_longer_a_round_trip(self):
        # ?q= used to filter server-side. It now renders everything and the
        # browser hides rows, which is what stops a save under a search
        # dropping what was not visible.
        r = self.client.get("/points/airfields?q=cambridge")
        self.assertIn(b"EGSC", r.data)
        self.assertIn(b"EGSS", r.data)

    def test_saving_writes_the_markers(self):
        self.client.post("/points/airfields", data={"airfield": ["EGSS", "EGGW"]})
        self.assertEqual([row[0] for row in self.stored()["airfields"]],
                         ["EGSS", "EGGW"])

    def test_the_saved_position_is_the_dataset_one(self):
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        _, lat, lon = self.stored()["airfields"][0]
        self.assertAlmostEqual(lat, 51.884998, places=5)
        self.assertAlmostEqual(lon, 0.235, places=5)

    def test_saved_fields_come_back_ticked(self):
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        self.assertTrue(ticked(self.client.get("/points/airfields"), "EGSS"))

    def test_runways_are_only_offered_for_saved_fields(self):
        self.assertIn(b"Mark an airfield and save",
                      self.client.get("/points/airfields").data)
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        self.assertIn(b"04/22", self.client.get("/points/airfields").data)

    def test_a_centreline_is_saved_as_an_axis(self):
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        self.client.post("/points/airfields", data={"airfield": "EGSS",
                                             "runway": "EGSS 04/22"})
        rows = self.stored()["runways"]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][0], 51.875081, places=5)
        self.assertAlmostEqual(rows[0][3], 0.250050, places=5)

    def test_a_saved_centreline_comes_back_ticked(self):
        # The round-trip that matters: the stored row is four bare floats with
        # no link to the runway it came from.
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        self.client.post("/points/airfields", data={"airfield": "EGSS",
                                             "runway": "EGSS 04/22"})
        self.assertTrue(ticked(self.client.get("/points/airfields"),
                               "EGSS 04/22"))

    def test_unticking_a_field_drops_its_centrelines(self):
        # Otherwise the axis stays in the file with no marker above it, and
        # nothing on the page would ever show it again.
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        self.client.post("/points/airfields", data={"airfield": "EGSS",
                                             "runway": "EGSS 04/22"})
        self.client.post("/points/airfields", data={})
        self.assertEqual(self.stored()["runways"], [])

    def test_saving_leaves_the_other_sections_alone(self):
        from boxradar_config import store
        from boxradar_site.geo import selection
        store.save(self.selection_path, selection.Selection(
            HOME_LAT, HOME_LON, 65.0,
            [selection.Group("STANSTED", "LONDON STANSTED CTR")],
            towns=[("STVG", 51.90167, -0.20272)]))
        self.client.post("/points/airfields", data={"airfield": "EGSS"})
        raw = self.stored()
        self.assertEqual(len(raw["airspace"]), 1)
        self.assertEqual(raw["towns"], [["STVG", 51.90167, -0.20272]])


class TestFixes(PickerCase):
    def setUp(self):
        super().setUp()
        self.install(navaids=NAVAIDS)

    def test_navaids_and_curated_fixes_share_one_list(self):
        r = self.client.get("/points/fixes")
        self.assertIn(b"BKY", r.data)     # downloaded navaid
        self.assertIn(b"LOREL", r.data)   # shipped enroute fix

    def test_the_box_disambiguates_a_reused_ident(self):
        r = self.client.get("/points/fixes")
        self.assertIn(b"Barkway", r.data)
        self.assertNotIn(b"Bouake", r.data)

    def test_saving_writes_waypoints(self):
        self.client.post("/points/fixes", data={"fix": ["BKY", "LOREL"]})
        self.assertEqual(sorted(row[0] for row in self.stored()["waypoints"]),
                         ["BKY", "LOREL"])

    def test_the_saved_navaid_position_matches_location_h(self):
        self.client.post("/points/fixes", data={"fix": "BKY"})
        _, lat, lon = self.stored()["waypoints"][0]
        self.assertAlmostEqual(lat, 51.98970, places=4)
        self.assertAlmostEqual(lon, 0.061944, places=5)

    def test_saved_fixes_come_back_ticked(self):
        self.client.post("/points/fixes", data={"fix": "BKY"})
        self.assertTrue(ticked(self.client.get("/points/fixes"), "BKY"))

    def test_working_without_navaids_downloaded(self):
        (self.data_dir / "navaids.csv").unlink()
        r = self.client.get("/points/fixes")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"LOREL", r.data)
        self.assertIn(b"Navaids are not downloaded", r.data)

    def test_importing_from_the_eaip_adds_a_fix(self):
        self.client.post("/points/fixes/import",
                         data={"eaip": "TABOR\t515800.00N\t0001200.00E"})
        self.assertIn(b"TABOR", self.client.get("/points/fixes").data)

    def test_an_imported_fix_can_then_be_selected(self):
        self.client.post("/points/fixes/import",
                         data={"eaip": "TABOR\t515800.00N\t0001200.00E"})
        self.client.post("/points/fixes", data={"fix": "TABOR"})
        _, lat, lon = self.stored()["waypoints"][0]
        self.assertAlmostEqual(lat, 51.96667, places=4)
        self.assertAlmostEqual(lon, 0.2, places=4)

    def test_an_unreadable_paste_is_reported(self):
        r = self.client.post("/points/fixes/import", data={"eaip": "nonsense"},
                             follow_redirects=True)
        self.assertIn(b"no coordinate pair", r.data)

    def test_an_import_survives_a_restart(self):
        self.client.post("/points/fixes/import",
                         data={"eaip": "TABOR\t515800.00N\t0001200.00E"})
        self.assertTrue(self.settings.fixes_path.exists())


class TestTowns(PickerCase):
    def setUp(self):
        super().setUp()
        self.install(towns=TOWNS)

    def test_towns_in_reach_are_listed(self):
        r = self.client.get("/points/towns?min_population=0")
        self.assertIn(b"Stevenage", r.data)
        self.assertNotIn(b"Glasgow", r.data)

    def test_there_is_no_map(self):
        # 293KB of a 788KB page, and a dot cloud at 640px told you less than
        # a distance column does.
        r = self.client.get("/points/towns?min_population=0")
        self.assertNotIn(b'<svg class="map"', r.data)

    def test_population_ranks_but_does_not_gate(self):
        r = self.client.get("/points/towns?min_population=0")
        self.assertIn(b"Tiny Hamlet", r.data)

    def test_a_floor_shortens_the_list(self):
        r = self.client.get("/points/towns?min_population=1000")
        self.assertNotIn(b"Tiny Hamlet", r.data)

    def test_saving_uses_the_given_label(self):
        self.client.post("/points/towns", data={"town": "2636940",
                                         "label_2636940": "STVG"})
        self.assertEqual(self.stored()["towns"][0][0], "STVG")

    def test_a_label_is_uppercased(self):
        self.client.post("/points/towns", data={"town": "2636940",
                                         "label_2636940": "stvg"})
        self.assertEqual(self.stored()["towns"][0][0], "STVG")

    def test_a_saved_town_comes_back_ticked_with_its_label(self):
        # Matched on position, not name — the label is a hand-chosen
        # abbreviation that deliberately does not match the dataset.
        self.client.post("/points/towns", data={"town": "2636940",
                                         "label_2636940": "STVG"})
        r = self.client.get("/points/towns?min_population=0")
        self.assertIn(b'value="STVG"', r.data)
        self.assertTrue(ticked(r, "2636940"))

    def test_an_over_long_label_refuses_the_whole_save(self):
        # Not a partial save: dropping the one bad town and flashing about it
        # reads as success, and the map comes back short.
        self.client.post("/points/towns", data={"town": "2636940",
                                         "label_2636940": "STVG"})
        r = self.client.post("/points/towns",
                             data={"town": ["2636940", "2647044"],
                                   "label_2636940": "STVG",
                                   "label_2647044": "HERTFORDSHIRE"},
                             follow_redirects=True)
        self.assertIn(b"limit is 7", r.data)
        self.assertIn(b"Nothing was saved", r.data)
        self.assertEqual(len(self.stored()["towns"]), 1)

    def test_a_default_label_is_offered(self):
        r = self.client.get("/points/towns?min_population=0")
        self.assertIn(b'value="STEV"', r.data)


if __name__ == "__main__":
    unittest.main()


class TestFilteringAndOrder(PickerCase):
    """Client-side filtering across all three panels, and nearest-first order.

    The gate tests here are the important ones. Both were proven against the
    live app before this change: a selected small airfield and a selected
    sub-floor town were each dropped by visiting the page and pressing Save,
    with no search typed and no warning. A save rebuilds the selection from
    exactly what the form contained, so anything the gate hid was simply not
    there.
    """

    def setUp(self):
        super().setUp()
        self.install(airports=AIRPORTS, runways=RUNWAYS, navaids=NAVAIDS,
                     towns=TOWNS)

    def rows(self, body, name):
        """Checkbox values in render order."""
        return [chunk.split('value="')[1].split('"')[0]
                for chunk in body.decode().split("<input ")[1:]
                if f'name="{name}"' in chunk.split(">")[0]]

    def distances(self, body):
        """The dist column, in render order.

        First numeric cell of each row: every one of these tables puts dist
        there. Scraping every class="n" cell would also pick up population.
        """
        import re
        out = []
        for row in body.decode().split("<tr")[1:]:
            found = re.search(r'<td class="n">(\d+)</td>', row)
            if found:
                out.append(int(found.group(1)))
        return out

    # ------------------------------------------------------------- filtering

    def test_every_panel_offers_a_filter_box(self):
        for path in ("/points/airfields", "/points/fixes", "/points/towns"):
            body = self.client.get(path).data
            self.assertIn(b'id="find"', body, path)
            self.assertIn(b'id="counts"', body, path)

    def test_every_panel_marks_its_rows_searchable(self):
        for path in ("/points/airfields", "/points/fixes", "/points/towns"):
            self.assertIn(b"data-search=", self.client.get(path).data, path)

    def test_airfields_are_searchable_by_icao_name_and_town(self):
        body = self.client.get("/points/airfields").data.decode()
        row = [c for c in body.split("<tr") if "EGSC" in c][0]
        search = row.split('data-search="')[1].split('"')[0]
        self.assertIn("EGSC", search)
        self.assertIn("CAMBRIDGE", search)

    # ----------------------------------------------------------------- order

    def test_airfields_are_nearest_first(self):
        d = self.distances(self.client.get("/points/airfields").data)
        self.assertEqual(d, sorted(d), d)

    def test_fixes_are_nearest_first(self):
        d = self.distances(self.client.get("/points/fixes").data)
        self.assertEqual(d, sorted(d), d)

    def test_towns_are_nearest_first(self):
        d = self.distances(
            self.client.get("/points/towns?min_population=0").data)
        self.assertEqual(d, sorted(d), d)

    # ------------------------------------------------- gates cannot hide a pick

    def test_a_selected_small_airfield_survives_the_default_view(self):
        self.client.post("/points/airfields", data={"airfield": "EGTR"})
        body = self.client.get("/points/airfields").data   # small hidden
        self.assertIn(b"EGTR", body,
                      "a selected field the class gate hides must still render")

    def test_saving_the_default_view_keeps_a_selected_small_airfield(self):
        self.client.post("/points/airfields", data={"airfield": "EGTR"})
        body = self.client.get("/points/airfields").data
        self.client.post("/points/airfields",
                         data={"airfield": self.rows(body, "airfield")})
        self.assertIn("EGTR", [r[0] for r in self.stored()["airfields"]])

    def test_a_selected_sub_floor_town_survives_the_default_view(self):
        self.client.post("/points/towns", data={"town": "1000001",
                                                "label_1000001": "TINY"})
        body = self.client.get("/points/towns?min_population=1000").data
        self.assertIn(b"TINY", body,
                      "a selected town under the floor must still render")

    def test_saving_a_floored_view_keeps_a_selected_sub_floor_town(self):
        self.client.post("/points/towns", data={"town": "1000001",
                                                "label_1000001": "TINY"})
        body = self.client.get("/points/towns?min_population=1000").data
        form = {"town": self.rows(body, "town")}
        for uid in form["town"]:
            form[f"label_{uid}"] = "X"
        form["label_1000001"] = "TINY"
        self.client.post("/points/towns", data=form)
        self.assertIn("TINY", [r[0] for r in self.stored()["towns"]])

    def test_an_unselected_hidden_item_stays_hidden(self):
        # The union is only for what is selected. Rendering every small field
        # regardless would defeat the toggle.
        self.assertNotIn(b"EGTR", self.client.get("/points/airfields").data)


class TestPreview(PickerCase):
    """The preview page, which draws whatever would be published."""

    def setUp(self):
        super().setUp()
        import yaml
        from tests.test_config_app import FEATURES
        path = self.cache / "airspace" / "airspace.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"airspace": FEATURES}))

    def test_it_renders_every_range_the_scope_offers(self):
        from boxradar_config import preview
        r = self.client.get("/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data.count(b'<svg class="scope"'),
                         1 + len(preview.DETAIL_RANGES_NM))

    def test_the_panel_geometry_reaches_the_page(self):
        self.assertIn(b'viewBox="0 0 320 240"', self.client.get("/preview").data)

    def test_markers_are_drawn_for_the_selection(self):
        from boxradar_config import store
        from boxradar_site.geo import selection
        store.save(self.selection_path, selection.Selection(
            HOME_LAT, HOME_LON, 65.0, [],
            airfields=[("EGSS", 51.885, 0.235)],
            towns=[("STVG", 51.90167, -0.20272)]))
        data = self.client.get("/preview").data
        self.assertIn(b">EGSS<", data)
        self.assertIn(b">STVG<", data)

    def test_crowding_is_reported(self):
        from boxradar_config import store
        from boxradar_site.geo import selection
        store.save(self.selection_path, selection.Selection(
            HOME_LAT, HOME_LON, 65.0, [],
            towns=[("AAAA", HOME_LAT, HOME_LON),
                   ("BBBB", HOME_LAT + 0.0005, HOME_LON)]))
        data = self.client.get("/preview").data
        self.assertIn(b"overlapping pair", data)
        self.assertIn(b"<code>AAAA/BBBB</code>", data)

    def test_a_clean_selection_says_so(self):
        from boxradar_config import store
        from boxradar_site.geo import selection
        store.save(self.selection_path, selection.Selection(
            HOME_LAT, HOME_LON, 65.0, [],
            towns=[("AAAA", HOME_LAT, HOME_LON)]))
        self.assertIn(b"no overlaps", self.client.get("/preview").data)

    def test_a_broken_selection_does_not_render(self):
        from boxradar_config import store
        from boxradar_site.geo import selection
        store.save(self.selection_path, selection.Selection(
            HOME_LAT, HOME_LON, 65.0,
            [selection.Group("GONE", "MOVED CTR")]))
        r = self.client.get("/preview")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/airspace", r.headers["Location"])

    def test_the_preview_never_touches_the_published_blob(self):
        self.client.get("/preview")
        self.assertFalse(self.settings.blob_path.exists())

    def test_no_selection_goes_to_the_site_page(self):
        self.selection_path.unlink()
        r = self.client.get("/preview")
        self.assertIn("/site", r.headers["Location"])
