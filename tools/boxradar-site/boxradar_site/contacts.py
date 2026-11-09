"""Turn the receiver's aircraft.json into the board's binary contact feed.

The board used to deserialise the whole feed and only then apply MAX_AIRCRAFT,
which made its heap low-water mark a function of how many aircraft happened to
be airborne. Filtering, range-sorting and capping happen here instead, and what
goes on the wire is a fixed-size record the board can cast in place.

Pure functions, no I/O — the fetch lives in feed.py so these stay testable
without a network. Filtering is field-for-field parity with
lib/radarcore/parse.cpp: this is a transport change, not a behaviour change.

The wire format is specified in docs/design/specs/2026-08-08-contact-feed.md.
Nothing derived is transmitted: no range, no bearing, no screen position. The
Pi needs home to decide *which* contacts to send, but the board projects them
itself, so a home disagreement can never silently move traffic on the display.
"""

import math
import struct
from typing import NamedTuple

MAGIC = b"BXAC"
VERSION = 1

# magic, version, record length, count, total-before-cap
_HEADER = "<4sHHHH"
# hex, lat, lon, callsign, type, squawk, alt/25, gs, track, vrate/64,
# seen, rssi*2, flags, pad. Every field lands on its natural alignment so the
# board can cast the receive buffer to const Contact* without copying.
_RECORD = "<Iii8s4s4shHHhBbBB"
HEADER_LEN = struct.calcsize(_HEADER)  # 12
RECORD_LEN = struct.calcsize(_RECORD)  # 40

# Mirrors lib/radarcore/aircraft.h.
SEEN_DROP_S = 60.0
NM_PER_DEG_LAT = 60.0

# Saturation limits, derived from the field widths so they cannot drift from
# the format. A wrapped value would be a plausible-looking lie — an aircraft
# at FL350 reading as a descent through the sea floor — where a saturated one
# is merely wrong at the edge of a range nothing real occupies.
CALLSIGN_LEN, TYPE_LEN, SQUAWK_LEN = 8, 4, 4
ALT_STEP_FT, VERT_RATE_STEP_FPM = 25, 64
MAX_ALT_FT = 32767 * ALT_STEP_FT
MIN_ALT_FT = -32768 * ALT_STEP_FT
MAX_VERT_RATE_FPM = 32767 * VERT_RATE_STEP_FPM
MIN_VERT_RATE_FPM = -32768 * VERT_RATE_STEP_FPM
MAX_SEEN_S = 255
MIN_RSSI, MAX_RSSI = -64.0, 63.5  # int8 dBm x2

FLAG_ON_GROUND = 1 << 0
FLAG_MLAT = 1 << 1
# The watchlist hit. A spare bit in a byte that already had two used, so this
# needed no CONTACT_VERSION bump and no record-layout change — which is why
# the signal rides here rather than in a second request. A board built before
# this existed simply never sets it and never reads it.
FLAG_WATCHED = 1 << 2


class Contact(NamedTuple):
    hex: int
    lat: float
    lon: float
    callsign: str
    type: str
    squawk: str
    alt_ft: int
    on_ground: bool
    # Whether alt_ft means anything. NOT transmitted: the altitude band is
    # applied here, so the board never has to tell "0ft" from "no idea".
    # Without this they are the same number — `alt_baro` simply absent lands
    # as 0 through _number's default — and a jet with a dropped altitude
    # field would silently vanish the moment anyone set a floor above 0.
    alt_known: bool
    watched: bool
    gs_kt: int
    track_deg: int
    vert_rate_fpm: int
    seen_s: int
    rssi: float
    is_mlat: bool
    range_nm: float


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


def _text(value, width):
    """Trimmed, truncated ASCII. Anything not a string degrades to empty.

    The feed pads callsigns with spaces, and a squawk arriving as a number
    rather than a string must become "" rather than a mangled code — leading
    zeros are significant there, so "0100" and 100 are different answers.
    """
    if not isinstance(value, str):
        return ""
    return value.strip()[:width]


