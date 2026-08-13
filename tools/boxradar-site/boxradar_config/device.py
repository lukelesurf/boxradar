"""The board's optional settings, and the two hops needed to reach them.

Ten settings that previously required editing include/config.h and reflashing.
The board's own captive portal (src/portal.cpp) covers the other eight keys and
only appears when WiFi association fails, so these were unreachable in practice.

Nothing here holds state. The board's NVS remains the single authority for its
own configuration — the Pi reads it, offers a form, and pushes a diff back. See
site_config.h, which states in capitals that NVS is an overlay and must not be
inverted; a copy of these values kept on the Pi would be exactly that
inversion, so there isn't one.

  1. GET  http://127.0.0.1:8081/board      where the board is (display service)
  2. POST http://127.0.0.1:8081/board/wake ask it to open its config server
  3. GET  http://<board>/config            what it currently holds
  4. POST http://<board>/config            the diff, then it restarts

Step 1 is why no address is ever typed in: the board polls the display service
every two seconds, so the Pi has known where it is all along.

**Only differences are written.** Writing a key to NVS shadows its compiled
default permanently and silently — that is the trap portal.cpp:69-74 avoids
with placeholders instead of prefilled values. This page can afford to prefill,
because it re-reads the board and diffs before pushing, so pressing Save
without changing anything writes nothing at all.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

# The board is on a LAN and may be mid-reboot. Short, because a wizard that
# hangs for thirty seconds on an unplugged board is worse than one that says
# "not reachable" in three.
TIMEOUT_S = 4.0

# Mirrors lib/radarcore/device_config.h. tests/test_config_device_contract.py
# fails if the two drift, because a key that disagrees is not a compile error
# on either side — it is a setting that silently never applies.
DEFAULT_FEED_URL = "http://127.0.0.1:8081"


class Group:
    def __init__(self, key, label, note=""):
        self.key = key
        self.label = label
        self.note = note


GROUPS = [
    Group("feeds", "Optional feeds",
          "Weather and the map are extras. Turning one off stops the board "
          "asking for it at all — useful for telling a display problem from "
          "a feed problem without a reflash."),
    Group("traffic", "Traffic",
          "Which aircraft are worth a second look. The list is what the "
          "board considers ORDINARY, so anything not on it is highlighted."),
    Group("night", "Night blanking",
          "Set start and end to the same hour to turn night mode off "
          "entirely — that is how night_mode.cpp reads it."),
    Group("poll", "Poll intervals",
          "Faster polling costs the Pi, which is also running readsb and "
          "tar1090. Weather below 300s only re-serves the proxy's cache."),
    Group("clock", "Clock",
          "The board has no RTC, so night blanking depends entirely on NTP "
          "and on this timezone rule being right."),
]


class Field:
    def __init__(self, key, label, kind, group, low=None, high=None,
                 unit="", help="", wide=False, choices=None):
        self.key = key
        self.label = label
        self.kind = kind          # 'u' unsigned int, 's' string
        self.group = group
        self.low = low
        self.high = high
        self.unit = unit
        self.help = help
        self.wide = wide        # render a textarea rather than a one-line box
        self.choices = choices  # [(value, label)] for a select

    @property
    def range_text(self):
        if self.choices:
            return ""
        if self.kind == "s":
            return f"up to {self.high} characters"
        return f"{self.low}–{self.high}{(' ' + self.unit) if self.unit else ''}"


# Ranges are refused rather than clamped, on the same principle as
# cfgSetStr(): a value that did not stick must not look saved. Several of these
# bounds exist because the value below them is silently useless rather than
# obviously broken.
FIELDS = [
    Field("nstart", "Start hour", "u", "night", 0, 23,
          help="Local time, 24-hour."),
    Field("nend", "End hour", "u", "night", 0, 23,
          help="Equal to the start hour disables night mode."),
    Field("nwake", "Wake on tap", "u", "night", 5, 3600, unit="s",
          help="How long a tap holds the display up during night hours."),
    Field("nfade", "Fade", "u", "night", 0, 10000, unit="ms",
          help="0 snaps. At 3am a fade is the difference between glancing "
               "at it and being woken by it."),
    Field("nduty", "Clock brightness", "u", "night", 0, 255,
          help="Backlight duty for the overnight clock. 0 blanks the panel "
               "completely instead of showing a dim clock."),
    Field("poll", "Traffic", "u", "poll", 500, 60000, unit="ms",
          help="The scope's refresh. 2000 is the shipped value."),
    Field("mpoll", "Weather", "u", "poll", 10000, 3600000, unit="ms",
          help="The METAR proxy caches for 300s, so anything under that "
               "re-serves the same observation."),
    Field("gpoll", "Geography", "u", "poll", 60000, 86400000, unit="ms",
          help="The map changes when you publish, not on its own."),
    Field("metaron", "Weather", "u", "feeds", 0, 1,
          choices=[(1, "on"), (0, "off")],
          help="Stops the board polling the METAR proxy."),
    Field("geoon", "Map", "u", "feeds", 0, 1,
          choices=[(1, "on"), (0, "off")],
          help="Stops the board fetching geography. It keeps drawing "
               "whatever it already had."),
    # 255 is CFG_TYPES_LEN - 1. The built-in list is 134 characters, so there
    # is room to grow one without a reflash.
    Field("types", "Ordinary types", "s", "traffic", high=255, wide=True,
          help="Comma-separated ICAO designators the board should treat as "
               "everyday. Anything NOT listed is highlighted, so this is a "
               "list of what to ignore. The built-in one is the short-haul "
               "fleet that saturates a London feed — a box somewhere else "
               "wants a different list, and at a GA field it wants an "
               "entirely different kind of list."),
    # 33 and 48 are CFG_HOST_LEN and CFG_TZ_LEN from site_config_data.h, less
    # the terminator. cfgSetStr refuses an oversized value rather than
    # truncating it, so a longer string would be rejected on the board — this
    # catches it while the message can still name the field.
    Field("ntp", "NTP server", "s", "clock", high=32,
          help="Reached before WiFi is necessarily up; the SNTP client "
               "retries on its own."),
    Field("tz", "Timezone", "s", "clock", high=47,
          help="A POSIX TZ rule, not a fixed offset, so BST transitions "
               "keep working without an update."),
]

BY_KEY = {f.key: f for f in FIELDS}


def fields_in(group_key):
    return [f for f in FIELDS if f.group == group_key]


class BoardError(Exception):
    """The board could not be reached or did not answer usefully."""


def parse_form(form):
    """(values, clears, problems) from a submitted device form.

    Validation happens here rather than on the board so a bad value can be
    reported next to the field that caused it. The firmware validates again —
    this is a LAN service with no authentication and the board must not trust
    it — but by then the useful context is gone.
    """
    values, clears, problems = {}, [], []

    requested = form.getlist("clear") if hasattr(form, "getlist") else \
        ([form["clear"]] if "clear" in form else [])
    for key in requested:
        if key in BY_KEY:
            clears.append(key)

    for key, field in BY_KEY.items():
        raw = form.get(key)
        if raw is None:
            continue
        raw = raw.strip()
        if not raw:
            continue
        if key in clears:
            problems.append(f"{field.label} ({key}): asked to use the "
                            f"built-in default and to set a value at the "
                            f"same time.")
            continue
        if field.kind == "s":
            if len(raw) > field.high:
                problems.append(f"{field.label} ({key}): too long, "
                                f"{field.range_text}.")
                continue
            values[key] = raw
            continue
        try:
            number = int(raw)
        except ValueError:
            problems.append(f"{field.label} ({key}): "
                            f"expected a whole number, got {raw!r}.")
            continue
        if not (field.low <= number <= field.high):
            problems.append(f"{field.label} ({key}): {number} is outside "
                            f"{field.range_text}.")
            continue
        values[key] = number

    return values, clears, problems


class Client:
    """Talks to the display service on localhost and to the board on the LAN.

    Two hosts, one class, because the caller's question ("can I configure the
    board, and what does it hold") always needs both. The opener is injected so
    the tests never open a socket.
    """

    def __init__(self, feed_url=DEFAULT_FEED_URL, opener=None,
                 timeout=TIMEOUT_S):
        self.feed_url = feed_url.rstrip("/")
        self._open = opener or urllib.request.urlopen
        self.timeout = timeout

    # ------------------------------------------------------- display service

    def presence(self):
        """Where the board is. Never raises: a display service that is down is
        a thing the page has to render, not an error page."""
        try:
            return self._json("GET", f"{self.feed_url}/board")
        except Exception as e:
            return {"addr": None, "age_s": None, "fresh": False,
                    "waking": False,
                    "error": f"cannot reach the display service on "
                             f"{self.feed_url}: {e}"}

    def wake(self):
        """Ask the display service to flag the next few contact polls."""
        try:
            return self._json("POST", f"{self.feed_url}/board/wake", b"")
        except Exception as e:
            return {"addr": None, "fresh": False, "waking": False,
                    "error": f"cannot reach the display service: {e}"}

    def reload_geo(self):
        """Tell the board a new map is up. Best effort, by design.

        Returns None if the display service could not be reached. The blob is
        already written by the time this is called, so a failure here costs
        the board's geography poll interval and nothing else — it must never
        turn a publish that succeeded into one that looks failed.
        """
        try:
            return self._json("POST", f"{self.feed_url}/board/reload-geo", b"")
        except Exception:
            return None

    # ------------------------------------------------------------- the board

    def read(self, addr):
        """The board's whole answer: its settings and its health.

        Health is uptime, why it last reset, heap and RSSI. Without serial
        access that is the only view of the board's condition there is, and
        "it reset and I do not know why" is otherwise unanswerable — a
        brownout is the power supply, a panic is firmware, and a software
        restart is something asking it to.
        """
        try:
            payload = self._json("GET", f"http://{addr}/config")
        except Exception as e:
            raise BoardError(
                f"no answer from the board at {addr}: {e}. It opens its "
                f"settings server for a minute after being asked — if this "
                f"keeps failing, check it is still polling.") from e
        if not isinstance(payload.get("fields"), dict):
            raise BoardError(f"the board at {addr} answered with something "
                             f"unexpected: {payload!r}")
        return payload

    def read_config(self, addr):
        """What the board currently holds, per key, with its source."""
        return self.read(addr)["fields"]

    def restart(self, addr):
        """Ask the board to reboot.

        The workaround for a map that will not load: geoStoreRefresh needs a
        contiguous block the size of the whole blob while still holding the
        live one, and a heap that has been running for hours does not always
        have one. A fresh boot does.
        """
        try:
            return self._json("POST", f"http://{addr}/restart", b"")
        except Exception as e:
            raise BoardError(f"could not ask the board at {addr} to "
                             f"restart: {e}") from e

    def write_config(self, addr, values, clears):
        """Push only what differs, and report what was done.

        The diff is computed against a FRESH read rather than against whatever
        the form was rendered from. The page may have been open for a while,
        and pushing a value the board already holds would shadow its compiled
        default in NVS for nothing.
        """
        current = self.read_config(addr)

        changed = {}
        for key, value in values.items():
            entry = current.get(key) or {}
            if str(entry.get("value")) != str(value):
                changed[key] = value

        # Clearing is about WHERE a value comes from, not what it is: a key in
        # NVS holding the same number as the compiled default still shadows
        # it, so the comparison here is on source, never on value.
        to_clear = [k for k in clears
                    if (current.get(k) or {}).get("source") == "nvs"]

        if not changed and not to_clear:
            return {"written": 0, "cleared": 0, "restarting": False,
                    "problems": []}

        body = [(k, str(v)) for k, v in sorted(changed.items())]
        body += [("clear", k) for k in sorted(to_clear)]
        encoded = urllib.parse.urlencode(body).encode()
        try:
            result = self._json("POST", f"http://{addr}/config", encoded)
        except Exception as e:
            raise BoardError(f"the board at {addr} refused the write: {e}. "
                             f"Nothing was changed.") from e
        # Defaults only. The board's own counts win: it validates again and may
        # have refused something, in which case it also did not restart, and
        # reporting a restart that did not happen would have the page claiming
        # the scope was about to go dark for nothing.
        result.setdefault("written", len(changed))
        result.setdefault("cleared", len(to_clear))
        result.setdefault("restarting",
                          bool(result["written"] or result["cleared"]))
        return result

    # ---------------------------------------------------------------- plumbing

    def _json(self, method, url, data=None):
        request = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type",
                               "application/x-www-form-urlencoded")
        with self._open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode())
