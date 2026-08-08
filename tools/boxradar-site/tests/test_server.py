import json
import threading
import unittest
import urllib.error
import urllib.request

from boxradar_site import server
from boxradar_site.config import SiteConfig


class FakeCache:
    def __init__(self):
        self.observations = []
        self.at = 1754640000
        self.stale = False
        self.asked = []

    def get(self, ids):
        self.asked.append(list(ids))
        return self.observations, self.at, self.stale


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.cache = FakeCache()
        self.cfg = SiteConfig({"EGSS": [("04", 43), ("22", 223)]})
        # Port 0 lets the OS choose, so tests never collide with the real
        # service or with each other.
        self.httpd = server.make_server(("127.0.0.1", 0), self.cache, self.cfg)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.load(r)

    def get_expecting_error(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            urllib.request.urlopen(url, timeout=5)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
        self.fail("expected an HTTP error")


class TestParseIds(unittest.TestCase):
    def test_single(self):
        self.assertEqual(server.parse_ids("EGSS"), ["EGSS"])

    def test_lowercase_is_accepted_and_uppercased(self):
        self.assertEqual(server.parse_ids("egss"), ["EGSS"])

    def test_comma_list(self):
        self.assertEqual(server.parse_ids("EGSS,EGGW"), ["EGSS", "EGGW"])

    def test_duplicates_collapse(self):
        self.assertEqual(server.parse_ids("EGSS,EGSS"), ["EGSS"])

    def test_wrong_length_rejected(self):
        self.assertIsNone(server.parse_ids("EGS"))
        self.assertIsNone(server.parse_ids("EGSSX"))

    def test_non_alpha_rejected(self):
        # This is an unauthenticated service that makes outbound requests.
        # The id list goes into an upstream URL, so it is validated, not
        # trusted.
        self.assertIsNone(server.parse_ids("EG.."))
        self.assertIsNone(server.parse_ids("../../etc/passwd"))
        self.assertIsNone(server.parse_ids("EGSS&foo=1"))

    def test_empty_rejected(self):
        self.assertIsNone(server.parse_ids(""))

    def test_too_many_rejected(self):
        self.assertIsNone(server.parse_ids(",".join(["EGSS"] * 9)))


class TestMetarRoute(ServerTest):
    def test_envelope_shape_is_what_loadmetar_parses(self):
        self.cache.observations = [{"icaoId": "EGSS", "wdir": 43, "wspd": 12,
                                    "visib": "6+",
                                    "clouds": [{"cover": "BKN",
                                                "base": 2500}]}]
        status, body = self.get("/metar/EGSS")
        self.assertEqual(status, 200)
        self.assertEqual(body["t"], 1754640000)
        self.assertEqual(body["stale"], 0)
        self.assertEqual(len(body["stations"]), 1)
        station = body["stations"][0]
        self.assertEqual(station["id"], "EGSS")
        self.assertEqual(station["rwy"], "04")
        self.assertEqual(station["conf"], 1)
        self.assertEqual(station["cov"], "BKN")
        self.assertEqual(station["ceil"], 2500)
        self.assertEqual(station["vis"], 9999)

    def test_station_without_a_runway_table_still_serves_weather(self):
        self.cache.observations = [{"icaoId": "EGLL", "wdir": 90, "wspd": 15}]
        _, body = self.get("/metar/EGLL")
        station = body["stations"][0]
        self.assertEqual(station["rwy"], "")
        self.assertEqual(station["conf"], 0)
        self.assertEqual(station["wspd"], 15)

    def test_lowercase_path_works(self):
        self.cache.observations = [{"icaoId": "EGSS"}]
        status, _ = self.get("/metar/egss")
        self.assertEqual(status, 200)
        self.assertEqual(self.cache.asked, [["EGSS"]])

    def test_stale_is_reported(self):
        self.cache.observations = [{"icaoId": "EGSS"}]
        self.cache.stale = True
        _, body = self.get("/metar/EGSS")
        self.assertEqual(body["stale"], 1)

    def test_no_data_at_all_is_503(self):
        self.cache.observations = []
        status, body = self.get_expecting_error("/metar/EGSS")
        self.assertEqual(status, 503)
        self.assertIn("error", body)

    def test_invalid_id_is_400(self):
        status, body = self.get_expecting_error("/metar/NOPE!")
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.cache.asked, [])  # never reached the cache

    def test_response_is_not_cached_by_intermediaries(self):
        self.cache.observations = [{"icaoId": "EGSS"}]
        url = f"http://127.0.0.1:{self.port}/metar/EGSS"
        with urllib.request.urlopen(url, timeout=5) as r:
            self.assertEqual(r.headers["Content-Type"], "application/json")
            self.assertEqual(r.headers["Cache-Control"], "no-store")


class TestHealthRoute(ServerTest):
    def test_healthz(self):
        status, body = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("version", body)

    def test_unknown_path_is_404(self):
        status, body = self.get_expecting_error("/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_bare_metar_without_a_station_is_400(self):
        # /metar/ matches the route prefix, so it reaches the id parser and
        # is rejected there rather than 404ing. Either would be defensible;
        # this is what the code does and the message is the useful one.
        status, body = self.get_expecting_error("/metar/")
        self.assertEqual(status, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
