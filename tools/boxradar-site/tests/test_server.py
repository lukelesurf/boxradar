import json
import threading
import unittest
import urllib.error
import urllib.request

from boxradar_site import contacts, feed, presence, server
from boxradar_site.config import SiteConfig


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeCache:
    def __init__(self):
        self.observations = []
        self.at = 1754640000
        self.stale = False
        self.asked = []

    def get(self, ids):
        self.asked.append(list(ids))
        return self.observations, self.at, self.stale


class FakeFeed:
    def __init__(self):
        self.aircraft = []
        self.error = None
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.aircraft


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.cache = FakeCache()
        self.feed = FakeFeed()
        self.cfg = SiteConfig({"EGSS": [("04", 43), ("22", 223)]})
        self.clock = FakeClock()
        self.presence = presence.Presence(clock=self.clock)
        # Port 0 lets the OS choose, so tests never collide with the real
        # service or with each other.
        self.httpd = server.make_server(("127.0.0.1", 0), self.cache, self.cfg,
                                        fetch_feed=self.feed,
                                        board=self.presence)
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


class TestParseSite(unittest.TestCase):
    def test_accepts_a_well_formed_query(self):
        self.assertEqual(server.parse_site("lat=51.9&lon=0.03&n=32"),
                         (51.9, 0.03, 32))

    def test_negative_longitude(self):
        self.assertEqual(server.parse_site("lat=51.9&lon=-0.36&n=1")[1], -0.36)

    def test_missing_parameters_are_rejected(self):
        self.assertIsNone(server.parse_site("lat=51.9&lon=0.03"))
        self.assertIsNone(server.parse_site("n=32"))
        self.assertIsNone(server.parse_site(""))

    def test_unparseable_values_are_rejected(self):
        self.assertIsNone(server.parse_site("lat=north&lon=0.03&n=32"))
        self.assertIsNone(server.parse_site("lat=51.9&lon=0.03&n=lots"))

    def test_out_of_range_positions_are_rejected(self):
        self.assertIsNone(server.parse_site("lat=91&lon=0&n=32"))
        self.assertIsNone(server.parse_site("lat=0&lon=181&n=32"))

    def test_nan_is_rejected_by_the_range_check(self):
        self.assertIsNone(server.parse_site("lat=nan&lon=0&n=32"))

    def test_count_must_be_within_the_ceiling(self):
        self.assertIsNone(server.parse_site("lat=51.9&lon=0.03&n=0"))
        self.assertIsNone(
            server.parse_site(f"lat=51.9&lon=0.03&n={server.MAX_CONTACTS + 1}"))


class TestContactsRoute(ServerTest):
    HOME = "lat=51.88501837&lon=0.23502732"

    def get_binary(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read(), r.headers

    def test_serves_a_parseable_feed(self):
        self.feed.aircraft = [
            {"hex": "400abc", "lat": 52.0, "lon": 0.1, "seen": 1.0,
             "flight": "BAW123 ", "t": "A320", "alt_baro": 3000},
        ]
        status, body, _ = self.get_binary(f"/contacts?{self.HOME}&n=32")
        self.assertEqual(status, 200)
        got = contacts.read(body)
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["contacts"][0]["callsign"], "BAW123")

    def test_content_type_is_binary_and_uncached(self):
        _, _, headers = self.get_binary(f"/contacts?{self.HOME}&n=32")
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_quiet_sky_is_a_valid_empty_feed(self):
        status, body, _ = self.get_binary(f"/contacts?{self.HOME}&n=32")
        self.assertEqual(status, 200)
        self.assertEqual(contacts.read(body)["contacts"], [])

    def test_n_caps_the_records_but_not_the_total(self):
        self.feed.aircraft = [
            {"hex": f"4000{i:02x}", "lat": 52.0 + i / 100.0, "lon": 0.1,
             "seen": 1.0}
            for i in range(10)
        ]
        _, body, _ = self.get_binary(f"/contacts?{self.HOME}&n=4")
        got = contacts.read(body)
        self.assertEqual(len(got["contacts"]), 4)
        self.assertEqual(got["total"], 10)

    def test_a_dead_receiver_is_503_not_an_empty_feed(self):
        self.feed.error = feed.FeedError("connection refused")
        status, body = self.get_expecting_error(f"/contacts?{self.HOME}&n=32")
        self.assertEqual(status, 503)
        self.assertIn("error", body)

    def test_a_bad_query_is_400_and_never_touches_the_receiver(self):
        status, body = self.get_expecting_error("/contacts?lat=51.9&n=32")
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertEqual(self.feed.calls, 0)


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


