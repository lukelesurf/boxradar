"""The device step as a route, with a fake board.

device.py's own tests cover validation and the diff. What only these can cover
is the page's behaviour when the board is not there — which is the normal case
for a page you open before checking whether the thing is plugged in.
"""

import pathlib
import tempfile
import unittest

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

from boxradar_config import device

ABSENT = {"addr": None, "age_s": None, "fresh": False, "waking": False}
PRESENT = {"addr": "192.0.2.42", "age_s": 1.5, "fresh": True,
           "waking": True}

FIELDS = {
    "nstart": {"value": 0, "source": "default"},
    "nend": {"value": 7, "source": "default"},
    "nwake": {"value": 30, "source": "default"},
    "nfade": {"value": 600, "source": "default"},
    "nduty": {"value": 7, "source": "nvs"},
    "poll": {"value": 2000, "source": "default"},
    "mpoll": {"value": 60000, "source": "default"},
    "gpoll": {"value": 600000, "source": "default"},
    "ntp": {"value": "pool.ntp.org", "source": "default"},
    "tz": {"value": "GMT0BST,M3.5.0/1,M10.5.0", "source": "default"},
}


class FakeBoard:
    def __init__(self, snapshot=None, fields=None, error=None):
        self.snapshot = snapshot or dict(PRESENT)
        self.fields = fields if fields is not None else dict(FIELDS)
        self.error = error
        self.woke = 0
        self.writes = []

    def wake(self):
        self.woke += 1
        return self.snapshot

    def presence(self):
        return self.snapshot

    def read_config(self, addr):
        if self.error:
            raise device.BoardError(self.error)
        return self.fields

    def write_config(self, addr, values, clears):
        if self.error:
            raise device.BoardError(self.error)
        self.writes.append((addr, values, clears))
        return {"written": len(values), "cleared": len(clears),
                "restarting": bool(values or clears), "problems": []}


@unittest.skipUnless(HAVE_FLASK, "needs flask (it is in the devShell)")
class DevicePageCase(unittest.TestCase):
    def build(self, board):
        from boxradar_config.app import create_app
        from boxradar_config.settings import Settings

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = pathlib.Path(self.dir.name)
        settings = Settings(root / "selection.json", root / "cache",
                            root / "www" / "site.bin", 8082)
        app = create_app(settings, board=board)
        app.config["TESTING"] = True
        self.board = board
        return app.test_client()


class TestReading(DevicePageCase):
    def test_opening_the_page_wakes_the_board(self):
        # Nothing else asks. The board only opens its settings server when the
        # display service flags a contact poll, and this page is what makes it
        # do that.
        client = self.build(FakeBoard())
        client.get("/device")
        self.assertEqual(self.board.woke, 1)

    def test_the_current_values_are_shown(self):
        client = self.build(FakeBoard())
        body = client.get("/device").data
        self.assertIn(b'value="600"', body)          # nfade
        self.assertIn(b"pool.ntp.org", body)

    def test_an_nvs_backed_field_is_marked_and_offers_a_clear(self):
        # nduty is the one from NVS in the fixture. Saying so matters: a value
        # in NVS shadows the compiled default permanently and silently.
        client = self.build(FakeBoard())
        body = client.get("/device").data.decode()
        self.assertIn("saved on board", body)
        self.assertIn('name="clear" value="nduty"', body)

    def test_a_board_that_has_not_polled_says_so_and_offers_no_form(self):
        client = self.build(FakeBoard(snapshot=dict(ABSENT)))
        body = client.get("/device").data
        self.assertIn(b"No contact poll recently", body)
        self.assertNotIn(b"Save to board", body)

    def test_a_board_that_will_not_answer_yet_retries_once(self):
        # It has two seconds to notice the flag on its next contact poll, so a
        # first load can legitimately be too early.
        client = self.build(FakeBoard(error="no answer"))
        body = client.get("/device").data
        self.assertIn(b"http-equiv=\"refresh\"", body)

    def test_the_retry_does_not_loop(self):
        client = self.build(FakeBoard(error="no answer"))
        body = client.get("/device?noretry=1").data
        self.assertNotIn(b"http-equiv=\"refresh\"", body)
        self.assertIn(b"no answer", body)

    def test_a_display_service_that_is_down_is_reported(self):
        down = dict(ABSENT, error="cannot reach the display service")
        client = self.build(FakeBoard(snapshot=down))
        self.assertIn(b"cannot reach the display service",
                      client.get("/device").data)


class TestSaving(DevicePageCase):
    def post(self, client, **form):
        return client.post("/device", data=form, follow_redirects=True)

    def test_a_valid_change_reaches_the_board(self):
        client = self.build(FakeBoard())
        self.post(client, nstart="23")
        self.assertEqual(len(self.board.writes), 1)
        addr, values, clears = self.board.writes[0]
        self.assertEqual(addr, "192.0.2.42")
        self.assertEqual(values, {"nstart": 23})

    def test_a_bad_value_sends_nothing_at_all(self):
        # Refused as a set, like the town labels: a save that wrote the good
        # fields and flashed about the bad one would read as "saved" and leave
        # the board half-configured.
        client = self.build(FakeBoard())
        body = self.post(client, nstart="99", nend="6").data
        self.assertEqual(self.board.writes, [])
        self.assertIn(b"Nothing was sent to the board", body)

    def test_saving_against_an_absent_board_explains_rather_than_hanging(self):
        client = self.build(FakeBoard(snapshot=dict(ABSENT)))
        body = self.post(client, nstart="23").data
        self.assertEqual(self.board.writes, [])
        self.assertIn(b"has not polled recently", body)

    def test_a_clear_is_passed_through(self):
        client = self.build(FakeBoard())
        self.post(client, clear="nduty")
        _, values, clears = self.board.writes[0]
        self.assertEqual(clears, ["nduty"])

    def test_the_restart_is_announced(self):
        client = self.build(FakeBoard())
        body = self.post(client, nstart="23").data
        self.assertIn(b"restarting", body)

    def test_a_board_error_on_write_is_flashed_not_raised(self):
        board = FakeBoard()
        client = self.build(board)
        board.error = "the board at 192.0.2.42 refused the write"
        body = self.post(client, nstart="23").data
        self.assertIn(b"refused the write", body)


if __name__ == "__main__":
    unittest.main()
