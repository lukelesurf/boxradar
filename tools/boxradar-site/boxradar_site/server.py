"""HTTP routes for the site application.

    GET /metar/EGSS         one station
    GET /metar/EGSS,EGGW    several, in one upstream call
    GET /healthz            liveness

The /metar response envelope is fixed by lib/radarcore/metar.cpp and must not
change shape: it iterates root["stations"] matching on "id". Extra keys are
safe — ArduinoJson ignores what it does not read.
"""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION
from .metar import envelope, normalise

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


def _make_handler(cache, cfg):
    class Handler(BaseHTTPRequestHandler):
        # Keep-alive matters: the board polls one URL every 60s over the LAN,
        # and HTTP/1.0 would make every poll a fresh connection.
        protocol_version = "HTTP/1.1"
        server_version = f"boxradar-site/{VERSION}"

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                self._json(200, {"ok": True, "version": VERSION})
                return
            if path.startswith("/metar/"):
                self._metar(path[len("/metar/"):])
                return
            self._json(404, {"error": "not found"})

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

        def _json(self, status, payload):
            body = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Default goes to stderr with a timestamp systemd already adds.
            print(f"{self.address_string()} {fmt % args}", flush=True)

    return Handler


def make_server(addr, cache, cfg):
    """Threading so a slow upstream fetch cannot block an unrelated request.

    Pass port 0 to let the OS choose — used by the tests.
    """
    return ThreadingHTTPServer(addr, _make_handler(cache, cfg))
