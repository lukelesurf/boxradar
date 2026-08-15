"""ICAO airline code to the operator behind it, and the name on the radio.

`RYR4ZQ` is Ryanair, and `RRR7241` is the RAF — the board carries the callsign
already, straight off the feed, so this is only the lookup. 6,310 operators at
407KB is far past a firmware at 59% flash with ~80KB of free heap, so it lives
here and the board asks. Same shape and same reasoning as aircraft_types.py.

**The data is already on the Pi.** tar1090-db ships it beside the type table,
so there is no new download, no new dependency and nothing to keep in sync:

    /usr/local/share/tar1090/git-db/db/operators.js

Same two traps as the type table, and for the same reasons. The DEPLOYED copy
sits under `html/db-<hash>/` and that hash changes on every tar1090-db update,
so this uses the stable `git-db` path. And `_table_from()` checks the value
SHAPE rather than trusting the filename, because a file of the right length
holding the wrong thing yields a lookup that resolves nothing and says nothing.

Despite the `.js` extension the file is gzip, and despite the gzip it is JSON.

Each entry carries three fields and this serves two of them:

    "BAW": {"n": "British Airways", "c": "United Kingdom", "r": "SPEEDBIRD"}

`n` is who they are; `r` is what you hear on the air, and for some operators it
is the more recognisable half — `RRR` is "RAF HQSTC" on paper and ASCOT in the
air, `GTI` is Atlas Air and GIANT, `NPT` is West Atlantic and NEPTUNE. Both go
on the wire and the panel decides what fits. `c` is dropped: there is no room
for it and no display asking.

**Nothing here raises**, on the same principle as config.py: a missing or
unreadable database costs the operator name and nothing else. The panel falls
back to showing the callsign on its own, which is what it shows today.
"""

import gzip
import json
import os
import sys

DEFAULT_PATH = "/usr/local/share/tar1090/git-db/db/operators.js"


class Operators:
    """Airline code to (name, radio callsign). Empty and absent are the same."""

    def __init__(self, table=None, source=None):
        self.table = table or {}
        self.source = source

    def __len__(self):
        return len(self.table)

    def lookup(self, code):
        """(name, radio) for one code, or None.

        None covers the cases the caller cannot usefully tell apart: the code
        is not in the table, the table is empty because the file was missing,
        and the entry exists with no name. All three mean "show the callsign on
        its own". An entry with a name but no radio callsign is NOT None —
        that is a partial answer worth having, and `radio` comes back empty.
        """
        if not code:
            return None
        entry = self.table.get(str(code).strip().upper())
        if not isinstance(entry, dict):
            return None
        name = (entry.get("n") or "").strip()
        if not name:
            return None
        return name, (entry.get("r") or "").strip()


def _table_from(payload):
    """The operator map out of a parsed file, or {} if it is the wrong shape.

    Checked on VALUE shape, not on the filename: an entry has to be a dict
    carrying an `n`. A file of plausible size and plausible keys that fails
    this would otherwise install cleanly and resolve nothing, which is the
    failure mode worth refusing loudly — the same argument as the sibling
    `icao_aircraft_types.js` trap next door.
    """
    if not isinstance(payload, dict) or not payload:
        return {}
    checked = 0
    for value in payload.values():
        if not isinstance(value, dict) or "n" not in value:
            return {}
        checked += 1
        if checked >= 20:  # enough to tell the file apart; not a full scan
            break
    return payload


def load(path=None):
    """Read the table. Never raises — an absent database is not an outage."""
    path = path or os.environ.get("BOXRADAR_OPERATORS", DEFAULT_PATH)
    try:
        with gzip.open(path, "rb") as f:
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        # Not gzip, or not there at all. Try it as plain text before giving
        # up, so a decompressed copy in a test fixture works the same way.
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError as e:
            print(f"operators: no database at {path} ({e})", file=sys.stderr)
            return Operators()
    start = raw.find("{")
    if start < 0:
        print(f"operators: {path} holds no JSON object", file=sys.stderr)
        return Operators()
    try:
        payload = json.loads(raw[start:])
    except ValueError as e:
        print(f"operators: {path} did not parse ({e})", file=sys.stderr)
        return Operators()
    table = _table_from(payload)
    if not table:
        print(f"operators: {path} is not an operator table", file=sys.stderr)
        return Operators()
    print(f"operators: {len(table)} codes from {path}")
    return Operators(table, source=path)
