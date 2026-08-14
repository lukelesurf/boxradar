"""The type-designator database and the /type route.

The interesting tests here are not the happy path. They are the two ways this
lookup fails SILENTLY — by loading the names-less sibling file, and by treating
an unknown designator as an error the board retries forever — because both
produce a service that is up, answering, and useless.
"""

import gzip
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from boxradar_site import aircraft_types, presence, server
from boxradar_site.config import SiteConfig

from .test_server import FakeCache, FakeClock, FakeFeed

# What tar1090-db actually stores: [name, description code, WTC]. GLID really
# is present with an empty name.
SAMPLE = {
    "PC12": ["PILATUS PC-12", "L1T", "L"],
    "A318": ["AIRBUS A-318", "L2J", "M"],
    "EV97": ["EVEKTRO EV-97 EuroStar", "L1P", "L"],
    "GLID": ["", "L0-", "-"],
}

# The sibling file one character shorter in the same directory. Same keys, no
# names. This is the shape that must be REFUSED.
SAMPLE_NAMELESS = {
    "PC12": {"desc": "L1T", "wtc": "L"},
    "A318": {"desc": "L2J", "wtc": "M"},
}


def write_db(payload):
    """A gzipped JSON file, as tar1090-db ships it — .js extension and all."""
    path = pathlib.Path(tempfile.mkdtemp()) / "icao_aircraft_types2.js"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


