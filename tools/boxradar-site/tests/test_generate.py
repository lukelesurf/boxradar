"""The shared build pipeline.

These tests exist because the pipeline is about to have a second caller. The
CLI had it inline in main(), and a web UI that reimplemented "outlines, then
coastline, then sections, then bytes" would drift from it silently — the blob
would still parse, it would just describe a different site than the CLI does.
"""

import importlib
import pathlib
import tempfile
import unittest
from unittest import mock

from boxradar_site.geo import blob, generate, selection

# A circle boundary is the one YAIXM shape that needs no DMS line-string, so
# the fixtures below say what they mean rather than encoding it.
HOME_LAT, HOME_LON = 51.8667, 0.15


def feature(name, centre="515200N 0000900E", radius="5 nm", kind="CTR"):
    return {"name": name, "type": kind,
            "geometry": [{"boundary": [{"circle": {"centre": centre,
                                                   "radius": radius}}]}]}


def sel(groups=(), **points):
    return selection.Selection(HOME_LAT, HOME_LON, 65.0, list(groups),
                               **points)


def group(name, primary=None, envelope=None):
    return selection.Group(name, primary or name, envelope)


class TestBuild(unittest.TestCase):
    def test_blob_round_trips_with_the_selection_home(self):
        out = generate.build(sel([group("STANSTED")]),
                             [feature("STANSTED")])
        self.assertEqual(out.problems, [])
        got = blob.read(out.blob)
        self.assertAlmostEqual(got["home"][0], HOME_LAT, places=4)
        self.assertAlmostEqual(got["home"][1], HOME_LON, places=4)

    def test_airspace_reaches_the_blob(self):
        out = generate.build(sel([group("STANSTED")]), [feature("STANSTED")])
        rings = blob.read(out.blob)["sections"][blob.KIND_AIRSPACE]
        self.assertEqual(len(rings), 1)
        self.assertGreater(len(rings[0]), 3)

    def test_point_sections_reach_the_blob(self):
        out = generate.build(
            sel([group("STANSTED")],
                airfields=[("EGSS", 51.885, 0.235)],
                # A runway is an unnamed axis segment — the label comes from
                # the airfield marker sitting on top of it.
                runways=[(51.875081, 0.219933, 51.895166, 0.25005)],
                waypoints=[("LOREL", 51.95, 0.30)],
                towns=[("WARE", 51.81, -0.03)]),
            [feature("STANSTED")])
        sections = blob.read(out.blob)["sections"]
        for kind in (blob.KIND_AIRFIELDS, blob.KIND_RUNWAYS,
                     blob.KIND_WAYPOINTS, blob.KIND_TOWNS):
            self.assertEqual(len(sections[kind]), 1, f"kind {kind}")

    def test_coastline_is_included_when_supplied(self):
        coast = [[(51.9, 0.9), (51.95, 1.0), (52.0, 1.05)]]
        out = generate.build(sel([group("STANSTED")]), [feature("STANSTED")],
                             coast=coast)
        sections = blob.read(out.blob)["sections"]
        self.assertIn(blob.KIND_COASTLINE, sections)
        self.assertEqual(len(sections[blob.KIND_COASTLINE]), 1)

    def test_omitted_coastline_leaves_no_section(self):
        out = generate.build(sel([group("STANSTED")]), [feature("STANSTED")])
        self.assertNotIn(blob.KIND_COASTLINE, blob.read(out.blob)["sections"])

    def test_counts_describe_what_was_written(self):
        out = generate.build(sel([group("STANSTED")],
                                 airfields=[("EGSS", 51.885, 0.235)]),
                             [feature("STANSTED")])
        self.assertEqual(out.counts["airspace"], 1)
        self.assertEqual(out.counts["airfields"], 1)
        self.assertEqual(out.counts["towns"], 0)

    def test_same_input_gives_identical_bytes(self):
        # The board caches on the ETag lighttpd derives from the file, so a
        # rebuild that changes nothing must not change the bytes.
        args = (sel([group("STANSTED")]), [feature("STANSTED")])
        self.assertEqual(generate.build(*args).blob,
                         generate.build(*args).blob)


class TestProblemsBlockTheBlob(unittest.TestCase):
    def test_missing_feature_is_reported(self):
        out = generate.build(sel([group("NOWHERE")]), [feature("STANSTED")])
        self.assertTrue(out.problems)
        self.assertIn("NOWHERE", out.problems[0])

    def test_no_blob_is_produced_when_there_are_problems(self):
        # Refusing here rather than in the caller is the point of the module:
        # a UI that forgot the check would publish a map with a hole in it.
        out = generate.build(sel([group("NOWHERE")]), [feature("STANSTED")])
        self.assertIsNone(out.blob)

    def test_coast_loader_is_not_called_for_a_broken_selection(self):
        calls = []

        def loader():
            calls.append(1)
            return []

        generate.build(sel([group("NOWHERE")]), [feature("STANSTED")],
                       coast_loader=loader)
        self.assertEqual(calls, [])

    def test_coast_loader_is_called_for_a_sound_one(self):
        coast = [[(51.9, 0.9), (51.95, 1.0), (52.0, 1.05)]]
        out = generate.build(sel([group("STANSTED")]), [feature("STANSTED")],
                             coast_loader=lambda: coast)
        self.assertIn(blob.KIND_COASTLINE, blob.read(out.blob)["sections"])

    def test_ok_reflects_the_problem_list(self):
        self.assertFalse(generate.build(sel([group("NOWHERE")]),
                                        [feature("STANSTED")]).ok)
        self.assertTrue(generate.build(sel([group("STANSTED")]),
                                       [feature("STANSTED")]).ok)


class TestSourceLoading(unittest.TestCase):
    def test_missing_source_names_the_path_and_the_remedy(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(generate.SourceMissing) as caught:
                generate.load_features(cache_dir=d)
        message = str(caught.exception)
        self.assertIn("airspace.yaml", message)
        self.assertIn("fetch", message)

    def test_importing_does_not_need_a_home_directory(self):
        """A DynamicUser service has no home, and this used to kill it.

        The cache defaults were expanded at import time. Under
        DynamicUser=yes with ProtectHome=true there is no passwd entry and no
        $HOME, so Path.expanduser() raises and the whole application dies
        before main() runs. Nothing caught it: a shell always has $HOME, so
        the CLI and the whole test suite were fine.
        """
        boom = RuntimeError("Could not determine home directory.")
        with mock.patch.object(pathlib.Path, "expanduser", side_effect=boom):
            importlib.reload(generate)
        importlib.reload(generate)  # leave the module as we found it

    def test_a_supplied_cache_dir_never_expands_a_home(self):
        boom = RuntimeError("Could not determine home directory.")
        with mock.patch.object(pathlib.Path, "expanduser", side_effect=boom):
            self.assertIn("somewhere", str(generate.yaml_path("/tmp/somewhere")))

    def test_yaml_path_is_under_the_given_cache_dir(self):
        path = generate.yaml_path("/tmp/somewhere")
        self.assertTrue(str(path).startswith("/tmp/somewhere"))
        self.assertEqual(pathlib.Path(path).name, "airspace.yaml")


if __name__ == "__main__":
    unittest.main()