def _number(value, default=0.0):
    """Feed numbers, with non-numeric values degrading to a default.

    bool is excluded deliberately: it is an int subclass in Python, and a
    JSON true arriving in a numeric field is a malformed feed, not a 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _parse_hex(value):
    """ICAO address. TIS-B addresses arrive prefixed with '~'."""
    if not isinstance(value, str):
        return 0
    text = value[1:] if value.startswith("~") else value
    try:
        return int(text, 16) & 0xFFFFFFFF
    except ValueError:
        return 0


def _to_contact(entry, home_lat, home_lon, lon_scale):
    """One feed entry, or None if it fails the same filters parse.cpp applies."""
    lat, lon = entry.get("lat"), entry.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    if isinstance(lat, bool) or isinstance(lon, bool):
        return None
    seen = _number(entry.get("seen"), 0.0)
    if seen > SEEN_DROP_S:
        return None

    # "ground" arrives as a string in the altitude field; that IS the signal.
    alt_raw = entry.get("alt_baro")
    on_ground = isinstance(alt_raw, str)
    alt_ft = 0 if on_ground else int(_number(alt_raw, 0.0))
    # On the ground the altitude is known and it is zero. Otherwise it is
    # known only if a real number arrived: bools are excluded because
    # isinstance(True, int) is True in Python and would make a stray `true`
    # read as 1ft.
    alt_known = on_ground or (isinstance(alt_raw, (int, float))
                              and not isinstance(alt_raw, bool))

    # baro_rate is the usual source. Airframes reporting only geometric
    # altitude omit it, so fall back to geom_rate before giving up.
    rate = entry.get("baro_rate")
    if rate is None:
        rate = entry.get("geom_rate")

    x = (float(lon) - home_lon) * lon_scale
    y = (float(lat) - home_lat) * NM_PER_DEG_LAT

    return Contact(
        hex=_parse_hex(entry.get("hex")),
        lat=float(lat),
        lon=float(lon),
        callsign=_text(entry.get("flight"), CALLSIGN_LEN),
        # "t" is the airframe type; "type" is how the position was obtained.
        type=_text(entry.get("t"), TYPE_LEN),
        squawk=_text(entry.get("squawk"), SQUAWK_LEN),
        alt_ft=int(_clamp(alt_ft, MIN_ALT_FT, MAX_ALT_FT)),
        on_ground=on_ground,
        alt_known=alt_known,
        # Filled in by select(), which is where the patterns are known.
        watched=False,
        gs_kt=int(_clamp(_number(entry.get("gs")), 0, 65535)),
        track_deg=int(_number(entry.get("track"))) % 360,
        vert_rate_fpm=int(_clamp(_number(rate), MIN_VERT_RATE_FPM,
                                 MAX_VERT_RATE_FPM)),
        seen_s=int(_clamp(seen, 0, MAX_SEEN_S)),
        rssi=_clamp(_number(entry.get("rssi")), MIN_RSSI, MAX_RSSI),
        is_mlat=entry.get("type") == "mlat",
        range_nm=math.hypot(x, y),
    )


# The altitude band's own bounds, mirroring DEVICE_FIELDS' amin/amax.
ALT_BAND_CEILING_FT = 70000

# A floor of 0 means NO floor, not "at or above zero". Barometric altitude
# genuinely reads slightly negative at a low airfield on a high-pressure day,
# so a literal 0 would make ground and early-climb traffic vanish at the
# DEFAULT setting — a silent wrong answer, and the worst kind. The ceiling is
# literal by contrast: nothing that reports ADS-B flies above 70000ft, so a
# record claiming to is better hidden than drawn.
NO_ALT_FLOOR = 0


def in_alt_band(contact, alt_min, alt_max):
    """Whether one contact passes the altitude band.

    An unknown altitude always passes. The same reasoning as an unknown type
    counting as ordinary rather than rare: erring toward showing keeps the
    absence of data from masquerading as a value, and a band is a filter
    someone chose, not a claim that everything outside it does not exist.
    """
    if not contact.alt_known:
        return True
    if alt_min > NO_ALT_FLOOR and contact.alt_ft < alt_min:
        return False
    return contact.alt_ft <= alt_max


# How many characters a watchlist pattern must have before it is matched as a
# substring of a type NAME. Prefix matches on the designator and the callsign
# are anchored and safe at any length; a name substring is not — "17" appears
# in "C-17", "B717" and "Beech 1700" alike. Three is where a pattern starts
# describing an airframe rather than colliding with one.
MIN_NAME_PATTERN = 3


def watch_match(contact, patterns, name_for=None):
    """Which watchlist pattern this contact hits, or None.

    Three ways to match, because none of them alone is enough:

      designator PREFIX   `B74` catches B741..B748, B74R, B74S
      callsign   PREFIX   `RRR` catches every RAF flight
      type name  SUBSTRING`737` catches all thirteen 737 designators, which
                          no designator prefix can — the MAX variants are
                          B37M/B38M/B39M and share nothing with B733..B739

    The name substring is the reason this lives on the Pi at all: the board
    holds designators and has never seen a name. It is also the loose one, and
    loose in ways that surprise. `A380` matches NOTHING, because the name is
    "AIRBUS A-380-800" — Airbus hyphenates and Boeing does not. `C-130` matches
    C130 and C30J as intended, and EC30 as well, because "EUROCOPTER EC-130"
    contains it. That is why /watch/<pattern> exists: the answer to "what does
    this actually catch" should be checkable rather than discovered later.

    Returns the matching pattern AS GIVEN, so a caller can say why — which the
    preview endpoint needs and the board does not. Comparison is
    case-insensitive: this is a public function and a caller that hand-writes
    "Hercules" should not silently match nothing because the table shouts.
    """
    if not patterns:
        return None
    designator = (contact.type or "").upper()
    callsign = (contact.callsign or "").upper()
    name = ""
    if name_for:
        name = (name_for(designator) or "").upper()
    for pattern in patterns:
        needle = pattern.strip().upper()
        if not needle:
            continue
        if designator and designator.startswith(needle):
            return pattern
        if callsign and callsign.startswith(needle):
            return pattern
        if name and len(needle) >= MIN_NAME_PATTERN and needle in name:
            return pattern
    return None


def select(aircraft, home_lat, home_lon, limit, alt_min=None, alt_max=None,
           include_mlat=True, watch=None, name_for=None):
    """Filter, range-sort and cap. Returns (contacts, total_before_cap).

    `total` is what the board renders as the second half of "32/58". The cap
    has always dropped the farthest silently; the count is what stops that
    being invisible. Band-filtered aircraft are NOT counted in it: `+N` means
    "aircraft you asked to see that did not fit", and folding in traffic
    deliberately excluded would turn a useful number into a permanent one.

    The band is applied HERE rather than on the board because the cap
    saturates continuously — a real feed runs 54-65 aircraft against 32 slots.
    Filtering at draw time would spend all 32 and then hide most of them,
    leaving fewer aircraft on screen exactly when the sky is busy. Filtering
    first means the 32 are the nearest 32 *in the band*.

    `alt_min > alt_max` is ignored rather than obeyed: obeying it empties the
    scope, and an empty scope reads as a broken board rather than as a setting
    someone typed. Same principle as viewRangesSet() refusing a zero range —
    the validator should have caught it, and this is the backstop that keeps
    the failure visible instead of silent.

    `watch` marks rather than filters — a watchlist hit sets a flag on the
    record and changes nothing about which contacts are sent. That distinction
    is worth keeping: every other argument here decides what reaches the board,
    and confusing "show me this" with "show me only this" would make an empty
    scope one typo away.

    `include_mlat=False` drops multilaterated positions here for the same
    reason the band is applied here: they occupy cap slots. Note what it costs.
    An MLAT target is a few hundred metres less certain than ADS-B, which is
    the case for dropping it — but in saturated airspace an airframe not
    sending ADS-B at all is unusual in its own right, and that signal goes with
    it. The hollow ring exists to say both things at once, so switching this
    off is a decision to stop asking the question rather than a tidy-up.
    """
    lon_scale = NM_PER_DEG_LAT * math.cos(math.radians(home_lat))
    banded = (alt_min is not None and alt_max is not None
              and alt_min <= alt_max)
    found = []
    for entry in aircraft:
        if not isinstance(entry, dict):
            continue
        contact = _to_contact(entry, home_lat, home_lon, lon_scale)
        if contact is None:
            continue
        if not include_mlat and contact.is_mlat:
            continue
        if banded and not in_alt_band(contact, alt_min, alt_max):
            continue
        if watch and watch_match(contact, watch, name_for):
            contact = contact._replace(watched=True)
        found.append(contact)
    # Stable, so equal ranges keep feed order — as insertByRange's <= does.
    found.sort(key=lambda c: c.range_nm)
    return found[:max(0, limit)], len(found)


def pack(picked, total):
    """Serialise to wire bytes."""
    out = bytearray(struct.pack(_HEADER, MAGIC, VERSION, RECORD_LEN,
                                len(picked), min(total, 65535)))
    for c in picked:
        flags = (FLAG_WATCHED if c.watched else 0) | \
                (FLAG_ON_GROUND if c.on_ground else 0) | \
                (FLAG_MLAT if c.is_mlat else 0)
        out += struct.pack(
            _RECORD,
            c.hex,
            round(c.lat * 1e7),
            round(c.lon * 1e7),
            c.callsign.encode("ascii", "replace"),
            c.type.encode("ascii", "replace"),
            c.squawk.encode("ascii", "replace"),
            round(c.alt_ft / ALT_STEP_FT),
            c.gs_kt,
            c.track_deg,
            round(c.vert_rate_fpm / VERT_RATE_STEP_FPM),
            c.seen_s,
            round(c.rssi * 2),
            flags,
            0,
        )
    return bytes(out)


def build(aircraft, home_lat, home_lon, limit, alt_min=None, alt_max=None,
          include_mlat=True, watch=None, name_for=None):
    picked, total = select(aircraft, home_lat, home_lon, limit,
                           alt_min=alt_min, alt_max=alt_max,
                           include_mlat=include_mlat, watch=watch,
                           name_for=name_for)
    return pack(picked, total)


# ---------------------------------------------------------------------------
# Round-trip reader — tests only. Production reading is on the board.
# ---------------------------------------------------------------------------

def read(data):
    if len(data) < HEADER_LEN:
        raise ValueError("too short to be a contact feed")
    magic, version, rec_len, count, total = struct.unpack_from(_HEADER, data, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported version {version}")
    if rec_len != RECORD_LEN:
        raise ValueError(f"record length {rec_len} is not {RECORD_LEN}")
    if len(data) != HEADER_LEN + count * RECORD_LEN:
        raise ValueError("length does not match the record count")

    out = []
    for i in range(count):
        (hex_, lat, lon, callsign, type_, squawk, alt25, gs, track, vr64,
         seen, rssi2, flags, _) = struct.unpack_from(
            _RECORD, data, HEADER_LEN + i * RECORD_LEN)
        out.append({
            "hex": hex_,
            "lat": lat / 1e7,
            "lon": lon / 1e7,
            "callsign": callsign.rstrip(b"\0").decode("ascii"),
            "type": type_.rstrip(b"\0").decode("ascii"),
            "squawk": squawk.rstrip(b"\0").decode("ascii"),
            "alt_ft": alt25 * ALT_STEP_FT,
            "gs_kt": gs,
            "track_deg": track,
            "vert_rate_fpm": vr64 * VERT_RATE_STEP_FPM,
            "seen_s": seen,
            "rssi": rssi2 / 2.0,
            "on_ground": bool(flags & FLAG_ON_GROUND),
            "watched": bool(flags & FLAG_WATCHED),
            "is_mlat": bool(flags & FLAG_MLAT),
        })
    return {"total": total, "contacts": out}
