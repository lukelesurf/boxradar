"""The selection file the UI owns, and the edits it makes to it.

Phase 4 moves the selection from "a JSON file a human edits" to "state an
application writes", so this module holds the two properties that change
implies.

**Round-trip fidelity.** The airspace picker edits `airspace` and nothing else,
but it rewrites the whole file. Airfields, runway centrelines, fixes and towns
are curated by hand and are the expensive part of a site, so saving a tick must
carry them through untouched. That is what most of these tests are about.

**Atomic replacement.** `site.bin` is written into lighttpd's document root
while a board may be fetching it. A partial write would be served, and although
the blob's CRC would reject it, the board would then sit on its cache until the
next poll for no good reason. os.replace() is atomic within a filesystem, so a
reader sees either the old file or the new one.
"""

import json
import os
import pathlib
import re
import tempfile

from boxradar_site.geo import selection

# Trailing words that say what class of airspace a feature is rather than which
# place it belongs to. Stripped when deriving a group name, because the group
# already means "the airspace at this place" — STANSTED_CTR is generated from
# group STANSTED, so a group called STANSTED_CTR yields STANSTED_CTR_CTR.
CLASS_SUFFIXES = ("CTR", "CTA", "TMA", "TMZ", "ATZ", "RMZ", "FIR")

_NOT_IDENT = re.compile(r"[^A-Z0-9]+")


def write_atomic(path, data):
    """Replace path's contents in one step. Accepts str or bytes."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
    # Same directory, so os.replace() stays within one filesystem — across a
    # mount boundary it raises rather than falling back to a copy.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, mode) as f:
            f.write(data)
        os.replace(tmp, str(path))
    except BaseException:
        # Leaving a stray .tmp beside the real file would be mistaken for the
        # real file by anything globbing the directory.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def to_dict(sel):
    """A Selection as the JSON shape selection.load() reads back."""
    return {
        "home_lat": sel.home_lat,
        "home_lon": sel.home_lon,
        "reach_nm": sel.reach_nm,
        "airspace": [{"name": g.name, "primary": g.primary,
                      "envelope": list(g.envelope)} for g in sel.groups],
        # Lists, not tuples — json would render either, but load() compares
        # arity and these must come back the same shape they went out.
        "airfields": [list(p) for p in sel.airfields],
        "runways": [list(p) for p in sel.runways],
        "waypoints": [list(p) for p in sel.waypoints],
        "towns": [list(p) for p in sel.towns],
    }


def save(path, sel):
    write_atomic(path, json.dumps(to_dict(sel), indent=2) + "\n")


def load(path):
    """The stored selection, or None if there is not one yet."""
    if not pathlib.Path(path).exists():
        return None
    return selection.load(str(path))


def group_name_for(feature_name, taken=()):
    """A C-identifier-safe group name for a feature the user just ticked.

    The group name becomes a symbol in the generated header (<NAME>_CTR and
    <NAME>_ENV), so it has to be an identifier and it has to be unique —
    selection.load() rejects duplicates precisely because the symbols would
    collide.
    """
    words = str(feature_name).upper().split()
    while len(words) > 1 and words[-1] in CLASS_SUFFIXES:
        words.pop()
    base = _NOT_IDENT.sub("_", " ".join(words)).strip("_") or "AIRSPACE"
    if base[0].isdigit():
        base = "A" + base
    name, n = base, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1
    return name


def apply_airspace(sel, ticked):
    """A copy of sel whose airspace is exactly the ticked feature names.

    Existing groups are preserved wherever they still apply, because envelope
    grouping is a hand-made judgement the picker cannot reconstruct: it is the
    difference between drawing a CTR alone and drawing it merged with its CTA.
    Unticking a primary therefore promotes its still-ticked envelope members to
    groups of their own rather than dropping them — the tick means "draw this",
    and honouring it somewhere is better than silently discarding it.
    """
    ticked = list(dict.fromkeys(ticked))  # de-duplicate, keep order
    wanted = set(ticked)
    groups, covered, taken = [], set(), set()

    for g in sel.groups:
        if g.primary not in wanted:
            continue
        envelope = [e for e in g.envelope if e in wanted]
        groups.append(selection.Group(g.name, g.primary, envelope))
        taken.add(g.name)
        covered.add(g.primary)
        covered.update(envelope)

    for name in ticked:
        if name in covered:
            continue
        group = selection.Group(group_name_for(name, taken), name)
        taken.add(group.name)
        groups.append(group)

    return selection.Selection(sel.home_lat, sel.home_lon, sel.reach_nm,
                               groups, airfields=sel.airfields,
                               runways=sel.runways, waypoints=sel.waypoints,
                               towns=sel.towns)


def with_points(sel, airfields=None, runways=None, waypoints=None,
                towns=None):
    """A copy of sel with some point sections replaced. None means keep.

    One function rather than four so that "the page I was not on does not lose
    its data" is a property of the code rather than of every caller
    remembering to pass the other three through.
    """
    return selection.Selection(
        sel.home_lat, sel.home_lon, sel.reach_nm, sel.groups,
        airfields=sel.airfields if airfields is None else list(airfields),
        runways=sel.runways if runways is None else list(runways),
        waypoints=sel.waypoints if waypoints is None else list(waypoints),
        towns=sel.towns if towns is None else list(towns))


def with_site(sel, home_lat, home_lon, reach_nm):
    """A copy of sel with a different home. Everything else carries over."""
    return selection.Selection(home_lat, home_lon, reach_nm, sel.groups,
                               airfields=sel.airfields, runways=sel.runways,
                               waypoints=sel.waypoints, towns=sel.towns)


def empty(home_lat, home_lon, reach_nm=selection.DEFAULT_REACH_NM):
    return selection.Selection(home_lat, home_lon, reach_nm, [])
