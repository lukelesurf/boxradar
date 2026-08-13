"""The wizard's progress rail.

Two things are being checked here, and the second matters more than the first.

The obvious one is that each step reports the right state — that Airspace is
blocked without a source, that Publish notices the selection has moved on since
the blob was written.

The one worth defending is COST. The rail renders on every page, so it is
allowed to stat() files and read the selection that the request already loaded,
and nothing else. If it ever reaches for the catalog or a dataset filter it
would put a second or two onto every page load on a Pi — which is the exact
failure the memoisation in app.py exists to avoid. test_the_rail_is_cheap
enforces that by exploding if the loaders are touched at all.
"""

import pathlib
import tempfile
import unittest

from boxradar_config import datasets, sources, steps
from boxradar_config.settings import Settings

HOME_LAT, HOME_LON = 51.8850, 0.2350


def make_selection(groups=(), **points):
    from boxradar_site.geo import selection
    return selection.Selection(HOME_LAT, HOME_LON, 65.0, list(groups),
                               **points)


class RailCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)
        self.settings = Settings(self.root / "selection.json",
                                 self.root / "cache",
                                 self.root / "www" / "site.bin", 8082)

    def write_dataset(self, name):
        path = datasets.path_for(name, self.settings.cache_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub")

    def write_all_datasets(self):
        for name in datasets.SOURCES:
            self.write_dataset(name)

    def write_source(self):
        from boxradar_site.geo import generate
        path = generate.yaml_path(self.settings.source_cache)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("airspace: []")

    def write_selection_file(self):
        self.settings.selection_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.selection_path.write_text("{}")

    def write_blob(self):
        self.settings.blob_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.blob_path.write_bytes(b"blob")

    def rail(self, sel=None, current="site"):
        return {s.key: s for s in steps.rail(self.settings, sel, current)}


class TestOrderAndShape(RailCase):
    def test_six_steps_in_dependency_order(self):
        order = [s.key for s in steps.rail(self.settings, None, "site")]
        self.assertEqual(order, ["site", "data", "airspace", "points",
                                 "device", "publish"])

    def test_the_current_step_is_marked_active(self):
        rail = self.rail(make_selection(), current="airspace")
        self.assertTrue(rail["airspace"].active)
        self.assertFalse(rail["site"].active)

    def test_every_step_has_a_route(self):
        for step in steps.rail(self.settings, None, "site"):
            self.assertTrue(step.route.startswith("/"), step.key)


class TestSiteStep(RailCase):
    def test_todo_without_a_selection(self):
        self.assertEqual(self.rail(None)["site"].state, steps.TODO)

    def test_done_shows_the_home_position(self):
        step = self.rail(make_selection())["site"]
        self.assertEqual(step.state, steps.DONE)
        self.assertIn("51.885", step.detail)
        self.assertIn("0.235", step.detail)


class TestDataStep(RailCase):
    def test_todo_when_nothing_is_downloaded(self):
        self.assertEqual(self.rail(make_selection())["data"].state, steps.TODO)

    def test_counts_what_is_present(self):
        self.write_dataset(next(iter(datasets.SOURCES)))
        step = self.rail(make_selection())["data"]
        self.assertEqual(step.state, steps.TODO)
        self.assertIn(f"1 of {len(sources.ALL)}", step.detail)

    def test_the_age_is_rounded(self):
        # age_days() returns a float. Unformatted, the live strip read
        # "oldest 4.337401080090139d" — caught on the Pi, not in a test.
        self.write_all_datasets()
        self.write_source()
        detail = self.rail(make_selection())["data"].detail
        self.assertNotIn(".", detail)

    def test_done_needs_the_airspace_source_too(self):
        # The YAIXM source is a prerequisite in exactly the way the four
        # downloads are, and treating it as a separate hidden concept is why
        # the old UI bounced you to source.html from the Airspace tab.
        self.write_all_datasets()
        self.assertEqual(self.rail(make_selection())["data"].state, steps.TODO)
        self.write_source()
        self.assertEqual(self.rail(make_selection())["data"].state, steps.DONE)


class TestAirspaceStep(RailCase):
    def test_blocked_without_a_source(self):
        step = self.rail(make_selection())["airspace"]
        self.assertEqual(step.state, steps.BLOCKED)
        self.assertIn("source", step.detail.lower())

    def test_todo_with_a_source_and_no_groups(self):
        self.write_source()
        self.assertEqual(self.rail(make_selection())["airspace"].state,
                         steps.TODO)

    def test_done_counts_groups(self):
        from boxradar_site.geo import selection
        self.write_source()
        sel = make_selection(groups=[selection.Group("STANSTED", "A"),
                                     selection.Group("LUTON", "B")])
        step = self.rail(sel)["airspace"]
        self.assertEqual(step.state, steps.DONE)
        self.assertIn("2", step.detail)


class TestPointsStep(RailCase):
    def test_blocked_without_the_datasets(self):
        self.assertEqual(self.rail(make_selection())["points"].state,
                         steps.BLOCKED)

    def test_todo_once_the_datasets_are_there(self):
        self.write_all_datasets()
        self.assertEqual(self.rail(make_selection())["points"].state,
                         steps.TODO)

    def test_done_summarises_each_kind(self):
        self.write_all_datasets()
        sel = make_selection(airfields=[("EGSS", 51.9, 0.2)],
                             waypoints=[("LOREL", 51.8, 0.1),
                                        ("ABBOT", 52.0, 0.3)],
                             towns=[("BISHOPS", 51.87, 0.16)])
        step = self.rail(sel)["points"]
        self.assertEqual(step.state, steps.DONE)
        self.assertIn("1 airfield", step.detail)
        self.assertIn("2 fixes", step.detail)
        self.assertIn("1 town", step.detail)


class TestDeviceStep(RailCase):
    def test_is_optional_and_never_blocks(self):
        # There is no stored state that says the board has been configured,
        # and inventing one would mean a second authority for its NVS. The
        # step is always available and never claims to be done.
        step = self.rail(make_selection())["device"]
        self.assertEqual(step.state, steps.OPTIONAL)

    def test_carries_no_detail_because_that_would_cost_a_request(self):
        # The board's address lives in the display service on :8081. Asking
        # for it on every page render would put an HTTP round trip into the
        # rail; the device page asks for itself.
        self.assertEqual(self.rail(make_selection())["device"].detail, "")


class TestPublishStep(RailCase):
    def test_todo_when_nothing_has_been_published(self):
        step = self.rail(make_selection())["publish"]
        self.assertEqual(step.state, steps.TODO)

    def test_done_when_the_blob_is_newer_than_the_selection(self):
        self.write_selection_file()
        self.write_blob()
        step = self.rail(make_selection())["publish"]
        self.assertEqual(step.state, steps.DONE)

    def test_stale_when_the_selection_moved_on(self):
        # This is the question the old UI could not answer at all: every save
        # said "Publish to rebuild the map" and nothing ever said whether you
        # had.
        self.write_blob()
        import os
        self.write_selection_file()
        os.utime(self.settings.selection_path,
                 (self.settings.blob_path.stat().st_mtime + 10,) * 2)
        step = self.rail(make_selection())["publish"]
        self.assertEqual(step.state, steps.STALE)
        self.assertIn("changed", step.detail.lower())


class TestCost(RailCase):
    def test_the_rail_is_cheap(self):
        """No catalog build, no dataset filter, no coastline. Ever.

        Rendering the rail happens on every page. The expensive calls are the
        ones app.py memoises precisely because they cost a second or more on a
        Pi, and a rail that touched them would hand that cost back on every
        single request.
        """
        def explode(*args, **kwargs):
            raise AssertionError("the rail loaded something expensive")

        from boxradar_site.geo import catalog, generate

        for module, name in ((generate, "load_features"),
                             (generate, "load_coastline"),
                             (catalog, "catalog"),
                             (datasets, "airfields"),
                             (datasets, "towns"),
                             (datasets, "navaids"),
                             (datasets, "runways")):
            original = getattr(module, name)
            setattr(module, name, explode)
            self.addCleanup(setattr, module, name, original)

        self.write_all_datasets()
        self.write_source()
        self.write_selection_file()
        self.write_blob()
        rendered = steps.rail(self.settings, make_selection(), "airspace")
        self.assertEqual(len(rendered), 6)


if __name__ == "__main__":
    unittest.main()
