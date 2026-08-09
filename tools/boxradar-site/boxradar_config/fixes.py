"""Enroute fixes: the curated table, and importing more from the eAIP.

Every other reference the pickers offer comes from a downloadable dataset.
5-letter RNAV fixes do not — they are published only in the NATS eAIP ENR 4.4
"significant points" table, as a web page of DDMMSS.ssN/DDDMMSS.ssE rows. So
this is the one table that ships with the application and is extended by hand.

The import path is cheap because the eAIP's coordinate format is the same one
the YAIXM airspace source uses, and yaixm.parse_latlon already reads it. Paste
rows in, get fixes out; nothing here re-implements DMS parsing.

Two tiers, merged at read time:

  data/enroute_fixes.csv   ships with the application, seeded from location.h
  <state>/fixes.csv        whatever this site imported, written by the UI

A user row wins over a shipped row with the same ident, so a stale shipped
value can always be corrected without editing the installed tree.
"""

import csv
import pathlib
import re
from collections import namedtuple

from boxradar_site.geo import yaixm

Fix = namedtuple("Fix", "ident lat lon note source")

SHIPPED = pathlib.Path(__file__).resolve().parent / "data" / "enroute_fixes.csv"

# A published coordinate pair: DDMMSS[.sss]N DDDMMSS[.sss]E, which is what
# both the eAIP and YAIXM use. Kept loose about the separator because pasted
# table rows arrive with anything between the columns.
_PAIR = re.compile(r"(\d{6}(?:\.\d+)?\s*[NS])\s*[, \t]\s*(\d{7}(?:\.\d+)?\s*[EW])",
                   re.I)
_IDENT = re.compile(r"\b([A-Z]{2,5})\b")

MAX_IDENT = 7  # blob.MAX_NAME_CHARS; a longer label cannot be stored


def _read(path, source):
    out = []
    if not pathlib.Path(path).exists():
        return out
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#"):
                continue
            if len(row) < 3:
                continue
            try:
                out.append(Fix(row[0].strip().upper(), float(row[1]),
                               float(row[2]),
                               row[3].strip() if len(row) > 3 else "", source))
            except ValueError:
                continue  # a malformed row costs one fix, not the file
    return out


def load(user_path=None):
    """Shipped fixes overlaid with this site's imports, by ident."""
    merged = {}
    for fix in _read(SHIPPED, "shipped"):
        merged[fix.ident] = fix
    if user_path:
        for fix in _read(user_path, "imported"):
            merged[fix.ident] = fix
    return sorted(merged.values(), key=lambda f: f.ident)


def save(user_path, fixes):
    path = pathlib.Path(user_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted({f.ident: f for f in fixes}.values(), key=lambda f: f.ident)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["# ident", "lat", "lon", "note"])
        for fix in rows:
            writer.writerow([fix.ident, f"{fix.lat:.5f}", f"{fix.lon:.5f}",
                             fix.note])


def parse_eaip(text):
    """(fixes, problems) from pasted eAIP ENR 4.4 rows.

    Deliberately line-oriented and forgiving about layout — a table copied out
    of a browser arrives with whatever whitespace the page had. A line is used
    only if it yields both an identifier and a full coordinate pair, and every
    line that does not is reported rather than dropped, because a paste that
    silently produced three fixes out of forty would look like it worked.
    """
    out, problems = [], []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pair = _PAIR.search(stripped)
        if pair is None:
            problems.append(f"line {number}: no coordinate pair — {stripped[:60]}")
            continue
        # The identifier is looked for BEFORE the coordinates, so the N/S/E/W
        # hemisphere letters cannot be mistaken for one.
        head = stripped[:pair.start()]
        ident_match = _IDENT.search(head.upper())
        if ident_match is None:
            problems.append(f"line {number}: no identifier before the "
                            f"coordinates — {stripped[:60]}")
            continue
        ident = ident_match.group(1)
        if len(ident) > MAX_IDENT:
            problems.append(f"line {number}: {ident} is longer than "
                            f"{MAX_IDENT} characters")
            continue
        try:
            lat, lon = yaixm.parse_latlon(
                f"{pair.group(1).replace(' ', '')} "
                f"{pair.group(2).replace(' ', '')}")
        except ValueError as e:
            problems.append(f"line {number}: {e}")
            continue
        out.append(Fix(ident, lat, lon, "imported from eAIP", "imported"))
    return out, problems
