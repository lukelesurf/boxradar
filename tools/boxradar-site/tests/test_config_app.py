"""The configuration UI, through Flask's test client.

These are route-level tests: the geography behind them is already covered in
test_catalog, test_rules and test_generate, so what is worth checking here is
the wiring nobody else can — that a save preserves the curated points, that a
build with a problem publishes nothing at all, and that a first run leads
somewhere useful rather than to a stack trace.
"""

import json
import pathlib
import tempfile
import unittest

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

HOME_LAT, HOME_LON = 51.8850, 0.2350

FEATURES = [
    {"name": "LONDON STANSTED CTR", "type": "CTR",
     "geometry": [{"boundary": [{"circle": {"centre": "515200N 0000900E",
                                            "radius": "5 nm"}}]}]},
    {"name": "LONDON STANSTED CTA", "type": "CTA",
     "geometry": [{"boundary": [{"circle": {"centre": "515200N 0000900E",
                                            "radius": "9 nm"}}]}]},
]


@unittest.skipUnless(HAVE_FLASK, "needs flask (it is in the devShell)")
class AppCase(unittest.TestCase):
    def setUp(self):
        from boxradar_config.app import create_app
        from boxradar_config.settings import Settings

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = pathlib.Path(self.dir.name)
        self.selection_path = root / "selection.json"
        self.blob_path = root / "www" / "site.bin"
        self.cache = root / "cache"
        self.settings = Settings(self.selection_path, self.cache,
                                 self.blob_path, 8082)
        app = create_app(self.settings)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def write_source(self, features=FEATURES):
        import yaml
        path = self.cache / "airspace" / "airspace.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"airspace": features}))

    def write_selection(self, groups=(), **points):
        from boxradar_config import store
        from boxradar_site.geo import selection
        sel = selection.Selection(HOME_LAT, HOME_LON, 65.0, list(groups),
                                  **points)
        store.save(self.selection_path, sel)
        return sel


