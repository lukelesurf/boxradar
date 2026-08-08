"""The geography blob: one binary file per site.

Little-endian throughout, and every vertex array padded to a 4-byte boundary.
That padding is the point of the format: it lets the board cast into the
received buffer and hand out `const Vertex*` directly, so there is one heap
allocation, no per-record copy, and a render path identical to the flash
arrays it replaces. Remove the alignment and the format loses its reason to
exist.

Names are fixed-width rather than pooled in a string arena. The longest label
in include/location.h is five characters, because every character is 6px
competing with datablocks — the display constraint already bounds the data, so
an arena would save tens of bytes in exchange for offsets, a second allocation
and pointer fixup.

Nothing derived is stored. Coastline bounding boxes in particular are computed
at load, because a stored bbox can disagree with its own points and the result
is a coastline that silently fails to draw.

read() exists for round-trip tests. Production reading is
lib/radarcore/geoblob.cpp.
"""

import struct
import zlib

MAGIC = b"BXRG"
VERSION = 1
NAME_LEN = 8
MAX_NAME_CHARS = NAME_LEN - 1

HEADER_LEN = 28
SECTION_ENTRY_LEN = 12
CRC_START = 16

KIND_AIRSPACE = 1
KIND_COASTLINE = 2
KIND_AIRFIELDS = 3
KIND_RUNWAYS = 4
KIND_WAYPOINTS = 5
KIND_TOWNS = 6

POLYLINE_KINDS = (KIND_AIRSPACE, KIND_COASTLINE)
NAMED_POINT_KINDS = (KIND_AIRFIELDS, KIND_WAYPOINTS, KIND_TOWNS)

_KNOWN_KINDS = POLYLINE_KINDS + NAMED_POINT_KINDS + (KIND_RUNWAYS,)


class NameTooLong(ValueError):
    pass


def _pad4(data):
    """Grow a bytearray to the next 4-byte boundary."""
    while len(data) % 4:
        data += b"\x00"
    return data


def _encode_name(name):
    encoded = str(name).encode("ascii", "replace")
    if len(encoded) > MAX_NAME_CHARS:
        raise NameTooLong(
            f"{name!r} is {len(encoded)} chars, limit is {MAX_NAME_CHARS} — "
            f"shorten the label rather than letting the scope truncate it")
    return encoded + b"\x00" * (NAME_LEN - len(encoded))


def _encode_polylines(rings):
    out = bytearray()
    for ring in rings:
        if len(ring) < 2:
            raise ValueError(f"polyline needs at least 2 points, got "
                             f"{len(ring)}")
        out += struct.pack("<HH", len(ring), 0)  # count, pad -> aligns vertices
        for lat, lon in ring:
            out += struct.pack("<ff", lat, lon)
    return out


def _encode_named_points(points):
    out = bytearray()
    for name, lat, lon in points:
        out += _encode_name(name) + struct.pack("<ff", lat, lon)
    return out


def _encode_runways(axes):
    out = bytearray()
    for lat0, lon0, lat1, lon1 in axes:
        out += struct.pack("<ffff", lat0, lon0, lat1, lon1)
    return out


def _encode_section(kind, records):
    if kind in POLYLINE_KINDS:
        return _encode_polylines(records)
    if kind in NAMED_POINT_KINDS:
        return _encode_named_points(records)
    if kind == KIND_RUNWAYS:
        return _encode_runways(records)
    raise ValueError(f"unknown section kind {kind}")


def write(home_lat, home_lon, sections):
    """Serialise sections to blob bytes. Empty sections are omitted."""
    for kind in sections:
        if kind not in _KNOWN_KINDS:
            raise ValueError(f"unknown section kind {kind}")

    # Deterministic order, so the committed C++ fixture is regenerable and an
    # unchanged site produces an unchanged ETag.
    present = sorted(k for k, v in sections.items() if v)
    encoded = {k: _encode_section(k, sections[k]) for k in present}

    table_len = len(present) * SECTION_ENTRY_LEN
    cursor = HEADER_LEN + table_len
    while cursor % 4:
        cursor += 1

    entries, payload = [], bytearray()
    for kind in present:
        body = encoded[kind]
        offset = cursor + len(payload)
        entries.append((kind, len(sections[kind]), offset, len(body)))
        payload += body
        payload = _pad4(payload)

    table = bytearray()
    for kind, count, offset, length in entries:
        table += struct.pack("<HHII", kind, count, offset, length)
    table = _pad4(table)

    body = struct.pack("<ffHH", float(home_lat), float(home_lon),
                       len(present), 0) + bytes(table) + bytes(payload)
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return MAGIC + struct.pack("<HHII", VERSION, 0, crc, len(body)) + body


# ---------------------------------------------------------------------------
# Round-trip reader — tests only. Production reading is radarcore/geoblob.cpp.
# ---------------------------------------------------------------------------

def read(data):
    if len(data) < CRC_START:
        raise ValueError("too short to be a blob")
    if data[:4] != MAGIC:
        raise ValueError(f"bad magic {data[:4]!r}")
    version, _, crc, length = struct.unpack_from("<HHII", data, 4)
    if version != VERSION:
        raise ValueError(f"unsupported version {version}")
    body = data[CRC_START:CRC_START + length]
    if len(body) != length:
        raise ValueError("truncated payload")
    if (zlib.crc32(body) & 0xFFFFFFFF) != crc:
        raise ValueError("crc mismatch")

    home_lat, home_lon, count, _ = struct.unpack_from("<ffHH", data, CRC_START)
    sections = {}
    for i in range(count):
        kind, records, offset, seclen = struct.unpack_from(
            "<HHII", data, HEADER_LEN + i * SECTION_ENTRY_LEN)
        if offset + seclen > len(data):
            raise ValueError(f"section {kind} runs past the end")
        sections[kind] = _decode_section(kind, records, data, offset)
    return {"home": (home_lat, home_lon), "sections": sections}


def _decode_section(kind, records, data, offset):
    if kind in POLYLINE_KINDS:
        out, pos = [], offset
        for _ in range(records):
            n = struct.unpack_from("<H", data, pos)[0]
            pos += 4
            ring = [struct.unpack_from("<ff", data, pos + j * 8)
                    for j in range(n)]
            pos += n * 8
            out.append(ring)
        return out
    if kind in NAMED_POINT_KINDS:
        out = []
        for i in range(records):
            base = offset + i * 16
            name = data[base:base + NAME_LEN].split(b"\x00")[0].decode("ascii")
            lat, lon = struct.unpack_from("<ff", data, base + NAME_LEN)
            out.append((name, lat, lon))
        return out
    if kind == KIND_RUNWAYS:
        return [struct.unpack_from("<ffff", data, offset + i * 16)
                for i in range(records)]
    raise ValueError(f"unknown section kind {kind}")
