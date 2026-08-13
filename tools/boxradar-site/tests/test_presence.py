"""Board presence and the config-wake window.

The display service is the only thing on the Pi that hears from the board, and
it hears from it every couple of seconds. That makes it the natural place to
answer two questions the configuration UI cannot answer for itself: where is
the board, and is it still there.

A fake clock throughout. The real one is time.monotonic(), for the reason
cache.py documents: a Pi has no RTC, so the wall clock steps when NTP catches
up and any window measured against it would either expire instantly or never.
"""

import unittest

from boxradar_site import presence


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class PresenceTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.presence = presence.Presence(clock=self.clock)

    def test_nothing_seen_yet(self):
        snap = self.presence.snapshot()
        self.assertIsNone(snap["addr"])
        self.assertIsNone(snap["age_s"])
        self.assertFalse(snap["fresh"])

    def test_only_board_shaped_polls_count(self):
        """A curl or a browser hitting /contacts is not the display.

        Found live: diagnostic requests from the home server were recorded as the
        board, so /board reported the wrong address and the Device page would
        have offered to configure a workstation. The board is identified by
        HTTP/1.0, which net_task.cpp sets deliberately (useHTTP10) and which
        no browser or curl sends by default.
        """
        self.presence.saw("192.0.2.248", board_shaped=False)
        self.assertIsNone(self.presence.snapshot()["addr"])

    def test_a_later_non_board_request_does_not_overwrite_the_board(self):
        self.presence.saw("192.0.2.20", board_shaped=True)
        self.clock.advance(1)
        self.presence.saw("192.0.2.248", board_shaped=False)
        snap = self.presence.snapshot()
        self.assertEqual(snap["addr"], "192.0.2.20")
        # ...and it does not refresh the age either, or an unplugged board
        # would look alive for as long as anything else polled.
        self.assertEqual(snap["age_s"], 1)

    def test_records_the_address_it_was_last_polled_from(self):
        self.presence.saw("192.0.2.42", board_shaped=True)
        snap = self.presence.snapshot()
        self.assertEqual(snap["addr"], "192.0.2.42")
        self.assertEqual(snap["age_s"], 0.0)
        self.assertTrue(snap["fresh"])

    def test_a_new_address_replaces_the_old_one(self):
        # A DHCP lease change must not leave the UI pushing at an address the
        # board no longer has. Last poll wins, always.
        self.presence.saw("192.0.2.42", board_shaped=True)
        self.clock.advance(60)
        self.presence.saw("192.0.2.77", board_shaped=True)
        self.assertEqual(self.presence.snapshot()["addr"], "192.0.2.77")

    def test_goes_stale_once_the_polls_stop(self):
        self.presence.saw("192.0.2.42", board_shaped=True)
        self.clock.advance(presence.FRESH_S + 0.1)
        snap = self.presence.snapshot()
        self.assertFalse(snap["fresh"])
        # The address is still reported. It is the last one known to be right,
        # and showing it beside "not seen for 5m" is more use than a blank.
        self.assertEqual(snap["addr"], "192.0.2.42")
        self.assertAlmostEqual(snap["age_s"], presence.FRESH_S + 0.1, places=3)


class WakeTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.presence = presence.Presence(clock=self.clock)

    def test_not_wanted_by_default(self):
        # The board must never be told to open a server nobody asked for.
        self.assertFalse(self.presence.wants_config())

    def test_wake_asks_for_it(self):
        self.presence.wake()
        self.assertTrue(self.presence.wants_config())

    def test_the_ask_persists_across_several_polls(self):
        # One response can be lost. The board polls at 2s, so a window of
        # WAKE_WINDOW_S gives it a dozen or so chances to hear.
        self.presence.wake()
        for _ in range(5):
            self.clock.advance(2)
            self.assertTrue(self.presence.wants_config())

    def test_the_ask_expires(self):
        # Bounded on purpose. A flag that stayed set would have the board
        # reopening its config server forever after one visit to the page.
        self.presence.wake()
        self.clock.advance(presence.WAKE_WINDOW_S + 0.1)
        self.assertFalse(self.presence.wants_config())

    def test_waking_again_extends_the_window(self):
        self.presence.wake()
        self.clock.advance(presence.WAKE_WINDOW_S - 1)
        self.presence.wake()
        self.clock.advance(2)
        self.assertTrue(self.presence.wants_config())

    def test_snapshot_reports_the_window(self):
        self.assertFalse(self.presence.snapshot()["waking"])
        self.presence.wake()
        self.assertTrue(self.presence.snapshot()["waking"])


class GeoReloadTest(unittest.TestCase):
    """Publishing rings a bell so the board picks the map up in seconds.

    A separate window from the config wake, not a shared one: they are asked
    for by different things at different times, and a publish must not open
    the board's settings server as a side effect.
    """

    def setUp(self):
        self.clock = FakeClock()
        self.presence = presence.Presence(clock=self.clock)

    def test_not_wanted_by_default(self):
        self.assertFalse(self.presence.wants_geo())

    def test_reload_asks_for_it(self):
        self.presence.reload_geo()
        self.assertTrue(self.presence.wants_geo())

    def test_it_expires(self):
        self.presence.reload_geo()
        self.clock.advance(presence.WAKE_WINDOW_S + 0.1)
        self.assertFalse(self.presence.wants_geo())

    def test_the_two_signals_are_independent(self):
        self.presence.reload_geo()
        self.assertFalse(self.presence.wants_config(),
                         "publishing must not open the settings server")
        self.presence.wake()
        self.assertTrue(self.presence.wants_geo())
        self.assertTrue(self.presence.wants_config())

    def test_snapshot_reports_it(self):
        self.assertFalse(self.presence.snapshot()["reloading"])
        self.presence.reload_geo()
        self.assertTrue(self.presence.snapshot()["reloading"])


if __name__ == "__main__":
    unittest.main()