class TestFirstRun(AppCase):
    def test_index_names_the_next_action_rather_than_redirecting(self):
        # It used to redirect to /site, which redirected to /airspace, which
        # might then render source.html telling you to fetch the source —
        # three hops before anything said what to do. The order was known all
        # along and is now shown.
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Site", r.data)
        self.assertIn(b"Next", r.data)

    def test_the_progress_strip_is_on_every_page(self):
        for path in ("/", "/site", "/data"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(b"Setup steps", r.data, path)

    def test_publish_is_reachable_from_every_page(self):
        # The complaint that started this: every save flashed "Publish to
        # rebuild the map" from a page with no publish button on it.
        # follow_redirects because a first run with no selection still bounces
        # the pickers to /site — the point is that wherever you land, the
        # commit bar is there.
        for path in ("/site", "/data", "/points/airfields", "/airspace"):
            r = self.client.get(path, follow_redirects=True)
            self.assertIn(b"Publish to board", r.data, path)

    def test_airspace_leads_to_the_site_page(self):
        r = self.client.get("/airspace")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/site", r.headers["Location"])

    def test_saving_the_site_creates_the_selection(self):
        r = self.client.post("/site", data={"home_lat": "51.8850",
                                            "home_lon": "0.2350",
                                            "reach_nm": "65"})
        self.assertEqual(r.status_code, 302)
        raw = json.loads(self.selection_path.read_text())
        self.assertAlmostEqual(raw["home_lat"], 51.8850)
        self.assertEqual(raw["airspace"], [])

    def test_a_non_numeric_home_is_rejected(self):
        r = self.client.post("/site", data={"home_lat": "north a bit",
                                            "home_lon": "0.2350"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.selection_path.exists())

    def test_an_out_of_range_home_is_rejected(self):
        r = self.client.post("/site", data={"home_lat": "951.9",
                                            "home_lon": "0.03"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.selection_path.exists())

    def test_missing_source_offers_to_fetch_it(self):
        self.write_selection()
        r = self.client.get("/airspace")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"No airspace source yet", r.data)


class TestPicker(AppCase):
    def setUp(self):
        super().setUp()
        self.write_source()

    def test_candidates_are_listed(self):
        self.write_selection()
        r = self.client.get("/airspace")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"LONDON STANSTED CTR", r.data)

    def test_suggest_does_not_save(self):
        self.write_selection()
        self.client.get("/airspace?suggest=1")
        self.assertEqual(json.loads(self.selection_path.read_text())
                         ["airspace"], [])

    def test_ticking_saves_a_group(self):
        self.write_selection()
        r = self.client.post("/airspace",
                             data={"feature": "LONDON STANSTED CTR"})
        self.assertEqual(r.status_code, 302)
        raw = json.loads(self.selection_path.read_text())
        self.assertEqual([g["primary"] for g in raw["airspace"]],
                         ["LONDON STANSTED CTR"])

    def test_saving_preserves_the_curated_points(self):
        # The picker edits airspace and rewrites the whole file. Losing the
        # hand-curated airfields and towns here would look like a good save.
        self.write_selection(airfields=[("EGSS", 51.885, 0.235)],
                             towns=[("STVG", 51.90167, -0.20272)])
        self.client.post("/airspace", data={"feature": "LONDON STANSTED CTR"})
        raw = json.loads(self.selection_path.read_text())
        self.assertEqual(raw["airfields"], [["EGSS", 51.885, 0.235]])
        self.assertEqual(raw["towns"], [["STVG", 51.90167, -0.20272]])

    def test_unticking_everything_is_honoured(self):
        from boxradar_site.geo import selection
        self.write_selection([selection.Group("STANSTED",
                                              "LONDON STANSTED CTR")])
        self.client.post("/airspace", data={})
        self.assertEqual(json.loads(self.selection_path.read_text())
                         ["airspace"], [])

    def test_a_renamed_feature_is_reported(self):
        from boxradar_site.geo import selection
        self.write_selection([selection.Group("GONE", "MOVED CTR")])
        r = self.client.get("/airspace")
        self.assertIn(b"no longer in the dataset", r.data)


class TestPublish(AppCase):
    def setUp(self):
        super().setUp()
        self.write_source()

    def test_publishing_writes_the_blob(self):
        from boxradar_site.geo import blob, selection
        self.write_selection([selection.Group("STANSTED",
                                              "LONDON STANSTED CTR")])
        r = self.client.post("/publish", data={})
        self.assertEqual(r.status_code, 302)
        got = blob.read(self.blob_path.read_bytes())
        self.assertAlmostEqual(got["home"][0], HOME_LAT, places=4)
        self.assertEqual(len(got["sections"][blob.KIND_AIRSPACE]), 1)

    def test_a_broken_selection_publishes_nothing(self):
        from boxradar_site.geo import selection
        self.write_selection([selection.Group("GONE", "MOVED CTR")])
        self.client.post("/publish", data={})
        self.assertFalse(self.blob_path.exists())

    def test_a_broken_selection_leaves_the_previous_blob_alone(self):
        # The failure mode this guards is the worst one available: replacing a
        # working published map with a truncated or partial one.
        from boxradar_site.geo import selection
        self.blob_path.parent.mkdir(parents=True, exist_ok=True)
        self.blob_path.write_bytes(b"previous blob")
        self.write_selection([selection.Group("GONE", "MOVED CTR")])
        self.client.post("/publish", data={})
        self.assertEqual(self.blob_path.read_bytes(), b"previous blob")

    def test_publishing_without_a_selection_goes_to_the_site_page(self):
        r = self.client.post("/publish", data={})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/site", r.headers["Location"])


class TestHealth(AppCase):
    def test_reports_what_is_present(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["has_selection"])
        self.assertFalse(body["has_source"])

    def test_reflects_a_written_selection(self):
        self.write_selection()
        self.write_source()
        body = self.client.get("/healthz").get_json()
        self.assertTrue(body["has_selection"])
        self.assertTrue(body["has_source"])


if __name__ == "__main__":
    unittest.main()
