"""HTTP routes for the site application.

    GET  /metar/EGSS         one station
    GET  /metar/EGSS,EGGW    several, in one upstream call
    GET  /type/PC12          full name for an ICAO type designator
    GET  /type/PC12,A320     several, same cap as /metar
    GET  /contacts?lat=&lon=&n=   the binary traffic feed
    GET  /board              where the board is and when it last polled
    POST /board/wake         ask it to open its config server
    POST /board/reload-geo   ask it to refetch the map now
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

from . import VERSION, aircraft_types, contacts, feed, presence
from .metar import envelope, normalise

# Set on a /contacts response when the configuration UI has asked the board to
# open its settings server. Read by net_task.cpp, which collects exactly this
# one header name.
CONFIG_HEADER = "X-Boxradar-Config"

# Set on a /contacts response after a map is published, so the board refetches
# within a poll or two instead of waiting out its own geography interval. The
# poll stays as the fallback: a signal that is missed — board rebooting, off,
# off-wifi — is silent, and a map that never updates with nothing to say so is
# worse than one that updates late.
GEO_HEADER = "X-Boxradar-Geo"

# How the board is told apart from a browser, a curl or a health check asking
# for the same URL. net_task.cpp calls useHTTP10(true) deliberately — a 1.0
# response has no chunked encoding, so the body can be read against a known
# Content-Length — and nothing else on this LAN speaks 1.0 by default.
#
# It has to be told apart: recording every caller as the board reported the
# wrong address on /board and would have pointed the Device page's push at a
# workstation. That happened, live, from this project's own diagnostics.
# tests/test_config_device_contract.py fails if the firmware stops using 1.0.
BOARD_HTTP_VERSION = "HTTP/1.0"

# ICAO location indicators are four letters. Validated rather than trusted:
# this is an unauthenticated LAN service and the value is interpolated into an
# outbound URL, so a permissive parser here would be an open relay with extra
# steps. The cap bounds a single upstream request.
MAX_IDS = 8
_ICAO_RE = re.compile(r"^[A-Z]{4}$")

# Type designators are NOT four letters: `A1`, `PC12`, `B738`, `A002`, `EV97`.
# One to four alphanumerics, which is ICAO Doc 8643's rule. Validated for the
# same reason as the ICAO codes above — unauthenticated LAN service — though
# this one is only a dict key, never an outbound URL.
_TYPE_RE = re.compile(r"^[A-Z0-9]{1,4}$")


def parse_types(segment):
    """Uppercased designator list, or None if the segment is not acceptable.

    Same two-step as parse_ids, and the ordering matters for the same reason:
    the cap is applied to the RAW list, before dedup, so `PC12,PC12,...` five
    hundred times is refused rather than collapsing to one and sailing past it.
    """
    if not segment:
        return None
    parts = segment.upper().split(",")
    if len(parts) > MAX_IDS:
        return None
    seen, out = set(), []
    for part in parts:
        if not _TYPE_RE.match(part):
            return None
        if part not in seen:
            seen.add(part)
            out.append(part)
    return out or None


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


# Sentinel for "this request did not ask for a band". Distinct from the widest
# possible band because absent and 0-70000 should behave identically but be
# tellable apart in a log — and because a board flashed before this existed
# sends neither parameter and must keep working unchanged.
NO_BAND = (None, None)


def parse_band(query):
    """(alt_min, alt_max) in feet, NO_BAND if unasked, or None if malformed.

    Separate from parse_site because it is optional and that one is not: an
    older board sends lat/lon/n and nothing else, and must not start getting
    400s the day the Pi learns about altitude. Present-but-nonsense is still
    refused rather than ignored, on the same principle as the rest of this
    module — the board is trusted to be the authority on its own settings,
    not to be incapable of sending rubbish.
    """
    # keep_blank_values, unlike parse_site's default parse. Without it
    # `amax=` disappears from the dict entirely and reads as "not asked for",
    # so a request that plainly tried to set a ceiling would be answered with
    # an unfiltered feed and no complaint. Present-and-empty is malformed.
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    if "amin" not in params and "amax" not in params:
        return NO_BAND
    try:
        # Defaulted independently, so a request may send only one of them.
        low = int(params.get("amin", ["0"])[0])
        high = int(params.get("amax",
                              [str(contacts.ALT_BAND_CEILING_FT)])[0])
    except (IndexError, ValueError):
        return None
    ceiling = contacts.ALT_BAND_CEILING_FT
    if not (0 <= low <= ceiling) or not (0 <= high <= ceiling):
        return None
    return low, high


def parse_mlat(query):
    """Whether to include multilaterated positions, or None if malformed.

    Absent means include, so a board that predates the switch is unaffected —
    the same compatibility rule as the altitude band. Only "0" and "1" are
    accepted rather than any truthy string: the board sends one of exactly
    those two, and taking "false" or "no" as well would be inventing a wire
    format nothing writes.
    """
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    if "mlat" not in params:
        return True
    value = params["mlat"][0]
    if value not in ("0", "1"):
        return None
    return value == "1"


def _make_handler(cache, cfg, fetch_feed, board, types):
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
            if path.startswith("/type/"):
                self._types(path[len("/type/"):])
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
            if path == "/board/reload-geo":
                board.reload_geo()
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
            band = parse_band(query)
            if band is None:
                self._json(400, {"error": "amin and amax must be whole feet "
                                          f"in 0..{contacts.ALT_BAND_CEILING_FT}"})
                return
            alt_min, alt_max = band
            include_mlat = parse_mlat(query)
            if include_mlat is None:
                self._json(400, {"error": "mlat must be 0 or 1"})
                return
            # Recorded AFTER the request is validated but BEFORE the feed is
            # fetched. A malformed request did not come from the board, so it
            # must not move where we think the board is; a receiver outage is
            # a different failure from an absent board, and the UI has to be
            # able to tell them apart.
            board.saw(self.client_address[0],
                      board_shaped=self.request_version == BOARD_HTTP_VERSION)

            # Resolved once, here, and attached to whichever response goes
            # out. They belong to the ROUTE, not to the success path: a
            # receiver that is down must not also cost you the ability to
            # configure the board or to publish a map to it — it is still
            # polling and still reachable.
            wanted = board.wants_config()
            geo = board.wants_geo()
            try:
                aircraft = fetch_feed()
            except feed.FeedError as e:
                # 503 rather than an empty 200: a header with no records is a
                # legitimate answer meaning "quiet sky", and the board would
                # believe it. Losing the receiver must not read as silence.
                self._json(503, {"error": str(e)}, config_wanted=wanted,
                           geo_wanted=geo)
                return
            self._binary(200, contacts.build(aircraft, lat, lon, n,
                                             alt_min=alt_min,
                                             alt_max=alt_max,
                                             include_mlat=include_mlat),
                         config_wanted=wanted, geo_wanted=geo)

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

        def _types(self, segment):
            wanted = parse_types(segment)
            if wanted is None:
                self._json(400, {"error": "expected one to "
                                          f"{MAX_IDS} ICAO type designators"})
                return
            if not len(types):
                # No database at all — a service fault, and a 503 leaves the
                # board free to ask again later. An unknown designator is the
                # opposite case and must NOT come back as an error: see below.
                self._json(503, {"error": "no aircraft type database"})
                return
            # Every requested id is echoed, and `name` is present only when
            # there is one. That distinction is the whole contract: an id with
            # no name is a definitive answer the board can cache and stop
            # asking about, where a 404 or a 503 would have it retry forever
            # for a designator that is never going to resolve.
            out = []
            for designator in wanted:
                name = types.name_for(designator)
                entry = {"id": designator}
                if name:
                    entry["name"] = name
                out.append(entry)
            self._json(200, {"types": out})

        def _binary(self, status, body, config_wanted=False,
                    geo_wanted=False):
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            # Note what this does NOT do: touch `body`. The binary feed is a
            # specified format with a native test suite behind it, and both
            # signals stay entirely outside it.
            if config_wanted:
                self.send_header(CONFIG_HEADER, "1")
            if geo_wanted:
                self.send_header(GEO_HEADER, "1")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload, config_wanted=False,
                  geo_wanted=False):
            body = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if config_wanted:
                self.send_header(CONFIG_HEADER, "1")
            if geo_wanted:
                self.send_header(GEO_HEADER, "1")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Default goes to stderr with a timestamp systemd already adds.
            print(f"{self.address_string()} {fmt % args}", flush=True)

    return Handler


def make_server(addr, cache, cfg, fetch_feed=None, board=None, types=None):
    """Threading so a slow upstream fetch cannot block an unrelated request.

    Threading matters more now than it did for weather alone: /contacts is on
    the display's 1Hz path and must not queue behind a stalled METAR refresh.
    It is also why Presence takes a lock.

    Pass port 0 to let the OS choose, `board` a Presence with a fake clock, and
    `types` a TypeNames built from a literal dict — all used by the tests.

    `types` defaults to an EMPTY table rather than loading from disk. Reading a
    112KB database is a caller's decision, not a side effect of constructing a
    server: __main__ loads it once at startup, and a test that never mentions
    type names gets a server that cannot be slowed down or made
    environment-dependent by one.
    """
    return ThreadingHTTPServer(
        addr, _make_handler(cache, cfg, fetch_feed or feed.fetch,
                            board or presence.Presence(),
                            types if types is not None
                            else aircraft_types.TypeNames()))
