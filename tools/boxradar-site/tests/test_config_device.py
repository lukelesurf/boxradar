"""The device step: field validation and the two HTTP hops behind it.

No board and no display service in these tests — both are reached through an
injected opener. What is worth checking here is the wiring nobody else can:
that a save pushes only what actually changed, that a field out of range is
refused before it reaches NVS, and that an unreachable board produces a message
rather than a stack trace.

The "only what changed" rule is not an optimisation. Writing a key to NVS
shadows the compiled default for that key permanently and silently — see
site_config.h — so a form that submitted all ten fields would make config.h
dead code for all ten the first time you pressed Save.
"""

import json
import unittest
import urllib.error

from boxradar_config import device


class FakeResponse:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Records requests and replays canned responses by URL suffix."""

    def __init__(self):
        self.responses = {}
        self.calls = []
        self.error = None

    def __call__(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        data = getattr(request, "data", None)
        method = getattr(request, "method", "GET") or "GET"
        self.calls.append((method, url, data))
        if self.error:
            raise self.error
        for suffix, payload in self.responses.items():
            if url.endswith(suffix):
                return FakeResponse(payload)
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)


CURRENT = {
    "fields": {
        "nstart": {"value": 0, "source": "default"},
        "nend": {"value": 7, "source": "default"},
        "nwake": {"value": 30, "source": "default"},
        "nfade": {"value": 600, "source": "default"},
        "nduty": {"value": 7, "source": "default"},
        "poll": {"value": 2000, "source": "default"},
        "mpoll": {"value": 60000, "source": "default"},
        "gpoll": {"value": 600000, "source": "default"},
        "ntp": {"value": "pool.ntp.org", "source": "default"},
        "tz": {"value": "GMT0BST,M3.5.0/1,M10.5.0", "source": "nvs"},
    }
}


class TestFieldTable(unittest.TestCase):
    def test_covers_exactly_the_agreed_keys(self):
        self.assertEqual(
            sorted(f.key for f in device.FIELDS),
            sorted(["nstart", "nend", "nwake", "nfade", "nduty",
                    "poll", "mpoll", "gpoll", "ntp", "tz"]))

    def test_no_credential_or_ota_field_is_offered(self):
        # WiFi and OTA stay portal-only. A typo pushed from here into otapass
        # costs OTA access and needs a USB cable to recover; a typo into ssid
        # costs the board the network that makes it reflashable at all.
        offered = {f.key for f in device.FIELDS}
        for forbidden in ("ssid", "pass", "otahost", "otapass", "recv"):
            self.assertNotIn(forbidden, offered)

    def test_every_field_has_a_group_and_a_label(self):
        for f in device.FIELDS:
            self.assertIn(f.group, {g.key for g in device.GROUPS}, f.key)
            self.assertTrue(f.label, f.key)

    def test_nvs_keys_are_within_the_fifteen_character_limit(self):
        # NVS caps key names at 15 characters and site_config.cpp treats them
        # as a wire format. A key that does not fit would fail at runtime.
        for f in device.FIELDS:
            self.assertLessEqual(len(f.key), 15, f.key)


class TestValidation(unittest.TestCase):
    def parse(self, **form):
        return device.parse_form(form)

    def test_accepts_a_plain_change(self):
        values, clears, problems = self.parse(nstart="23")
        self.assertEqual(problems, [])
        self.assertEqual(values["nstart"], 23)

    def test_blank_fields_are_ignored_entirely(self):
        values, clears, problems = self.parse(nstart="", nend="  ")
        self.assertEqual(values, {})
        self.assertEqual(problems, [])

    def test_unknown_keys_are_ignored(self):
        # The form posts a CSRF-free plain form on a LAN, but a stray key must
        # never become an NVS write under a name the firmware does not know.
        values, _, problems = self.parse(otapass="hunter2", nstart="1")
        self.assertEqual(set(values), {"nstart"})
        self.assertEqual(problems, [])

    def test_non_numeric_is_refused(self):
        _, _, problems = self.parse(nstart="midnight")
        self.assertEqual(len(problems), 1)
        self.assertIn("nstart", problems[0])

    def test_out_of_range_is_refused_with_the_range_in_the_message(self):
        _, _, problems = self.parse(nstart="24")
        self.assertEqual(len(problems), 1)
        self.assertIn("0", problems[0])
        self.assertIn("23", problems[0])

    def test_equal_night_hours_are_allowed_because_that_means_off(self):
        # night_mode.cpp: `if (NIGHT_START_HOUR == NIGHT_END_HOUR) return
        # false; // disabled`. It is the off switch, not a 24-hour blank.
        values, _, problems = self.parse(nstart="3", nend="3")
        self.assertEqual(problems, [])
        self.assertEqual(values["nstart"], 3)

    def test_a_poll_interval_floor_protects_the_pi(self):
        # The board polls a Pi that is also running readsb and tar1090.
        _, _, problems = self.parse(poll="10")
        self.assertEqual(len(problems), 1)

    def test_strings_are_length_checked_against_the_firmware_field(self):
        _, _, problems = self.parse(tz="X" * 200)
        self.assertEqual(len(problems), 1)
        self.assertIn("too long", problems[0].lower())

    def test_clears_are_collected_separately(self):
        _, clears, problems = self.parse(clear="nstart", nend="5")
        self.assertEqual(clears, ["nstart"])
        self.assertEqual(problems, [])

    def test_a_field_cannot_be_both_set_and_cleared(self):
        _, _, problems = self.parse(clear="nstart", nstart="4")
        self.assertEqual(len(problems), 1)
        self.assertIn("nstart", problems[0])

    def test_unknown_clear_targets_are_ignored(self):
        _, clears, problems = self.parse(clear="otapass")
        self.assertEqual(clears, [])
        self.assertEqual(problems, [])


class TestClient(unittest.TestCase):
    def setUp(self):
        self.opener = FakeOpener()
        self.client = device.Client("http://127.0.0.1:8081",
                                    opener=self.opener)

    def test_presence_comes_from_the_display_service(self):
        self.opener.responses["/board"] = {"addr": "192.0.2.42",
                                           "age_s": 1.2, "fresh": True,
                                           "waking": False}
        snap = self.client.presence()
        self.assertEqual(snap["addr"], "192.0.2.42")
        self.assertTrue(snap["fresh"])
        self.assertEqual(self.opener.calls[0][0], "GET")

    def test_a_display_service_that_is_down_is_reported_not_raised(self):
        self.opener.error = OSError("connection refused")
        snap = self.client.presence()
        self.assertIsNone(snap["addr"])
        self.assertFalse(snap["fresh"])
        self.assertIn("error", snap)

    def test_wake_is_a_post(self):
        self.opener.responses["/board/wake"] = {"addr": "192.0.2.42",
                                                "fresh": True, "waking": True}
        self.client.wake()
        method, url, _ = self.opener.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/board/wake"))

    def test_read_config_targets_the_board_not_the_pi(self):
        self.opener.responses["/config"] = CURRENT
        got = self.client.read_config("192.0.2.42")
        self.assertEqual(got["nstart"]["value"], 0)
        _, url, _ = self.opener.calls[0]
        self.assertEqual(url, "http://192.0.2.42/config")

    def test_read_config_on_an_unreachable_board_raises_boarderror(self):
        self.opener.error = OSError("no route to host")
        with self.assertRaises(device.BoardError) as caught:
            self.client.read_config("192.0.2.42")
        self.assertIn("192.0.2.42", str(caught.exception))

    def test_write_sends_only_the_fields_that_differ(self):
        self.opener.responses["/config"] = CURRENT
        self.client.write_config("192.0.2.42",
                                 {"nstart": 23, "nend": 7, "poll": 2000},
                                 clears=[])
        # nend and poll already hold those values. Writing them would shadow
        # their compiled defaults in NVS for no reason at all.
        post = [c for c in self.opener.calls if c[0] == "POST"][0]
        body = post[2].decode()
        self.assertIn("nstart=23", body)
        self.assertNotIn("nend=", body)
        self.assertNotIn("poll=", body)

    def test_a_write_with_nothing_to_do_never_touches_the_board(self):
        self.opener.responses["/config"] = CURRENT
        result = self.client.write_config("192.0.2.42", {"nend": 7},
                                          clears=[])
        self.assertEqual(result["written"], 0)
        self.assertEqual([c for c in self.opener.calls if c[0] == "POST"], [])
        # No restart either — the board must not reboot to apply nothing.
        self.assertFalse(result["restarting"])

    def test_clears_are_sent_even_when_the_value_matches(self):
        # Clearing is about WHERE the value comes from, not what it is. A key
        # sitting in NVS at the same value as the compiled default still
        # shadows it, so "use built-in default" has to be able to remove it.
        self.opener.responses["/config"] = CURRENT
        self.client.write_config("192.0.2.42", {}, clears=["tz"])
        post = [c for c in self.opener.calls if c[0] == "POST"][0]
        self.assertIn("clear=tz", post[2].decode())

    def test_the_boards_own_verdict_wins_over_ours(self):
        # The board validates again and may refuse something, in which case it
        # did not restart either. Claiming a restart that did not happen would
        # have the page announcing five seconds of darkness for nothing.
        def refusing(request, timeout=None):
            if request.method == "POST":
                return FakeResponse({"written": 0, "cleared": 0,
                                     "restarting": False,
                                     "problems": ["nstart: out of range"]})
            return FakeResponse(CURRENT)

        client = device.Client("http://127.0.0.1:8081", opener=refusing)
        result = client.write_config("192.0.2.42", {"nstart": 23}, [])
        self.assertFalse(result["restarting"])
        self.assertEqual(result["written"], 0)
        self.assertIn("nstart: out of range", result["problems"])

    def test_clearing_a_key_that_is_already_a_default_is_a_no_op(self):
        self.opener.responses["/config"] = CURRENT
        result = self.client.write_config("192.0.2.42", {},
                                          clears=["nstart"])
        self.assertEqual(result["cleared"], 0)
        self.assertEqual([c for c in self.opener.calls if c[0] == "POST"], [])


if __name__ == "__main__":
    unittest.main()
