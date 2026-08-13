"""Turning dataset records into selection entries, and back again.

The "back again" is the awkward half. The selection stores exactly what the
blob needs and nothing else — a runway is four bare floats, a town is a short
label and a position — so on the next page load there is no key linking a
stored entry to the dataset row it came from. The tick boxes have to be
re-derived by matching coordinates.

That is a deliberate trade rather than an oversight. The alternative is storing
a dataset identifier alongside each entry, which introduces a second source of
truth that can disagree with the coordinates beside it, and the recorded rule
for this project is that nothing derived goes on the wire or in the file.
Matching on position cannot disagree with itself.

TOLERANCE_DEG is about 11 metres, which is far below the spacing of any two
distinct runway thresholds or town centroids and far above the float noise of
a JSON round trip.
"""

import math
from collections import namedtuple

# One row on the /fixes page. Navaids and enroute fixes come from completely
# different sources — a downloadable CSV and a hand-curated table — but they
# are the same thing to the person picking, so the page shows one list and
# `source` says where each row came from.
Candidate = namedtuple("Candidate", "ident name kind lat lon source")

TOLERANCE_DEG = 1e-4

NM_PER_DEG_LAT = 60.0

# blob.MAX_NAME_CHARS. Enforced here so a label that cannot be stored is
# refused at the form rather than at publish time, when it would abort a build
# the user had already committed to.
MAX_LABEL = 7


def _close(a, b):
    return abs(a - b) <= TOLERANCE_DEG


def _same_point(lat0, lon0, lat1, lon1):
    return _close(lat0, lat1) and _close(lon0, lon1)


def runway_key(record):
    return f"{record.airport} {record.ident}"


def selected_airfields(sel):
    """The ICAOs currently in the selection."""
    return {str(name).upper() for name, _, _ in sel.airfields}


def selected_runways(sel, records):
    """Keys of dataset runways whose axis is already stored.

    An axis may be stored either way round — nothing in the format fixes which
    threshold comes first — so both orientations count as a match.
    """
    keys = set()
    for lat0, lon0, lat1, lon1 in sel.runways:
        for record in records:
            forward = (_same_point(lat0, lon0, record.lat0, record.lon0)
                       and _same_point(lat1, lon1, record.lat1, record.lon1))
            reverse = (_same_point(lat0, lon0, record.lat1, record.lon1)
                       and _same_point(lat1, lon1, record.lat0, record.lon0))
            if forward or reverse:
                keys.add(runway_key(record))
                break
    return keys


def selected_fixes(sel):
    return {str(name).upper() for name, _, _ in sel.waypoints}


def selected_towns(sel, records):
    """uids of dataset towns already stored, matched on position.

    Not on name: the stored label is a hand-chosen abbreviation (STVG for
    Stevenage), so it deliberately does not match the dataset's name.
    """
    uids = set()
    for _, lat, lon in sel.towns:
        for record in records:
            if _same_point(lat, lon, record.lat, record.lon):
                uids.add(record.uid)
                break
    return uids


def town_labels(sel, records):
    """{uid: stored label} so the form can show what was chosen before."""
    labels = {}
    for name, lat, lon in sel.towns:
        for record in records:
            if _same_point(lat, lon, record.lat, record.lon):
                labels[record.uid] = str(name)
                break
    return labels


def default_label(name):
    """A starting abbreviation for a town the user has just picked.

    Only ever a suggestion. Stevenage is STVG in location.h, which no rule
    would produce — the point is to give the box a sensible value rather than
    to be right.
    """
    cleaned = "".join(c for c in str(name).upper() if c.isalnum())
    return cleaned[:4] or "TOWN"


def check_label(label):
    """None if the label can be stored, else why not."""
    text = str(label).strip()
    if not text:
        return "a label is required — it is what the marker is captioned with"
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError:
        return f"{text!r} has non-ASCII characters, which the blob cannot store"
    if len(encoded) > MAX_LABEL:
        return (f"{text!r} is {len(encoded)} characters, limit is {MAX_LABEL} "
                f"— every character is 6px against the datablocks")
    return None


def distance_nm(home_lat, home_lon, lat, lon):
    d_lat = (lat - home_lat) * NM_PER_DEG_LAT
    d_lon = ((lon - home_lon) * NM_PER_DEG_LAT
             * math.cos(math.radians(home_lat)))
    return math.hypot(d_lat, d_lon)


def bearing_deg(home_lat, home_lon, lat, lon):
    d_lat = (lat - home_lat) * NM_PER_DEG_LAT
    d_lon = ((lon - home_lon) * NM_PER_DEG_LAT
             * math.cos(math.radians(home_lat)))
    return (math.degrees(math.atan2(d_lon, d_lat)) + 360.0) % 360.0


COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(bearing):
    return COMPASS[int((bearing + 11.25) % 360 / 22.5)]


def by_distance(records, home_lat, home_lon):
    """Nearest first.

    Every picker orders this way now. The lists are answers to "what is near
    me that I would recognise", and the datasets' own orders — airport class,
    ident, population — all bury the nearest thing somewhere in the middle.

    Sorted here rather than in the template so it is computed once per record
    rather than once per cell, and so it can be tested without rendering.
    """
    return sorted(records,
                  key=lambda r: distance_nm(home_lat, home_lon, r.lat, r.lon))


def merge_selected(records, extras, key):
    """`records` plus any of `extras` it does not already contain.

    Every picker has a coarse gate the browser cannot do for it — the airfield
    class toggle, the town population floor — and those gates used to hide
    things that were already selected. Because a save rebuilds the selection
    from exactly what the form contained, a hidden-but-selected item was
    silently dropped by doing nothing more than visiting the page and pressing
    Save. Whatever is selected is therefore always rendered, gate or no gate.
    """
    seen = {key(r) for r in records}
    return list(records) + [e for e in extras if key(e) not in seen]
