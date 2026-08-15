"""The operator table, and the route that serves it.

Mirrors test_aircraft_types.py: the interesting cases are all about telling
"no answer" apart from "answered with nothing", because the board caches the
second and retries the first.
"""

import gzip
import json
import tempfile
import unittest
import urllib.error
import urllib.request

from boxradar_site import operators, server
from tests.test_server import ServerTest

TABLE = {
    "BAW": {"n": "British Airways", "c": "United Kingdom", "r": "SPEEDBIRD"},
    "RRR": {"n": "RAF HQSTC", "c": "United Kingdom", "r": "ASCOT"},
    "ZZZ": {"n": "No Radio Air", "c": "Nowhere", "r": ""},
    "QQQ": {"n": "", "c": "Nowhere", "r": "GHOST"},
}


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.ops = operators.Operators(dict(TABLE))

    def test_name_and_radio(self):
        self.assertEqual(self.ops.lookup("BAW"),
                         ("British Airways", "SPEEDBIRD"))

    def test_the_radio_callsign_is_often_the_recognisable_half(self):
        # RRR is "RAF HQSTC" on paper and ASCOT on the air. This is the case
        # that justifies serving both rather than just the name.
        self.assertEqual(self.ops.lookup("RRR"), ("RAF HQSTC", "ASCOT"))

    def test_lookup_is_case_insensitive_and_trims(self):
        self.assertEqual(self.ops.lookup(" baw "),
                         ("British Airways", "SPEEDBIRD"))

    def test_a_missing_radio_is_a_partial_answer(self):
        self.assertEqual(self.ops.lookup("ZZZ"), ("No Radio Air", ""))

    def test_an_entry_with_no_name_is_no_answer(self):
        # A radio callsign with nothing to attach it to is not useful, and the
        # panel has no row that says only "GHOST".
        self.assertIsNone(self.ops.lookup("QQQ"))

    def test_absent_and_empty_are_the_same_answer(self):
        self.assertIsNone(self.ops.lookup("XXX"))
        self.assertIsNone(self.ops.lookup(""))
        self.assertIsNone(self.ops.lookup(None))
        self.assertIsNone(operators.Operators().lookup("BAW"))


class TestLoad(unittest.TestCase):
    def write(self, payload, gzipped=True, prefix=""):
        f = tempfile.NamedTemporaryFile(suffix=".js", delete=False)
        body = (prefix + json.dumps(payload)).encode()
        f.write(gzip.compress(body) if gzipped else body)
        f.close()
        return f.name

    def test_reads_a_gzipped_table(self):
        ops = operators.load(self.write(TABLE))
        self.assertEqual(len(ops), 4)
        self.assertEqual(ops.lookup("BAW")[1], "SPEEDBIRD")

    def test_reads_a_plain_one_too(self):
        # So a decompressed fixture behaves like the shipped file.
        ops = operators.load(self.write(TABLE, gzipped=False))
        self.assertEqual(len(ops), 4)

    def test_a_javascript_prefix_is_skipped(self):
        ops = operators.load(self.write(TABLE, prefix="var operators = "))
        self.assertEqual(len(ops), 4)

    def test_a_missing_file_is_empty_not_an_exception(self):
        # An absent database costs the operator name and nothing else.
        self.assertEqual(len(operators.load("/nonexistent/operators.js")), 0)

    def test_the_wrong_file_is_refused_rather_than_half_loaded(self):
        # The trap next door: a file of plausible size and plausible keys that
        # holds the wrong shape would install cleanly and resolve nothing.
        wrong = {"BAW": ["British Airways", "L2J"], "RYR": ["Ryanair", "L2J"]}
        self.assertEqual(len(operators.load(self.write(wrong))), 0)

    def test_a_file_that_is_not_json_is_refused(self):
        f = tempfile.NamedTemporaryFile(suffix=".js", delete=False)
        f.write(gzip.compress(b"not json at all"))
        f.close()
        self.assertEqual(len(operators.load(f.name)), 0)