class TestLoading(unittest.TestCase):
    def test_a_real_shaped_database_loads(self):
        table = aircraft_types.load(write_db(SAMPLE))
        self.assertEqual(table.name_for("PC12"), "PILATUS PC-12")
        self.assertEqual(table.name_for("A318"), "AIRBUS A-318")

    def test_the_nameless_sibling_file_is_refused(self):
        # icao_aircraft_types.js — no `2` — has the same keys and the same
        # rough size, and loading it yields a table of plausible length that
        # resolves nothing. Refusing on the VALUE SHAPE rather than on the
        # filename is what makes this detectable at all.
        table = aircraft_types.load(write_db(SAMPLE_NAMELESS))
        self.assertEqual(len(table), 0)
        self.assertIsNone(table.name_for("PC12"))

    def test_a_missing_file_is_not_fatal(self):
        # Same discipline as config.py: losing the database costs the type
        # name and nothing else. The board still has the designator.
        table = aircraft_types.load("/nonexistent/icao_aircraft_types2.js")
        self.assertEqual(len(table), 0)
        self.assertIsNone(table.name_for("PC12"))

    def test_a_file_that_is_not_gzip_is_not_fatal(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "plain.js"
        path.write_text(json.dumps(SAMPLE))
        self.assertEqual(len(aircraft_types.load(path)), 0)

    def test_gzipped_rubbish_is_not_fatal(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "rubbish.js"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write("this is not JSON")
        self.assertEqual(len(aircraft_types.load(path)), 0)

    def test_one_malformed_row_does_not_cost_the_others_their_name(self):
        table = aircraft_types.load(write_db({
            "PC12": ["PILATUS PC-12", "L1T", "L"],
            "BAD1": "not a list",
            "BAD2": [],
            "A318": ["AIRBUS A-318", "L2J", "M"],
        }))
        self.assertEqual(table.name_for("PC12"), "PILATUS PC-12")
        self.assertEqual(table.name_for("A318"), "AIRBUS A-318")
        self.assertIsNone(table.name_for("BAD1"))


class TestNameFor(unittest.TestCase):
    def setUp(self):
        self.table = aircraft_types.TypeNames(
            {k: v[0] for k, v in SAMPLE.items() if v[0]})

    def test_case_and_space_are_forgiven(self):
        # The feed sends uppercase; a person types whatever they type.
        for spelling in ("PC12", "pc12", " Pc12 "):
            self.assertEqual(self.table.name_for(spelling), "PILATUS PC-12")

    def test_unknown_is_none(self):
        self.assertIsNone(self.table.name_for("ZZZZ"))

    def test_empty_name_is_none(self):
        # GLID is stored with an empty name. "Present but blank" and "absent"
        # are the same answer to the only caller there is.
        self.assertIsNone(self.table.name_for("GLID"))

    def test_no_designator_is_none(self):
        self.assertIsNone(self.table.name_for(""))
        self.assertIsNone(self.table.name_for(None))


class TestParseTypes(unittest.TestCase):
    def test_single_and_list(self):
        self.assertEqual(server.parse_types("PC12"), ["PC12"])
        self.assertEqual(server.parse_types("PC12,A318"), ["PC12", "A318"])

    def test_lowercase_is_uppercased(self):
        self.assertEqual(server.parse_types("pc12"), ["PC12"])

    def test_short_and_numeric_designators_are_real(self):
        # A1 (Skyraider) and A002 (Irkut) are genuine designators. A
        # four-letters-only rule copied from parse_ids would reject both.
        self.assertEqual(server.parse_types("A1"), ["A1"])
        self.assertEqual(server.parse_types("A002"), ["A002"])
        self.assertEqual(server.parse_types("B738"), ["B738"])

    def test_duplicates_collapse(self):
        self.assertEqual(server.parse_types("PC12,PC12"), ["PC12"])

    def test_the_cap_is_applied_before_dedup(self):
        # The ordering is the point: capping after dedup would let any number
        # of repeats through, since they collapse to one.
        self.assertIsNone(server.parse_types(",".join(["PC12"] * 9)))

    def test_rubbish_rejected(self):
        for bad in ("PC-12", "../../etc/passwd", "PC12&x=1", "TOOLONG", ""):
            self.assertIsNone(server.parse_types(bad), bad)


def loaded_table():
    return aircraft_types.TypeNames(
        {k: v[0] for k, v in SAMPLE.items() if v[0]})


class ServesTypes:
    """Starts the real server on an OS-chosen port. A mixin, not a base test.

    Kept separate from the TestCases so the no-database class can reuse the
    plumbing without inheriting happy-path tests it cannot pass.
    """

    def serve(self, table):
        httpd = server.make_server(
            ("127.0.0.1", 0), FakeCache(), SiteConfig({}),
            fetch_feed=FakeFeed(), board=presence.Presence(clock=FakeClock()),
            types=table)
        self.port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def shutdown():
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.addCleanup(shutdown)

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)


class TypeRouteTest(ServesTypes, unittest.TestCase):
    def setUp(self):
        self.serve(loaded_table())

    def test_a_known_designator_comes_back_named(self):
        status, body = self.get("/type/PC12")
        self.assertEqual(status, 200)
        self.assertEqual(body["types"], [{"id": "PC12",
                                          "name": "PILATUS PC-12"}])

    def test_several_in_one_request(self):
        status, body = self.get("/type/PC12,A318")
        self.assertEqual(status, 200)
        self.assertEqual([e["id"] for e in body["types"]], ["PC12", "A318"])

    def test_an_unknown_designator_is_a_definitive_answer_not_an_error(self):
        # This is the one that matters. A 404 or a 503 here would have the
        # board asking again on every tap for a designator that is never going
        # to resolve; an id echoed with no name is something it can cache.
        status, body = self.get("/type/ZZZZ")
        self.assertEqual(status, 200)
        self.assertEqual(body["types"], [{"id": "ZZZZ"}])

    def test_a_designator_with_a_blank_name_answers_the_same_way(self):
        status, body = self.get("/type/GLID")
        self.assertEqual(status, 200)
        self.assertEqual(body["types"], [{"id": "GLID"}])

    def test_rubbish_is_a_400(self):
        status, _ = self.get("/type/PC-12")
        self.assertEqual(status, 400)

    def test_the_other_routes_still_work(self):
        # The route is a new prefix on a shared handler; /metar and /board must
        # be untouched by it.
        self.assertEqual(self.get("/board")[0], 200)
        self.assertEqual(self.get("/healthz")[0], 200)


class TypeRouteWithNoDatabaseTest(ServesTypes, unittest.TestCase):
    """Deliberately NOT a subclass of TypeRouteTest.

    Inheriting would bring the happy-path tests along, and they cannot pass
    without a database — they would have to be disabled by assigning None over
    them, which works only because unittest's loader filters on callable().
    Sharing the plumbing through a mixin and listing the three tests that do
    apply is duller and says what it means.
    """

    def setUp(self):
        self.serve(aircraft_types.TypeNames())

    def test_a_missing_database_is_a_503(self):
        # Distinct from an unknown designator on purpose: this one MAY come
        # good later — the file could be installed, the service restarted — so
        # the board should be free to ask again.
        status, _ = self.get("/type/PC12")
        self.assertEqual(status, 503)

    def test_rubbish_is_still_a_400_not_a_503(self):
        # The order of the two checks in _types matters: validate first. A bad
        # designator is the caller's fault whether or not a database exists.
        status, _ = self.get("/type/PC-12")
        self.assertEqual(status, 400)

    def test_the_other_routes_are_unaffected(self):
        self.assertEqual(self.get("/board")[0], 200)
        self.assertEqual(self.get("/healthz")[0], 200)


if __name__ == "__main__":
    unittest.main()
