"""ICAO type designator to the name a person recognises.

`PC12` is a Pilatus PC-12, and the board has no way to know that. It carries
the designator already — `char type[5]` in aircraft.h, straight off the feed —
so this is only the name, and the name is far too big to live on the board:
2,821 entries, 112KB, against a firmware at 59% flash and ~80KB of free heap.
It lives here and the board asks.

**The data is already on the Pi.** tar1090-db ships it, so there is no new
download, no new dependency and nothing to keep in sync:

    /usr/local/share/tar1090/git-db/db/icao_aircraft_types2.js

Two traps in that path, both of which produce a working lookup that silently
never finds anything:

1. The DEPLOYED copy lives under `html/db-<hash>/`, and that hash changes on
   every tar1090-db update. This uses the `git-db` checkout, whose path is
   stable, because a lookup that works until the next update is worse than one
   that never worked.
2. There is a sibling file one character shorter — `icao_aircraft_types.js`,
   no `2` — with the same keys, the same size order, and NO names in it:
   `{"desc": "L1T", "wtc": "L"}` against this file's `["PILATUS PC-12", "L1T",
   "L"]`. Loading it would yield a table of the right length that resolves
   nothing. `_names_from()` checks the value SHAPE rather than trusting the
   filename, so picking the wrong one fails loudly at load instead of quietly
   at every lookup.

Despite the `.js` extension the file is gzip, and despite the gzip it is JSON.

**Nothing here raises**, on the same principle as config.py: a missing or
unreadable database costs the type name and nothing else. The board falls back
to showing the designator it already had, which is exactly what it shows today.

Names are served as they are stored — `ALLCAPS manufacturer` plus
`Mixed Case model`. Title-casing them would have to guess at `EC-135/635`,
`AW-139` and `PA-28-140/150/160/180`, and mangling a designator's name is
worse than shouting it.
"""

import gzip
import json
import os
import sys

DEFAULT_PATH = "/usr/local/share/tar1090/git-db/db/icao_aircraft_types2.js"


class TypeNames:
    """Designator to name. Empty and absent are the same answer."""

    def __init__(self, names=None, source=None):
        self.names = names or {}
        self.source = source

    def __len__(self):
        return len(self.names)

    def name_for(self, designator):
        """The full name, or None.

        None covers three cases the caller cannot usefully tell apart: the
        designator is not in the table, the table is empty because the file was
        missing, and the entry exists with an empty name — `GLID` is stored as
        `["", "L0-", "-"]`. All three mean "show the designator on its own".
        """
        if not designator:
            return None
        return self.names.get(str(designator).strip().upper()) or None


def _names_from(raw):
    """{designator: name} out of the parsed file, or None if it is the wrong one.

    Returning None rather than an empty dict matters: empty is a legitimate
    answer from a valid-but-unhelpful file, while None means "this is not the
    file you think it is" and deserves a different log line.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    out, shaped = {}, 0
    for designator, entry in raw.items():
        # The names-less sibling stores dicts here. One well-formed entry is
        # enough to prove the file's shape; anything malformed is skipped
        # rather than failing the whole table, so one bad row cannot cost every
        # other aircraft its name.
        if not isinstance(entry, (list, tuple)) or not entry:
            continue
        shaped += 1
        name = entry[0]
        if isinstance(name, str) and name.strip():
            out[str(designator).strip().upper()] = name.strip()
    if not shaped:
        return None
    return out


def load(path=None):
    """Read the database. Never raises; returns an empty table on any problem."""
    path = path or os.environ.get("BOXRADAR_TYPES_DB") or DEFAULT_PATH
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        print(f"aircraft types: no database at {path}, "
              f"type names disabled", file=sys.stderr, flush=True)
        return TypeNames(source=path)
    except OSError as e:
        # Includes gzip.BadGzipFile: the file exists but is not what we expect.
        print(f"aircraft types: cannot read {path}: {e}",
              file=sys.stderr, flush=True)
        return TypeNames(source=path)
    except (ValueError, UnicodeDecodeError) as e:
        print(f"aircraft types: {path} is not JSON: {e}",
              file=sys.stderr, flush=True)
        return TypeNames(source=path)

    names = _names_from(raw)
    if names is None:
        print(f"aircraft types: {path} has no names in it — this looks like "
              f"icao_aircraft_types.js rather than icao_aircraft_types2.js",
              file=sys.stderr, flush=True)
        return TypeNames(source=path)
    print(f"aircraft types: {len(names)} designators from {path}",
          flush=True)
    return TypeNames(names, source=path)