class TestBoardRoutes(ServerTest):
    """Presence and the config-wake signal.

    The signal rides on a RESPONSE HEADER of the existing /contacts poll, not
    in the payload. The contact header is <4sHHHH with no reserved field, so a
    flag byte would have meant bumping CONTACT_VERSION — and contact_feed.h
    rejects a version it does not know outright, blanking the scope until
    firmware and Pi were updated in lockstep. An unknown response header is
    ignored by definition, so an updated Pi keeps working with old firmware.
    """

    HOME = "lat=51.88501837&lon=0.23502732"

    def poll_contacts(self):
        """As a browser or curl would: HTTP/1.1."""
        url = f"http://127.0.0.1:{self.port}/contacts?{self.HOME}&n=32"
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.read(), r.headers

    def poll_contacts_as_board(self):
        """As the firmware does: HTTP/1.0, which is what identifies it."""
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn._http_vsn = 10
        conn._http_vsn_str = "HTTP/1.0"
        conn.request("GET", f"/contacts?{self.HOME}&n=32")
        r = conn.getresponse()
        body, headers = r.read(), r.headers
        conn.close()
        return body, headers

    def post(self, path, expect=200):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url, data=b"", method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                self.assertEqual(r.status, expect)
                return json.load(r)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, expect)
            return json.load(e)

    def test_polling_records_the_board(self):
        self.assertIsNone(self.presence.snapshot()["addr"])
        self.poll_contacts_as_board()
        snap = self.presence.snapshot()
        self.assertEqual(snap["addr"], "127.0.0.1")
        self.assertTrue(snap["fresh"])

    def test_board_route_reports_the_snapshot(self):
        self.poll_contacts_as_board()
        status, body = self.get("/board")
        self.assertEqual(status, 200)
        self.assertEqual(body["addr"], "127.0.0.1")
        self.assertTrue(body["fresh"])
        self.assertFalse(body["waking"])

    def test_board_route_before_anything_has_polled(self):
        status, body = self.get("/board")
        self.assertEqual(status, 200)
        self.assertIsNone(body["addr"])
        self.assertFalse(body["fresh"])

    def test_no_config_header_when_nobody_asked(self):
        # The board must never be told to open a server unprompted.
        _, headers = self.poll_contacts()
        self.assertIsNone(headers.get("X-Boxradar-Config"))

    def test_wake_sets_the_header_on_the_next_poll(self):
        self.post("/board/wake")
        _, headers = self.poll_contacts()
        self.assertEqual(headers.get("X-Boxradar-Config"), "1")

    def test_the_header_stops_once_the_window_closes(self):
        self.post("/board/wake")
        self.clock.advance(presence.WAKE_WINDOW_S + 1)
        _, headers = self.poll_contacts()
        self.assertIsNone(headers.get("X-Boxradar-Config"))

    def test_the_payload_is_byte_identical_either_way(self):
        # The whole reason for using a header is that the binary format does
        # not change. If waking altered a single byte of the body, the format
        # would need a version bump after all and this design would be wrong.
        self.feed.aircraft = [
            {"hex": "4008f3", "flight": "BAW123", "lat": 51.95, "lon": 0.05,
             "alt_baro": 3000, "gs": 220, "track": 90, "seen": 1.0,
             "rssi": -12.5},
        ]
        quiet, _ = self.poll_contacts()
        self.post("/board/wake")
        waking, headers = self.poll_contacts()
        self.assertEqual(headers.get("X-Boxradar-Config"), "1")
        self.assertEqual(quiet, waking)

    def test_wake_reports_whether_the_board_is_even_there(self):
        # Pressing wake against a board nobody has heard from is not an error,
        # but the UI has to be able to say so rather than spin.
        body = self.post("/board/wake")
        self.assertFalse(body["fresh"])
        self.poll_contacts_as_board()
        body = self.post("/board/wake")
        self.assertTrue(body["fresh"])
        self.assertTrue(body["waking"])

    def test_the_header_rides_a_503_too(self):
        # A failing receiver must not also cost you the ability to configure
        # the board. The board is still polling and still reachable; only the
        # traffic behind the request is missing, and the two have nothing to
        # do with each other. Found by running it, not by reading it: the
        # header started life in the binary responder, which a 503 never
        # reaches.
        self.feed.error = feed.FeedError("receiver unreachable")
        self.post("/board/wake")
        url = f"http://127.0.0.1:{self.port}/contacts?{self.HOME}&n=32"
        try:
            urllib.request.urlopen(url, timeout=5)
            self.fail("expected a 503")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 503)
            self.assertEqual(e.headers.get("X-Boxradar-Config"), "1")

    def test_a_failed_poll_still_records_presence(self):
        self.feed.error = feed.FeedError("receiver unreachable")
        try:
            self.poll_contacts_as_board()
        except Exception:
            pass
        self.assertTrue(self.presence.snapshot()["fresh"])

    def test_a_rejected_request_does_not_count_as_the_board(self):
        # A 400 means whatever sent it did not speak the protocol, so it was
        # not the board and must not update where we think the board is.
        self.get_expecting_error("/contacts?lat=51.9&n=32")
        self.assertIsNone(self.presence.snapshot()["addr"])

    def test_the_header_never_appears_on_unrelated_routes(self):
        self.post("/board/wake")
        url = f"http://127.0.0.1:{self.port}/healthz"
        with urllib.request.urlopen(url, timeout=5) as r:
            self.assertIsNone(r.headers.get("X-Boxradar-Config"))

    def test_a_browser_or_curl_is_not_mistaken_for_the_board(self):
        """Found live, from this project's own diagnostics.

        urllib sends HTTP/1.1, as browsers and curl do. The board sends 1.0
        because net_task.cpp calls useHTTP10(true). Recording every caller had
        /board reporting the home server's address, and would have pointed the
        Device page's config push at a workstation.
        """
        self.poll_contacts()          # urllib: HTTP/1.1
        self.assertIsNone(self.presence.snapshot()["addr"])

    def test_an_http_10_poll_is_the_board(self):
        self.poll_contacts_as_board()
        self.assertEqual(self.presence.snapshot()["addr"], "127.0.0.1")

    def test_a_later_browser_request_does_not_refresh_the_board(self):
        # Otherwise an unplugged board looks alive for as long as anyone has
        # the page open.
        self.poll_contacts_as_board()
        self.clock.advance(60)
        self.poll_contacts()
        snap = self.presence.snapshot()
        self.assertEqual(snap["addr"], "127.0.0.1")
        self.assertFalse(snap["fresh"])

    def test_geo_reload_sets_its_own_header(self):
        self.post("/board/reload-geo")
        _, headers = self.poll_contacts()
        self.assertEqual(headers.get("X-Boxradar-Geo"), "1")
        self.assertIsNone(headers.get("X-Boxradar-Config"),
                          "publishing must not open the settings server")

    def test_wake_does_not_set_the_geo_header(self):
        self.post("/board/wake")
        _, headers = self.poll_contacts()
        self.assertEqual(headers.get("X-Boxradar-Config"), "1")
        self.assertIsNone(headers.get("X-Boxradar-Geo"))

    def test_both_signals_can_ride_together(self):
        self.post("/board/wake")
        self.post("/board/reload-geo")
        _, headers = self.poll_contacts()
        self.assertEqual(headers.get("X-Boxradar-Config"), "1")
        self.assertEqual(headers.get("X-Boxradar-Geo"), "1")

    def test_the_geo_header_rides_a_503_too(self):
        # Same reason as the config one: a broken receiver must not also stop
        # a published map from reaching the board.
        self.feed.error = feed.FeedError("receiver unreachable")
        self.post("/board/reload-geo")
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/contacts?{self.HOME}&n=32",
                timeout=5)
            self.fail("expected a 503")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.headers.get("X-Boxradar-Geo"), "1")

    def test_the_geo_window_expires(self):
        self.post("/board/reload-geo")
        self.clock.advance(presence.WAKE_WINDOW_S + 1)
        _, headers = self.poll_contacts()
        self.assertIsNone(headers.get("X-Boxradar-Geo"))

    def test_wake_is_not_a_get(self):
        # It changes state. A GET would let a stray browser prefetch open the
        # board's config server.
        status, _ = self.get_expecting_error("/board/wake")
        self.assertEqual(status, 404)

    def test_unknown_post_is_404(self):
        self.post("/nope", expect=404)


if __name__ == "__main__":
    unittest.main()
