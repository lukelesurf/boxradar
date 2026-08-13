"""HTTP routes for the site application.

    GET  /metar/EGSS         one station
    GET  /metar/EGSS,EGGW    several, in one upstream call
    GET  /contacts?lat=&lon=&n=   the binary traffic feed
    GET  /board              where the board is and when it last polled
    POST /board/wake         ask it to open its config server
    GET  /healthz            liveness

The /metar response envelope is fixed by lib/radarcore/metar.cpp and must not
change shape: it iterates root["stations"] matching on "id". Extra keys are
safe — ArduinoJson ignores what it does not read.

/contacts is a fixed-size binary format, specified in
docs/superpowers/specs/2026-08-08-contact-feed.md, and is the display's primary
feed at 1Hz. Its shape is fixed by the board's reader in the same way.

The config-wake signal rides on a /contacts RESPONSE HEADER rather than in that
payload, and the reason is the format's rigidity. Its header is <4sHHHH with no
reserved field, so a flag byte would have to bump CONTACT_VERSION — and
contact_feed.h rejects an unknown version outright, which would blank the scope
until firmware and Pi were updated together. An unrecognised response header is
ignored by every HTTP client ever written, so a Pi updated ahead of its board
keeps working exactly as before.
"""

import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, contacts, feed, presence
from .metar import envelope, normalise

# Set on a /contacts response when the configuration UI has asked the board to
# open its settings server. Read by net_task.cpp, which collects exactly this
# one header name.
CONFIG_HEADER = "X-Boxradar-Config"

# ICAO location indicators are four letters. Validated rather than trusted:
# this is an unauthenticated LAN service and the value is interpolated into an
# outbound URL, so a permissive parser here would be an open relay with extra
# steps. The cap bounds a single upstream request.
MAX_IDS = 8
_ICAO_RE = re.compile(r"^[A-Z]{4}$")


def parse_ids(segment):
    """Uppercased ICAO list, or None if the segment is not acceptable."""
    if not segment:
        return None
    parts = segment.upper().split(",")
    # Length is checked on the RAW list, before dedup and before validation,
    # so an oversized request is rejected without being processed. Checking
    # after dedup would have let any number of repeats through, since they
    # collapse to one.
    if len(parts) > MAX_IDS:
        return None
    seen, out = set(), []
    for part in parts:
        if not _ICAO_RE.match(part):
            return None
        if part not in seen:
            seen.add(part)
            out.append(part)
    return out or None


# The board asks for what its static array can hold. The ceiling is here only
# so an unauthenticated LAN request cannot ask for an unbounded response; it is
# not a display policy and should stay well above any plausible MAX_AIRCRAFT.
MAX_CONTACTS = 128


def parse_site(query):
    """(lat, lon, n) from the query string, or None if it is not acceptable.

    Validated rather than trusted, as parse_ids is. Home is deliberately a
    request parameter and not service config: NVS on the board is the single
    authority for where "here" is, so the Pi holds no site position and two
    boards with different homes work off one service.
    """
    params = urllib.parse.parse_qs(query)
    try:
        lat = float(params["lat"][0])
        lon = float(params["lon"][0])
        n = int(params["n"][0])
    except (KeyError, IndexError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    # NaN fails every comparison above, so it is already rejected.
    if not (1 <= n <= MAX_CONTACTS):
        return None
    return lat, lon, n


def _make_handler(cache, cfg, fetch_feed, board):
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 for the sake of curl and the future web UI. The firmware is
        # NOT a beneficiary: net_task.cpp calls http.useHTTP10(true), so the
        # board sends 1.0 and gets a connection close per poll. That is
        # deliberate on its side — a 1.0 response has no chunked encoding, so
        # ArduinoJson can stream it straight off the socket.
        protocol_version = "HTTP/1.1"
        server_version = f"boxradar-site/{VERSION}"

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/healthz":
                self._json(200, {"ok": True, "version": VERSION})
                return
            if path.startswith("/metar/"):
                self._metar(path[len("/metar/"):])
                return
            if path == "/contacts":
                self._contacts(query)
                return
            if path == "/board":
                self._json(200, board.snapshot())
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            path, _, _ = self.path.partition("?")
            # Waking is a state change, so it is a POST and nothing else. As a
            # GET, a browser prefetching a link in the wizard could open the
            # board's config server without anyone pressing anything.
            if path == "/board/wake":
                board.wake()
                self._json(200, board.snapshot())
                return
            self._json(404, {"error": "not found"})

        def _contacts(self, query):
            site = parse_site(query)
            if site is None:
                self._json(400, {"error": "expected lat, lon and n=1.."
                                          f"{MAX_CONTACTS}"})
                return
            lat, lon, n = site
            # Recorded AFTER the request is validated but BEFORE the feed is
            # fetched. A malformed request did not come from the board, so it
            # must not move where we think the board is; a receiver outage is
            # a different failure from an absent board, and the UI has to be
            # able to tell them apart.
            board.saw(self.client_address[0])

            # Resolved once, here, and attached to whichever response goes
            # out. It belongs to the ROUTE, not to the success path: a
            # receiver that is down must not also cost you the ability to
            # configure the board, which is still polling and still reachable.
            wanted = board.wants_config()
            try:
                aircraft = fetch_feed()
            except feed.FeedError as e:
                # 503 rather than an empty 200: a header with no records is a
                # legitimate answer meaning "quiet sky", and the board would
                # believe it. Losing the receiver must not read as silence.
                self._json(503, {"error": str(e)}, config_wanted=wanted)
                return
            self._binary(200, contacts.build(aircraft, lat, lon, n),
                         config_wanted=wanted)

        def _metar(self, segment):
            ids = parse_ids(segment)
            if ids is None:
                self._json(400, {"error": "expected one to "
                                          f"{MAX_IDS} four-letter ICAO codes"})
                return
            observations, fetched_at, stale = cache.get(ids)
            if not observations:
                # Nothing cached and nothing upstream. 503 rather than an
                # empty 200: the board keeps its last good reading on a
                # non-200, and an empty stations array would look like a
                # successful publish with no weather in it.
                self._json(503, {"error": "no observation available"})
                return
            stations = [
                normalise(obs, cfg.runways_for(obs.get("icaoId") or ""),
                          cfg.calm_kt)
                for obs in observations
            ]
            self._json(200, envelope(stations, fetched_at, stale))

        def _binary(self, status, body, config_wanted=False):
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # Note what this does NOT do: touch `body`. The binary feed is a
            # specified format with a native test suite behind it, and the
            # signal stays entirely outside it.
            if config_wanted:
                self.send_header(CONFIG_HEADER, "1")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload, config_wanted=False):
            body = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if config_wanted:
                self.send_header(CONFIG_HEADER, "1")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Default goes to stderr with a timestamp systemd already adds.
            print(f"{self.address_string()} {fmt % args}", flush=True)

    return Handler


def make_server(addr, cache, cfg, fetch_feed=None, board=None):
    """Threading so a slow upstream fetch cannot block an unrelated request.

    Threading matters more now than it did for weather alone: /contacts is on
    the display's 1Hz path and must not queue behind a stalled METAR refresh.
    It is also why Presence takes a lock.

    Pass port 0 to let the OS choose, and `board` a Presence with a fake clock
    — both used by the tests.
    """
    return ThreadingHTTPServer(
        addr, _make_handler(cache, cfg, fetch_feed or feed.fetch,
                            board or presence.Presence()))
