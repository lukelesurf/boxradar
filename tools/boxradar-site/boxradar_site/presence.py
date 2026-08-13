"""Where the board is, and whether it has been asked to open its config server.

The display service is the only process on the Pi the board talks to, and it
talks to it about every two seconds (net_task.cpp polls /contacts at
POLL_INTERVAL_MS). That makes this the one place that already knows the board's
address without mDNS, a static lease, or anything typed into a form — the
address arrives on every request, thirty times a minute, for free.

The configuration UI runs in a different process and asks over HTTP
(GET /board, POST /board/wake). That is deliberate: tests/test_dependency_
boundary.py forbids the UI importing this package's service half, and the
README's "two systemd units, not one" rule exists so config-UI work cannot
restart the feed the display depends on. Shared memory would break both.

Everything here is measured on time.monotonic(), never the wall clock, for the
same reason cache.py is: a Pi has no RTC, so it boots with a wildly wrong time
and NTP then steps it. A wake window measured against a stepping clock would
either expire the instant it was opened or never expire at all.
"""

import threading
import time

# How long after a poll the board still counts as present. The board polls at
# 2s, so this is several missed polls rather than one unlucky one — but short
# enough that a board which has been unplugged stops looking configurable.
FRESH_S = 10.0

# How long a wake request keeps being advertised. Long enough for a dozen polls
# to carry it, so a single lost response costs nothing; short enough that one
# visit to the device page does not have the board reopening its server for the
# rest of the day.
WAKE_WINDOW_S = 30.0


class Presence:
    """Last-seen address and the wake window, both bounded in time.

    Thread-safe because the server is a ThreadingHTTPServer: /contacts and
    /board can be in flight at once, and the wake POST arrives on a third
    thread entirely.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._addr = None
        self._seen_at = None
        self._wake_until = None

    def saw(self, addr):
        """Record a poll from `addr`. Called on the 1Hz path — keep it cheap."""
        with self._lock:
            self._addr = addr
            self._seen_at = self._clock()

    def wake(self):
        """Ask the board to open its config server, for the next window."""
        with self._lock:
            self._wake_until = self._clock() + WAKE_WINDOW_S

    def wants_config(self):
        """True while the wake window is open."""
        with self._lock:
            return (self._wake_until is not None
                    and self._clock() < self._wake_until)

    def snapshot(self):
        """Everything the configuration UI needs, in one consistent read.

        Built under the lock so `addr` and `age_s` cannot come from either side
        of a concurrent poll and disagree about which board they describe.
        """
        with self._lock:
            now = self._clock()
            age = None if self._seen_at is None else now - self._seen_at
            return {
                "addr": self._addr,
                "age_s": age,
                # The address is reported even when stale. It is the last one
                # known to have been right, and "192.0.2.42, not seen for
                # 5m" tells you more than a blank field does.
                "fresh": age is not None and age <= FRESH_S,
                "waking": (self._wake_until is not None
                           and now < self._wake_until),
            }
