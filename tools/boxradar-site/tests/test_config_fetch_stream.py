"""The streamed download page.

The property under test is that progress reaches the browser WHILE the
download is running. That is easy to get wrong in a way nothing else catches:
collecting the fragments and yielding them after the fetch returns produces a
response with all the right bytes in the right order, passes any shape
assertion, and defeats the entire feature — every bar jumps 0 to 100 at the
moment the file has already landed.

So the first test here holds a fake fetch open and insists a fragment has
already arrived. It is the only one that would fail against that mistake.
"""

import pathlib
import tempfile
import threading
import unittest

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

from boxradar_config import sources


@unittest.skipUnless(HAVE_FLASK, "needs flask (it is in the devShell)")
class StreamCase(unittest.TestCase):
    def setUp(self):
        from boxradar_config.app import create_app
        from boxradar_config.settings import Settings

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = pathlib.Path(self.dir.name)
        self.settings = Settings(root / "selection.json", root / "cache",
                                 root / "www" / "site.bin", 8082)
        app = create_app(self.settings)
        app.config["TESTING"] = True
        self.client = app.test_client()

        self.real_fetch = sources.fetch
        self.addCleanup(setattr, sources, "fetch", self.real_fetch)

    def patch_fetch(self, fake):
        sources.fetch = fake


class TestItReallyStreams(StreamCase):
    def test_a_fragment_arrives_before_the_fetch_returns(self):
        reported = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        self.addCleanup(release.set)

        def fake(name, settings, progress=None, **kw):
            progress(256 * 1024, 10 * 1024 * 1024)
            reported.set()
            # Held open until the test lets go. `finished` is the honest
            # discriminator: an earlier version of this test asserted only
            # that `release` was unset, which a buffering implementation
            # satisfied by simply letting the wait time out. Whether the fetch
            # has RETURNED is the thing that separates the two.
            release.wait(30)
            finished.set()

        self.patch_fetch(fake)
        response = self.client.post("/data/fetch", data={"source": "towns"},
                                    buffered=False)
        # The generator only runs while something pulls it, so the fetch does
        # not start until here.
        stream = response.iter_encoded()

        seen = b""
        for chunk in stream:
            seen += chunk
            if b'u("towns"' in seen:
                break

        # The assertion that matters: the fragment is in hand while the fetch
        # has NOT yet returned. A version that collects fragments and flushes
        # them after the work would only get here once `fake` had returned,
        # so `finished` would be set.
        self.assertIn(b'u("towns"', seen,
                      "no progress reached the client mid-download")
        self.assertTrue(reported.is_set())
        self.assertFalse(finished.is_set(),
                         "progress only arrived after the fetch returned — "
                         "the fragments are being buffered, which defeats "
                         "the whole point")

        release.set()
        for _ in stream:  # drain, so the worker thread finishes cleanly
            pass


class TestReporting(StreamCase):
    def run_fetch(self, fake, **form):
        self.patch_fetch(fake)
        return self.client.post("/data/fetch", data=form).data.decode()

    def test_the_page_lists_every_requested_source_up_front(self):
        body = self.run_fetch(lambda name, settings, progress=None, **kw: None)
        for name in sources.ALL:
            self.assertIn(f'id="job-{name}"', body, name)

    def test_defaults_to_everything(self):
        seen = []

        def fake(name, settings, progress=None, **kw):
            seen.append(name)

        self.run_fetch(fake)
        self.assertEqual(seen, list(sources.ALL))

    def test_only_the_ticked_sources_are_fetched(self):
        seen = []

        def fake(name, settings, progress=None, **kw):
            seen.append(name)

        self.patch_fetch(fake)
        self.client.post("/data/fetch",
                         data={"source": ["towns", "navaids"]}).data
        self.assertEqual(seen, ["towns", "navaids"])

    def test_an_unknown_source_is_ignored_not_fetched(self):
        seen = []

        def fake(name, settings, progress=None, **kw):
            seen.append(name)

        self.patch_fetch(fake)
        self.client.post("/data/fetch",
                         data={"source": "../../etc/passwd"}).data
        # Falls back to everything rather than fetching a name that is not a
        # source. Nothing here interpolates the name into a path, but the
        # whitelist is what guarantees that stays true.
        self.assertEqual(seen, list(sources.ALL))

    def test_one_failure_does_not_stop_the_rest(self):
        def fake(name, settings, progress=None, **kw):
            if name == "airports":
                raise OSError("network went away")

        body = self.run_fetch(fake)
        self.assertIn("airports failed", body)
        self.assertIn("network went away", body)
        self.assertIn("source(s) failed", body)
        # towns comes after airports in the list and must still have run.
        self.assertIn("<li>towns", body)

    def test_a_clean_run_says_so_and_offers_the_way_on(self):
        body = self.run_fetch(lambda name, settings, progress=None, **kw: None)
        self.assertIn("Downloaded 5 source(s)", body)
        self.assertIn("Continue", body)

    def test_it_returns_to_the_page_that_sent_you(self):
        self.patch_fetch(lambda name, settings, progress=None, **kw: None)
        body = self.client.post(
            "/data/fetch",
            data={"source": "towns", "next": "/points/towns"}).data.decode()
        self.assertIn('href="/points/towns"', body)

    def test_an_error_message_cannot_inject_markup(self):
        # The message comes from an exception, which can hold anything.
        def fake(name, settings, progress=None, **kw):
            raise OSError("<script>alert(1)</script>")

        body = self.run_fetch(fake, source="towns")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_every_throttle_step_is_reported_not_just_the_first(self):
        """A skipped update must not end the stream.

        Found on the live Pi, not here: a 14MB download reported 1% once and
        then nothing for eighteen seconds. The throttle returns None between
        steps, and None was also the queue's end-of-stream sentinel — so the
        first throttled update looked like "the fetch is over" and every
        fragment after it was dropped on the floor.

        Ten megabytes in 64KB chunks against a 256KB throttle is 40 expected
        fragments, and the great majority of the calls in between return
        nothing.
        """
        def fake(name, settings, progress=None, **kw):
            size = 10 * 1024 * 1024
            for done in range(65536, size + 1, 65536):
                progress(done, size)

        body = self.run_fetch(fake, source="towns")
        fragments = body.count('u("towns"')
        self.assertGreater(fragments, 30,
                           f"only {fragments} progress updates survived")
        # And the last one has to be the finished figure, or the bar stops
        # short of the end while the file is already on disk.
        self.assertIn(f'u("towns",{10 * 1024 * 1024},', body)

    def test_progress_without_a_total_is_reported_as_unknown(self):
        # The git checkout has no byte count. "null" is what the page reads as
        # an indeterminate bar rather than a stuck 0%.
        def fake(name, settings, progress=None, **kw):
            progress(0, None)

        body = self.run_fetch(fake, source="airspace")
        self.assertIn('u("airspace",0,null)', body)


if __name__ == "__main__":
    unittest.main()