class TestRoute(ServerTest):
    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.load(r)

    def setUp(self):
        super().setUp()
        self.shutdown()
        self.httpd = server.make_server(
            ("127.0.0.1", 0), self.cache, self.cfg, fetch_feed=self.feed,
            board=self.presence, ops=operators.Operators(dict(TABLE)))
        self.port = self.httpd.server_address[1]
        import threading
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def test_serves_one_code(self):
        status, body = self.get("/operator/BAW")
        self.assertEqual(status, 200)
        self.assertEqual(body["operators"],
                         [{"id": "BAW", "name": "British Airways",
                           "radio": "SPEEDBIRD"}])

    def test_lowercase_is_accepted(self):
        _, body = self.get("/operator/baw")
        self.assertEqual(body["operators"][0]["id"], "BAW")

    def test_an_unknown_code_is_echoed_with_no_name(self):
        # 200 with a nameless entry, NOT a 404: the board caches this and stops
        # asking, where an error would have it retry a code that will never
        # resolve. Same contract as /type.
        _, body = self.get("/operator/XXX")
        self.assertEqual(body["operators"], [{"id": "XXX"}])

    def test_an_entry_with_no_radio_omits_the_key(self):
        _, body = self.get("/operator/ZZZ")
        self.assertEqual(body["operators"],
                         [{"id": "ZZZ", "name": "No Radio Air"}])

    def test_several_in_one_call(self):
        _, body = self.get("/operator/BAW,RRR")
        self.assertEqual([e["id"] for e in body["operators"]], ["BAW", "RRR"])

    def test_a_non_airline_shaped_code_is_400(self):
        # Three letters exactly. A registration-derived key would be four or
        # more, and the firmware refuses it a step earlier.
        for bad in ("BA", "BAW1", "B1W", "TOOLONG"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(f"/operator/{bad}")
            self.assertEqual(caught.exception.code, 400, bad)


class TestRouteWithNoDatabase(ServerTest):
    def test_no_database_is_503_so_the_board_retries(self):
        # The opposite case to an unknown code: this one may come good, so it
        # must not look like a definitive answer.
        url = f"http://127.0.0.1:{self.port}/operator/BAW"
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(url, timeout=5)
        self.assertEqual(caught.exception.code, 503)


if __name__ == "__main__":
    unittest.main()


class TestWatchPreview(ServerTest):
    """The route that stops a fuzzy pattern being a guess.

    Both traps it exists for are pinned here, because both were found by
    reading the real table rather than by reasoning: the A380's name is
    hyphenated where Boeing's is not, and "C-130" is a substring of
    "EUROCOPTER EC-130".
    """

    NAMES = {
        "B738": "BOEING 737-800",
        "B38M": "BOEING 737 MAX 8",
        "A388": "AIRBUS A-380-800",
        "C130": "LOCKHEED C-130 Hercules",
        "C30J": "LOCKHEED MARTIN C-130J Super Hercules",
        "EC30": "EUROCOPTER EC-130",
    }

    def setUp(self):
        super().setUp()
        self.shutdown()
        from boxradar_site import aircraft_types
        self.httpd = server.make_server(
            ("127.0.0.1", 0), self.cache, self.cfg, fetch_feed=self.feed,
            board=self.presence,
            types=aircraft_types.TypeNames(dict(self.NAMES)))
        self.port = self.httpd.server_address[1]
        import threading
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r)

    def test_a_name_pattern_lists_what_it_catches(self):
        body = self.get("/watch/737")
        self.assertEqual(body["count"], 2)
        self.assertEqual(sorted(t["id"] for t in body["types"]),
                         ["B38M", "B738"])
        self.assertEqual({t["via"] for t in body["types"]}, {"name"})

    def test_a_designator_prefix_is_reported_as_such(self):
        body = self.get("/watch/B7")
        self.assertEqual({t["via"] for t in body["types"]}, {"designator"})

    def test_the_hyphen_trap_is_visible_here(self):
        # The whole reason for the route: A380 looks obviously right and
        # catches nothing at all.
        self.assertEqual(self.get("/watch/A380")["count"], 0)
        self.assertEqual(self.get("/watch/A-380")["count"], 1)

    def test_the_over_match_is_visible_here_too(self):
        self.assertEqual(sorted(t["id"] for t in self.get("/watch/C-130")["types"]),
                         ["C130", "C30J", "EC30"])
        self.assertEqual(sorted(t["id"] for t in self.get("/watch/Hercules")["types"]),
                         ["C130", "C30J"])

    def test_a_short_pattern_matches_designators_only(self):
        # Mirrors MIN_NAME_PATTERN in contacts.py: below three characters a
        # pattern collides with names rather than describing them.
        body = self.get("/watch/37")
        self.assertEqual([t["via"] for t in body["types"]], [])

    def test_a_malformed_pattern_is_400(self):
        for bad in ("has%20space", "a%2Fb", ""):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(f"/watch/{bad}")
            self.assertEqual(caught.exception.code, 400, bad)
