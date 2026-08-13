"""Everything downloadable, as one list.

Five things have to be on disk before a site can be built: the UK airspace
dataset and four reference files. They arrive by two different mechanisms — a
git checkout and four HTTP downloads — and that difference is real enough that
forcing them into one registry would mean putting a git URL into a tuple shaped
(url, filename, member).

So they are joined here instead, one layer up, where the only questions are
"how old is it" and "go and get it". The Data page and the progress strip both
ask exactly those two questions and should not have to know which mechanism
answers them.
"""

import pathlib
import tempfile
import unittest

from boxradar_config import sources
from boxradar_config.settings import Settings


class SourcesCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = pathlib.Path(self.dir.name)
        self.settings = Settings(root / "selection.json", root / "cache",
                                 root / "www" / "site.bin", 8082)

    def write_dataset(self, name):
        from boxradar_config import datasets
        path = datasets.path_for(name, self.settings.cache_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub")

    def write_airspace(self):
        from boxradar_site.geo import generate
        path = generate.yaml_path(self.settings.source_cache)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("airspace: []")


class TestTheList(SourcesCase):
    def test_airspace_comes_first(self):
        # Everything else is a point reference layered onto the map; the
        # airspace source is what the picker is a picker OF. It is also the
        # one that blocks the most if it is absent.
        self.assertEqual(sources.ALL[0], sources.AIRSPACE)

    def test_it_covers_the_four_datasets_too(self):
        from boxradar_config import datasets
        self.assertEqual(set(sources.ALL),
                         {sources.AIRSPACE} | set(datasets.SOURCES))

    def test_every_source_says_what_it_is_for(self):
        for name in sources.ALL:
            self.assertTrue(sources.PURPOSE.get(name), name)


class TestAge(SourcesCase):
    def test_absent_reads_as_none(self):
        for name in sources.ALL:
            self.assertIsNone(sources.age_days(name, self.settings), name)

    def test_a_present_dataset_has_an_age(self):
        self.write_dataset("towns")
        self.assertLess(sources.age_days("towns", self.settings), 1)

    def test_the_airspace_source_has_an_age_too(self):
        # Its age is the yaml's mtime, not a git timestamp — what matters is
        # when this Pi last pulled, not when the upstream commit was made.
        self.write_airspace()
        self.assertLess(sources.age_days(sources.AIRSPACE, self.settings), 1)

    def test_an_unknown_name_is_refused_rather_than_reported_absent(self):
        # Returning None would make a typo indistinguishable from "not
        # downloaded", and the caller would offer to fetch something that does
        # not exist.
        with self.assertRaises(KeyError):
            sources.age_days("nonsense", self.settings)


class TestMissing(SourcesCase):
    def test_everything_missing_at_first(self):
        self.assertEqual(list(sources.missing(self.settings)),
                         list(sources.ALL))

    def test_nothing_missing_once_all_five_are_there(self):
        self.write_airspace()
        for name in ("airports", "runways", "navaids", "towns"):
            self.write_dataset(name)
        self.assertEqual(list(sources.missing(self.settings)), [])

    def test_missing_keeps_the_canonical_order(self):
        self.write_dataset("towns")
        self.assertEqual(list(sources.missing(self.settings))[0],
                         sources.AIRSPACE)


class TestFetch(SourcesCase):
    def test_a_dataset_is_fetched_through_datasets(self):
        seen = {}

        def fake(name, cache_dir, opener=None, progress=None):
            seen["name"] = name
            if progress:
                progress(512, 1024)
            return "path"

        sources.fetch("towns", self.settings, fetcher=fake)
        self.assertEqual(seen["name"], "towns")

    def test_the_airspace_source_is_fetched_through_generate(self):
        seen = {}

        def fake(cache_dir=None):
            seen["cache"] = cache_dir
            return "path"

        sources.fetch(sources.AIRSPACE, self.settings, source_fetcher=fake)
        self.assertEqual(seen["cache"], self.settings.source_cache)

    def test_progress_is_reported_for_a_dataset(self):
        seen = []

        def fake(name, cache_dir, opener=None, progress=None):
            progress(256, 1024)
            progress(1024, 1024)

        sources.fetch("towns", self.settings, fetcher=fake,
                      progress=lambda done, total: seen.append((done, total)))
        self.assertEqual(seen, [(256, 1024), (1024, 1024)])

    def test_the_git_checkout_reports_no_byte_total(self):
        # It is a subprocess, so there are no bytes to count. Reporting a
        # total of zero would render as a 0% bar that never moves, which reads
        # as a hang rather than as "this step has no measurable progress".
        seen = []
        sources.fetch(sources.AIRSPACE, self.settings,
                      source_fetcher=lambda cache_dir=None: None,
                      progress=lambda done, total: seen.append((done, total)))
        self.assertTrue(all(total is None for _, total in seen), seen)

    def test_an_unknown_name_is_refused(self):
        with self.assertRaises(KeyError):
            sources.fetch("nonsense", self.settings)


if __name__ == "__main__":
    unittest.main()
