# Geography Blob Implementation Plan (phase 2b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One binary file per site carrying airspace, coastline and point references, written by the Pi and readable by the board — with the reader natively tested, so phase 3b is plumbing rather than discovery.

**Architecture:** A single little-endian blob with a section table. Every vertex array is padded to 4-byte alignment so the board takes `const Vertex*` directly into the received buffer: zero copy, one heap allocation, and a render path byte-identical to today's flash arrays. The Python writer lives in `boxradar_site/geo/blob.py`; the reader is `lib/radarcore/geoblob.{h,cpp}`, portable and covered by Unity tests against a committed fixture. The generators keep emitting the existing C headers as well, so the firmware is untouched by this phase and every step stays shippable.

**Tech Stack:** Python `struct` for the writer; portable C++ for the reader (no Arduino, no TFT_eSPI, so it links in `[env:native]`).

## Global Constraints

- **The firmware does not change in this phase.** Headers keep being generated and keep being what `scope.cpp` uses. The blob is written, read and tested, but not yet consumed on device. Switching over is phase 3b.
- **Little-endian, 4-byte aligned.** The ESP32 and the x86_64 test host are both little-endian, so `float32` and `uint32` are read directly. Alignment is not optional: the ESP32 can fault or silently misread on an unaligned 32-bit load, and the whole point of the format is handing out `const Vertex*` into the buffer.
- **Read with `memcpy` into locals, never by casting a `char*` to `float*`.** Casting is undefined behaviour and, on Xtensa, occasionally wrong in practice. `memcpy` of 4 bytes compiles to a single load when the address is aligned, so it costs nothing.
- **Names are fixed-width `char[8]`.** The longest label in `include/location.h` is 5 characters (`LOREL`, `ABBOT`); airfields are 4-char ICAO and towns are already abbreviated to 4 (`STVG`, `HRFD`) because every character is 6px competing with datablocks. 7 chars plus NUL is generous. **The generator must reject a longer name** rather than truncating it — a wrong label costs more than the bytes saved. This replaces the string arena the spec called for; see the design doc for why.
- **No derived data in the blob.** Coastline bounding boxes are computed at load. `src/ui/coastline_data.h` precomputes them today, and they are worth having in RAM — but storing them in the file means a bbox can disagree with its own points, and the README already documents that a coastline which silently fails to draw is the worst failure mode here.
- **`lib/radarcore` stays portable.** `geoblob.cpp` may include `<stdint.h>`, `<string.h>` and nothing else. No `Arduino.h`, no `TFT_eSPI`.
- **The device build is `-std=gnu++11`; the native test env is `gnu++17`.** Anything in `lib/radarcore` must compile under both. `test_viewport` passing at C++17 while the device build broke at C++11 has already happened once in this repo — no default member initialisers in aggregates, no structured bindings, no `if constexpr`.
- Python tests: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
- Native C++ tests: `pio test -e native`
- Device build check: `pio run -e usb`

---

## The format

```
offset  size  field
------  ----  ---------------------------------------------------------------
   0     4    magic "BXRG"
   4     2    version (u16, currently 1)
   6     2    reserved (u16, zero)
   8     4    crc32 of everything from offset 16 to end (u32)
  12     4    payload length in bytes, from offset 16 (u32)
  16     4    homeLat (f32)
  20     4    homeLon (f32)
  24     2    section count (u16)
  26     2    reserved (u16, zero)
  28     ..   section table: count * 12 bytes
              u16 kind, u16 recordCount, u32 offset, u32 byteLength
   ..    ..   section payloads, each 4-byte aligned
```

`homeLat`/`homeLon` sit **inside** the CRC'd region deliberately: the board
rejects a blob whose home does not match its own config, which turns the
documented trap — "Regenerate after moving, or it will keep drawing the
previous area's coast" — from a silent wrong-area render into a visible
refusal.

Section kinds and record layouts. All offsets are absolute from byte 0, and
every section payload starts on a 4-byte boundary.

| kind | value | record |
|---|---|---|
| `AIRSPACE` | 1 | `u16 count, u16 pad, then count * (f32 lat, f32 lon)` |
| `COASTLINE` | 2 | same as AIRSPACE |
| `AIRFIELDS` | 3 | `char[8] name, f32 lat, f32 lon` (16 bytes) |
| `RUNWAYS` | 4 | `f32 lat0, f32 lon0, f32 lat1, f32 lon1` (16 bytes) |
| `WAYPOINTS` | 5 | `char[8] name, f32 lat, f32 lon` (16 bytes) |
| `TOWNS` | 6 | `char[8] name, f32 lat, f32 lon` (16 bytes) |

The `u16 pad` after each polyline's count is what keeps the following vertex
array 4-byte aligned, which is what makes `const Vertex*` into the buffer
legal. It is not spare space for later use — removing it breaks the format's
central property.

Polyline sections are a run of variable-length records, so they are walked
rather than indexed; the point-reference sections are fixed-stride and can be
indexed directly.

---

## File Structure

**Created:**

| file | responsibility |
|---|---|
| `boxradar_site/geo/blob.py` | the writer, and a Python reader used only for round-trip tests |
| `boxradar_site/geo/coastline.py` | coastline fetch, filter and simplify, moved from `tools/build_coastline.py` |
| `boxradar_site/geo/points.py` | point references from the selection config; emits `location.h` and the blob sections |
| `lib/radarcore/geoblob.h` | the reader's types and API |
| `lib/radarcore/geoblob.cpp` | the reader |
| `test/test_geoblob/test_main.cpp` | Unity tests over a committed fixture |
| `test/test_geoblob/fixture_blob.h` | generated byte array — a real blob, small |
| `tools/boxradar-site/tests/test_blob.py` | writer and round-trip tests |
| `tools/boxradar-site/tests/test_fixture_current.py` | asserts the committed fixture is regenerable |

**Modified:** `boxradar_site/geo/__main__.py`, `boxradar_site/geo/selection.example.json`, `README.md`, `SPEC.md`
**Deleted (last task only):** `tools/build_coastline.py`

---

### Task 1: The writer and its round trip

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/blob.py`
- Test: `tools/boxradar-site/tests/test_blob.py`

**Interfaces:**
- Produces:
  - `MAGIC = b"BXRG"`, `VERSION = 1`, `NAME_LEN = 8`
  - `KIND_AIRSPACE=1, KIND_COASTLINE=2, KIND_AIRFIELDS=3, KIND_RUNWAYS=4, KIND_WAYPOINTS=5, KIND_TOWNS=6`
  - `class NameTooLong(ValueError)`
  - `write(home_lat, home_lon, sections: dict[int, list]) -> bytes` — polyline sections take `list[list[(lat, lon)]]`, point sections take `list[(name, lat, lon)]`, runways take `list[(lat0, lon0, lat1, lon1)]`
  - `read(data: bytes) -> dict` — `{"home": (lat, lon), "sections": {kind: [...]}}`, raising `ValueError` on bad magic, version, CRC or truncation. Exists for the round trip, not for production use.

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_blob.py`:

```python
import struct
import unittest

from boxradar_site.geo import blob


AIRSPACE = [[(51.9, 0.03), (52.0, 0.1), (51.8, 0.2), (51.9, 0.03)],
            [(51.5, -0.4), (51.6, -0.3), (51.5, -0.4)]]
AIRFIELDS = [("EGSS", 51.885, 0.235), ("EGGW", 51.874, -0.368)]
RUNWAYS = [(51.8795, 0.2216, 51.8905, 0.2493)]
WAYPOINTS = [("LOREL", 51.9825, -0.2136)]
TOWNS = [("STVG", 51.9019, -0.2019)]


def full_blob():
    return blob.write(51.8850, 0.2350, {
        blob.KIND_AIRSPACE: AIRSPACE,
        blob.KIND_COASTLINE: [[(51.0, 1.0), (51.1, 1.1), (51.2, 1.05)]],
        blob.KIND_AIRFIELDS: AIRFIELDS,
        blob.KIND_RUNWAYS: RUNWAYS,
        blob.KIND_WAYPOINTS: WAYPOINTS,
        blob.KIND_TOWNS: TOWNS,
    })


class TestHeader(unittest.TestCase):
    def test_magic_and_version(self):
        data = full_blob()
        self.assertEqual(data[:4], blob.MAGIC)
        self.assertEqual(struct.unpack_from("<H", data, 4)[0], blob.VERSION)

    def test_payload_length_matches_reality(self):
        data = full_blob()
        declared = struct.unpack_from("<I", data, 12)[0]
        self.assertEqual(declared, len(data) - 16)

    def test_home_is_inside_the_crc_region(self):
        # Corrupting home must invalidate the CRC, so a blob for the wrong
        # area cannot be silently accepted after a byte flip.
        data = bytearray(full_blob())
        data[16] ^= 0xFF
        with self.assertRaises(ValueError):
            blob.read(bytes(data))


class TestAlignment(unittest.TestCase):
    def test_every_section_starts_4_byte_aligned(self):
        data = full_blob()
        count = struct.unpack_from("<H", data, 24)[0]
        for i in range(count):
            _, _, offset, _ = struct.unpack_from("<HHII", data, 28 + i * 12)
            self.assertEqual(offset % 4, 0, f"section {i} at {offset}")

    def test_every_vertex_array_is_4_byte_aligned(self):
        # The property the whole format exists for: the board hands out
        # const Vertex* into this buffer, and an unaligned 32-bit load can
        # fault or misread on the ESP32.
        data = full_blob()
        count = struct.unpack_from("<H", data, 24)[0]
        for i in range(count):
            kind, records, offset, length = struct.unpack_from(
                "<HHII", data, 28 + i * 12)
            if kind not in (blob.KIND_AIRSPACE, blob.KIND_COASTLINE):
                continue
            pos = offset
            for _ in range(records):
                n = struct.unpack_from("<H", data, pos)[0]
                self.assertEqual((pos + 4) % 4, 0,
                                 f"vertices at {pos + 4} not aligned")
                pos += 4 + n * 8

    def test_total_length_is_a_multiple_of_four(self):
        self.assertEqual(len(full_blob()) % 4, 0)


class TestRoundTrip(unittest.TestCase):
    def test_home_survives(self):
        got = blob.read(full_blob())
        self.assertAlmostEqual(got["home"][0], 51.8850, places=4)
        self.assertAlmostEqual(got["home"][1], 0.2350, places=4)

    def test_polylines_survive(self):
        got = blob.read(full_blob())["sections"][blob.KIND_AIRSPACE]
        self.assertEqual(len(got), 2)
        self.assertEqual(len(got[0]), 4)
        self.assertAlmostEqual(got[0][0][0], 51.9, places=4)
        self.assertAlmostEqual(got[0][0][1], 0.03, places=4)

    def test_named_points_survive(self):
        got = blob.read(full_blob())["sections"][blob.KIND_AIRFIELDS]
        self.assertEqual([n for n, _, _ in got], ["EGSS", "EGGW"])
        self.assertAlmostEqual(got[0][1], 51.885, places=4)

    def test_runways_survive(self):
        got = blob.read(full_blob())["sections"][blob.KIND_RUNWAYS]
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0][3], 0.2493, places=4)

    def test_empty_sections_are_omitted_not_stored_empty(self):
        data = blob.write(51.9, 0.0, {blob.KIND_AIRSPACE: []})
        self.assertEqual(blob.read(data)["sections"], {})

    def test_writing_is_deterministic(self):
        # The fixture committed for the C++ tests has to be regenerable, and
        # a blob that varies run to run would also defeat ETag caching.
        self.assertEqual(full_blob(), full_blob())


class TestValidation(unittest.TestCase):
    def test_name_longer_than_seven_chars_is_rejected(self):
        # Truncating would put a wrong label on the scope, which costs more
        # than the bytes saved.
        with self.assertRaises(blob.NameTooLong):
            blob.write(51.9, 0.0,
                       {blob.KIND_AIRFIELDS: [("TOOLONGNAME", 51.9, 0.0)]})

    def test_seven_chars_is_accepted(self):
        data = blob.write(51.9, 0.0,
                         {blob.KIND_TOWNS: [("ABCDEFG", 51.9, 0.0)]})
        self.assertEqual(blob.read(data)["sections"][blob.KIND_TOWNS][0][0],
                         "ABCDEFG")

    def test_polyline_needs_at_least_two_points(self):
        with self.assertRaises(ValueError):
            blob.write(51.9, 0.0, {blob.KIND_AIRSPACE: [[(51.9, 0.0)]]})

    def test_bad_magic_rejected(self):
        with self.assertRaises(ValueError):
            blob.read(b"NOPE" + full_blob()[4:])

    def test_unknown_version_rejected(self):
        data = bytearray(full_blob())
        struct.pack_into("<H", data, 4, 99)
        with self.assertRaises(ValueError):
            blob.read(bytes(data))

    def test_truncation_rejected(self):
        with self.assertRaises(ValueError):
            blob.read(full_blob()[:-8])

    def test_corrupt_payload_rejected(self):
        data = bytearray(full_blob())
        data[-4] ^= 0xFF
        with self.assertRaises(ValueError):
            blob.read(bytes(data))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.blob'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/geo/blob.py`:

```python
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
    return (MAGIC + struct.pack("<HHII", VERSION, 0, crc, len(body))
            + body)


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
```

- [ ] **Step 4: Run to verify passing**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 152 tests

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/blob.py \
        tools/boxradar-site/tests/test_blob.py
git commit -m "feat: geography blob writer with 4-byte aligned vertex arrays

The alignment is the format's reason to exist: it lets the board cast into the
received buffer and hand out const Vertex* directly, so there is one heap
allocation and a render path identical to the flash arrays it replaces.

Two departures from the spec, both because the data turned out smaller than
assumed. Names are fixed char[8] rather than pooled in a string arena — the
longest label in location.h is five characters, since every character is 6px
competing with datablocks, so an arena would save tens of bytes for offsets
and a second allocation. And coastline bboxes are not stored: they are derived,
and a stored bbox that disagrees with its own points gives a coastline that
silently fails to draw."
```

---

### Task 2: The C++ reader

**Files:**
- Create: `lib/radarcore/geoblob.h`
- Create: `lib/radarcore/geoblob.cpp`
- Create: `test/test_geoblob/test_main.cpp`
- Create: `test/test_geoblob/fixture_blob.h`
- Create: `tools/boxradar-site/tools_make_fixture.py`
- Test: `tools/boxradar-site/tests/test_fixture_current.py`

**Interfaces:**
- Produces, in `namespace radar`:
  - `struct GeoVertex { float lat, lon; };`
  - `struct GeoPolyline { const GeoVertex *pts; uint16_t count; };`
  - `struct GeoNamedPoint { char name[8]; float lat, lon; };`
  - `struct GeoRunway { float lat0, lon0, lat1, lon1; };`
  - `enum GeoKind { GEO_AIRSPACE=1, GEO_COASTLINE=2, GEO_AIRFIELDS=3, GEO_RUNWAYS=4, GEO_WAYPOINTS=5, GEO_TOWNS=6 };`
  - `enum GeoStatus { GEO_OK=0, GEO_BAD_MAGIC, GEO_BAD_VERSION, GEO_TRUNCATED, GEO_BAD_CRC, GEO_WRONG_HOME };`
  - `class GeoBlob` with:
    - `GeoStatus open(const uint8_t *data, size_t len, float homeLat, float homeLon)`
    - `float homeLat() const`, `float homeLon() const`
    - `uint16_t recordCount(GeoKind) const`
    - `bool polyline(GeoKind, uint16_t index, GeoPolyline &out) const`
    - `const GeoNamedPoint *namedPoints(GeoKind) const`
    - `const GeoRunway *runways() const`
  - `const char *geoStatusName(GeoStatus)`

Polylines are indexed by walking, so `polyline()` is O(index). The board reads
each section once per frame in order, so that is fine and it avoids storing an
index the file does not need.

- [ ] **Step 1: Write the fixture generator**

Create `tools/boxradar-site/tools_make_fixture.py`:

```python
#!/usr/bin/env python3
"""Generate test/test_geoblob/fixture_blob.h — a real, small blob as a C array.

A byte array rather than a file the C++ test opens: Unity tests run with an
unpredictable working directory, and a committed array cannot go missing.
tests/test_fixture_current.py asserts this stays regenerable, so the fixture
cannot drift from the writer.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from boxradar_site.geo import blob  # noqa: E402

HOME_LAT, HOME_LON = 51.8850, 0.2350

SECTIONS = {
    blob.KIND_AIRSPACE: [
        [(51.86523, 0.02170), (52.01778, 0.25083), (51.90447, 0.44838),
         (51.86523, 0.02170)],
        [(51.75222, 0.21917), (51.75574, 0.18333), (51.75222, 0.21917)],
    ],
    blob.KIND_COASTLINE: [
        [(51.23144, 1.40461), (51.31309, 1.37178), (51.31115, 1.35904)],
    ],
    blob.KIND_AIRFIELDS: [("EGSS", 51.88500, 0.23500),
                          ("EGGW", 51.87400, -0.36800)],
    blob.KIND_RUNWAYS: [(51.87950, 0.22160, 51.89050, 0.24930)],
    blob.KIND_WAYPOINTS: [("LOREL", 51.98250, -0.21360)],
    blob.KIND_TOWNS: [("STVG", 51.90190, -0.20190)],
}


def render(data):
    lines = [
        "// GENERATED by tools/boxradar-site/tools_make_fixture.py",
        "// A real geography blob, small enough to read. Regenerate with that",
        "// script; tests/test_fixture_current.py fails if it drifts.",
        "#pragma once",
        "#include <stdint.h>",
        "",
        f"// home {HOME_LAT}, {HOME_LON}",
        f"static const uint32_t FIXTURE_LEN = {len(data)};",
        "static const uint8_t FIXTURE[] = {",
    ]
    for i in range(0, len(data), 12):
        chunk = ", ".join(f"0x{b:02x}" for b in data[i:i + 12])
        lines.append(f"    {chunk},")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main():
    data = blob.write(HOME_LAT, HOME_LON, SECTIONS)
    repo = pathlib.Path(__file__).resolve().parents[2]
    out = repo / "test" / "test_geoblob" / "fixture_blob.h"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data))
    print(f"wrote {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Generate the fixture**

```bash
cd tools/boxradar-site && python3 tools_make_fixture.py && cd ../..
head -12 test/test_geoblob/fixture_blob.h
```

Expected: a header with `FIXTURE_LEN` and a byte array.

- [ ] **Step 3: Write the drift guard**

Create `tools/boxradar-site/tests/test_fixture_current.py`:

```python
"""The committed C++ fixture must stay regenerable from the writer.

Without this, a format change would leave the C++ tests passing against a
stale fixture — green tests proving the reader can still parse a file the
writer no longer produces.
"""

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
FIXTURE = REPO / "test" / "test_geoblob" / "fixture_blob.h"


@unittest.skipUnless(FIXTURE.exists(), "fixture not generated yet")
class TestFixtureMatchesWriter(unittest.TestCase):
    def test_bytes_are_what_the_writer_produces_now(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "make_fixture",
            REPO / "tools" / "boxradar-site" / "tools_make_fixture.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        from boxradar_site.geo import blob
        expected = blob.write(module.HOME_LAT, module.HOME_LON,
                              module.SECTIONS)

        text = FIXTURE.read_text()
        declared = int(re.search(r"FIXTURE_LEN = (\d+)", text).group(1))
        committed = bytes(int(b, 16) for b in
                          re.findall(r"0x([0-9a-f]{2})", text))

        self.assertEqual(declared, len(expected),
                         "fixture length is stale — re-run "
                         "tools_make_fixture.py")
        self.assertEqual(committed, expected,
                         "fixture bytes are stale — re-run "
                         "tools_make_fixture.py")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Write the failing Unity test**

Create `test/test_geoblob/test_main.cpp`:

```cpp
#include <unity.h>
#include "geoblob.h"
#include "fixture_blob.h"

using namespace radar;

static const float HOME_LAT = 51.8850f;
static const float HOME_LON = 0.2350f;

static GeoBlob openFixture() {
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_OK, b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON));
  return b;
}

static void test_opens_a_good_blob() {
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_OK, b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON));
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, HOME_LAT, b.homeLat());
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, HOME_LON, b.homeLon());
}

static void test_rejects_bad_magic() {
  uint8_t copy[16];
  memcpy(copy, FIXTURE, sizeof(copy));
  copy[0] = 'X';
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_BAD_MAGIC,
                    b.open(copy, sizeof(copy), HOME_LAT, HOME_LON));
}

static void test_rejects_truncation() {
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_TRUNCATED,
                    b.open(FIXTURE, FIXTURE_LEN - 8, HOME_LAT, HOME_LON));
}

static void test_rejects_a_blob_for_the_wrong_area() {
  // The documented trap: "Regenerate after moving, or it will keep drawing
  // the previous area's coast." A visible refusal beats a silent wrong map.
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_WRONG_HOME,
                    b.open(FIXTURE, FIXTURE_LEN, 55.0f, -3.0f));
}

static void test_record_counts() {
  GeoBlob b = openFixture();
  TEST_ASSERT_EQUAL_UINT16(2, b.recordCount(GEO_AIRSPACE));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_COASTLINE));
  TEST_ASSERT_EQUAL_UINT16(2, b.recordCount(GEO_AIRFIELDS));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_RUNWAYS));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_WAYPOINTS));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_TOWNS));
}

static void test_missing_section_has_no_records() {
  GeoBlob b = openFixture();
  TEST_ASSERT_EQUAL_UINT16(0, b.recordCount((GeoKind)99));
}

static void test_polyline_vertices() {
  GeoBlob b = openFixture();
  GeoPolyline line;
  TEST_ASSERT_TRUE(b.polyline(GEO_AIRSPACE, 0, line));
  TEST_ASSERT_EQUAL_UINT16(4, line.count);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.86523f, line.pts[0].lat);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.02170f, line.pts[0].lon);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.90447f, line.pts[2].lat);
}

static void test_second_polyline_is_reachable() {
  GeoBlob b = openFixture();
  GeoPolyline line;
  TEST_ASSERT_TRUE(b.polyline(GEO_AIRSPACE, 1, line));
  TEST_ASSERT_EQUAL_UINT16(3, line.count);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.75222f, line.pts[0].lat);
}

static void test_polyline_index_out_of_range() {
  GeoBlob b = openFixture();
  GeoPolyline line;
  TEST_ASSERT_FALSE(b.polyline(GEO_AIRSPACE, 2, line));
}

static void test_vertex_pointers_are_4_byte_aligned() {
  // If this fails the format is broken, not the test: an unaligned 32-bit
  // load can fault or silently misread on the ESP32.
  GeoBlob b = openFixture();
  GeoPolyline line;
  for (uint16_t i = 0; i < b.recordCount(GEO_AIRSPACE); i++) {
    TEST_ASSERT_TRUE(b.polyline(GEO_AIRSPACE, i, line));
    TEST_ASSERT_EQUAL_UINT32(0, ((uintptr_t)line.pts) % 4);
  }
}

static void test_named_points() {
  GeoBlob b = openFixture();
  const GeoNamedPoint *fields = b.namedPoints(GEO_AIRFIELDS);
  TEST_ASSERT_NOT_NULL(fields);
  TEST_ASSERT_EQUAL_STRING("EGSS", fields[0].name);
  TEST_ASSERT_EQUAL_STRING("EGGW", fields[1].name);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.885f, fields[0].lat);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, -0.368f, fields[1].lon);
}

static void test_names_are_nul_terminated_even_at_full_length() {
  GeoBlob b = openFixture();
  const GeoNamedPoint *fixes = b.namedPoints(GEO_WAYPOINTS);
  TEST_ASSERT_EQUAL_STRING("LOREL", fixes[0].name);
  TEST_ASSERT_EQUAL_CHAR('\0', fixes[0].name[7]);
}

static void test_runways() {
  GeoBlob b = openFixture();
  const GeoRunway *r = b.runways();
  TEST_ASSERT_NOT_NULL(r);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.8795f, r[0].lat0);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.2493f, r[0].lon1);
}

static void test_status_names_are_distinct() {
  TEST_ASSERT_EQUAL_STRING("ok", geoStatusName(GEO_OK));
  TEST_ASSERT_NOT_EQUAL(0, strcmp(geoStatusName(GEO_BAD_CRC),
                                  geoStatusName(GEO_WRONG_HOME)));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_opens_a_good_blob);
  RUN_TEST(test_rejects_bad_magic);
  RUN_TEST(test_rejects_truncation);
  RUN_TEST(test_rejects_a_blob_for_the_wrong_area);
  RUN_TEST(test_record_counts);
  RUN_TEST(test_missing_section_has_no_records);
  RUN_TEST(test_polyline_vertices);
  RUN_TEST(test_second_polyline_is_reachable);
  RUN_TEST(test_polyline_index_out_of_range);
  RUN_TEST(test_vertex_pointers_are_4_byte_aligned);
  RUN_TEST(test_named_points);
  RUN_TEST(test_names_are_nul_terminated_even_at_full_length);
  RUN_TEST(test_runways);
  RUN_TEST(test_status_names_are_distinct);
  return UNITY_END();
}
```

- [ ] **Step 5: Run to verify failure**

Run: `pio test -e native -f test_geoblob`
Expected: compile failure — `geoblob.h: No such file or directory`.

Note: `test_geoblob` includes `fixture_blob.h` from its own directory, which
works without changing `platformio.ini` because PlatformIO adds the test
directory to the include path.

- [ ] **Step 6: Write the header**

Create `lib/radarcore/geoblob.h`:

```cpp
#pragma once
#include <stddef.h>
#include <stdint.h>

// Reader for the geography blob written by boxradar_site.geo.
//
// Zero copy by design. open() validates the buffer and records section
// offsets; every accessor then points INTO that buffer, which the caller owns
// and must keep alive for as long as the GeoBlob is used. That is what makes
// this cost one allocation instead of one per record, and it is only legal
// because the writer pads every vertex array to a 4-byte boundary.
//
// Portable on purpose: stdint and string.h only, no Arduino, no TFT_eSPI, so
// it links in [env:native] and is tested off device. It must also compile
// under gnu++11, which is what the ESP32 core uses — no default member
// initialisers in aggregates.

namespace radar {

struct GeoVertex {
  float lat, lon;
};

struct GeoPolyline {
  const GeoVertex *pts;
  uint16_t count;
};

struct GeoNamedPoint {
  char name[8];
  float lat, lon;
};

struct GeoRunway {
  float lat0, lon0, lat1, lon1;
};

enum GeoKind {
  GEO_AIRSPACE = 1,
  GEO_COASTLINE = 2,
  GEO_AIRFIELDS = 3,
  GEO_RUNWAYS = 4,
  GEO_WAYPOINTS = 5,
  GEO_TOWNS = 6,
};

enum GeoStatus {
  GEO_OK = 0,
  GEO_BAD_MAGIC,
  GEO_BAD_VERSION,
  GEO_TRUNCATED,
  GEO_BAD_CRC,
  GEO_WRONG_HOME,
};

const char *geoStatusName(GeoStatus status);

// Home must match to within this, in degrees (~11m). A blob generated for a
// different site would otherwise render the previous area's map with no
// indication, which the README already documents as the trap here.
const float GEO_HOME_TOLERANCE_DEG = 0.0001f;

class GeoBlob {
public:
  GeoBlob();

  GeoStatus open(const uint8_t *data, size_t len, float homeLat,
                 float homeLon);

  bool valid() const { return m_valid; }
  float homeLat() const { return m_homeLat; }
  float homeLon() const { return m_homeLon; }

  uint16_t recordCount(GeoKind kind) const;

  // Walks from the start of the section, so this is O(index). The render
  // passes iterate in order, and an index would be data the file does not
  // need to carry.
  bool polyline(GeoKind kind, uint16_t index, GeoPolyline &out) const;

  const GeoNamedPoint *namedPoints(GeoKind kind) const;
  const GeoRunway *runways() const;

private:
  static const int MAX_SECTIONS = 8;

  struct Section {
    uint16_t kind;
    uint16_t count;
    uint32_t offset;
    uint32_t length;
  };

  const Section *find(GeoKind kind) const;

  const uint8_t *m_data;
  size_t m_len;
  Section m_sections[MAX_SECTIONS];
  int m_sectionCount;
  float m_homeLat;
  float m_homeLon;
  bool m_valid;
};

} // namespace radar
```

- [ ] **Step 7: Write the implementation**

Create `lib/radarcore/geoblob.cpp`:

```cpp
#include "geoblob.h"
#include <string.h>

namespace radar {

namespace {

const uint32_t HEADER_LEN = 28;
const uint32_t SECTION_ENTRY_LEN = 12;
const uint32_t CRC_START = 16;

// Every multi-byte read goes through these. Casting a const uint8_t* to a
// float* would be undefined behaviour and, on Xtensa, occasionally wrong in
// practice; memcpy of four bytes compiles to a single load when the address
// is aligned, so this costs nothing.
uint16_t readU16(const uint8_t *p) {
  uint16_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

uint32_t readU32(const uint8_t *p) {
  uint32_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

float readF32(const uint8_t *p) {
  float v;
  memcpy(&v, p, sizeof(v));
  return v;
}

// CRC-32 (IEEE 802.3, reflected) to match Python's zlib.crc32. Computed
// bitwise rather than from a 1KB table: this runs once per blob load, and
// 22KB of input costs well under a millisecond at 240MHz.
uint32_t crc32(const uint8_t *data, size_t len) {
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; bit++) {
      crc = (crc >> 1) ^ (0xEDB88320u & (~(crc & 1u) + 1u));
    }
  }
  return ~crc;
}

bool nearly(float a, float b) {
  float d = a - b;
  if (d < 0) d = -d;
  return d <= GEO_HOME_TOLERANCE_DEG;
}

} // namespace

const char *geoStatusName(GeoStatus status) {
  switch (status) {
  case GEO_OK: return "ok";
  case GEO_BAD_MAGIC: return "not a geography blob";
  case GEO_BAD_VERSION: return "unsupported blob version";
  case GEO_TRUNCATED: return "blob truncated";
  case GEO_BAD_CRC: return "blob corrupt";
  case GEO_WRONG_HOME: return "blob is for a different location";
  }
  return "unknown";
}

GeoBlob::GeoBlob()
    : m_data(0), m_len(0), m_sectionCount(0), m_homeLat(0.0f),
      m_homeLon(0.0f), m_valid(false) {}

GeoStatus GeoBlob::open(const uint8_t *data, size_t len, float homeLat,
                        float homeLon) {
  m_valid = false;
  m_sectionCount = 0;
  if (!data || len < CRC_START) return GEO_TRUNCATED;
  if (memcmp(data, "BXRG", 4) != 0) return GEO_BAD_MAGIC;

  uint16_t version = readU16(data + 4);
  if (version != 1) return GEO_BAD_VERSION;

  uint32_t crc = readU32(data + 8);
  uint32_t bodyLen = readU32(data + 12);
  if (CRC_START + bodyLen > len) return GEO_TRUNCATED;
  if (crc32(data + CRC_START, bodyLen) != crc) return GEO_BAD_CRC;

  float blobLat = readF32(data + CRC_START);
  float blobLon = readF32(data + CRC_START + 4);
  if (!nearly(blobLat, homeLat) || !nearly(blobLon, homeLon)) {
    return GEO_WRONG_HOME;
  }

  uint16_t count = readU16(data + CRC_START + 8);
  if (count > MAX_SECTIONS) return GEO_TRUNCATED;
  for (uint16_t i = 0; i < count; i++) {
    const uint8_t *entry = data + HEADER_LEN + i * SECTION_ENTRY_LEN;
    if ((size_t)(entry + SECTION_ENTRY_LEN - data) > len) return GEO_TRUNCATED;
    Section s;
    s.kind = readU16(entry);
    s.count = readU16(entry + 2);
    s.offset = readU32(entry + 4);
    s.length = readU32(entry + 8);
    if ((size_t)s.offset + s.length > len) return GEO_TRUNCATED;
    m_sections[m_sectionCount++] = s;
  }

  m_data = data;
  m_len = len;
  m_homeLat = blobLat;
  m_homeLon = blobLon;
  m_valid = true;
  return GEO_OK;
}

const GeoBlob::Section *GeoBlob::find(GeoKind kind) const {
  if (!m_valid) return 0;
  for (int i = 0; i < m_sectionCount; i++) {
    if (m_sections[i].kind == (uint16_t)kind) return &m_sections[i];
  }
  return 0;
}

uint16_t GeoBlob::recordCount(GeoKind kind) const {
  const Section *s = find(kind);
  return s ? s->count : 0;
}

bool GeoBlob::polyline(GeoKind kind, uint16_t index, GeoPolyline &out) const {
  const Section *s = find(kind);
  if (!s || index >= s->count) return false;
  uint32_t pos = s->offset;
  for (uint16_t i = 0; i < s->count; i++) {
    uint16_t n = readU16(m_data + pos);
    if (i == index) {
      out.count = n;
      // Legal only because the writer pads the count field to 4 bytes, so
      // this address is always 4-byte aligned.
      out.pts = (const GeoVertex *)(m_data + pos + 4);
      return true;
    }
    pos += 4 + (uint32_t)n * 8;
    if (pos > s->offset + s->length) return false;
  }
  return false;
}

const GeoNamedPoint *GeoBlob::namedPoints(GeoKind kind) const {
  if (kind != GEO_AIRFIELDS && kind != GEO_WAYPOINTS && kind != GEO_TOWNS) {
    return 0;
  }
  const Section *s = find(kind);
  if (!s) return 0;
  return (const GeoNamedPoint *)(m_data + s->offset);
}

const GeoRunway *GeoBlob::runways() const {
  const Section *s = find(GEO_RUNWAYS);
  if (!s) return 0;
  return (const GeoRunway *)(m_data + s->offset);
}

} // namespace radar
```

- [ ] **Step 8: Run the native tests**

Run: `pio test -e native -f test_geoblob -v`
Expected: 14 tests pass.

If `test_vertex_pointers_are_4_byte_aligned` fails, the **writer** is wrong,
not the reader — check the `u16 pad` after each polyline count in `blob.py`.

- [ ] **Step 9: Confirm it compiles for the device too**

Run: `pio run -e usb`
Expected: SUCCESS. This is the check that matters — `lib/radarcore` builds at
`gnu++11` on device and `gnu++17` natively, and this repo has already shipped
a break that only the device build caught.

- [ ] **Step 10: Run the whole suite and commit**

```bash
python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site
pio test -e native
pio run -e usb
git add lib/radarcore/geoblob.h lib/radarcore/geoblob.cpp \
        test/test_geoblob/ tools/boxradar-site/tools_make_fixture.py \
        tools/boxradar-site/tests/test_fixture_current.py
git commit -m "feat: portable geography blob reader with native tests

Zero copy: open() validates and records offsets, and every accessor points
into the caller's buffer. One allocation for the whole map instead of one per
record, which is only legal because the writer 4-byte aligns every vertex
array — asserted by a test that checks the pointers it hands out.

Multi-byte reads go through memcpy rather than pointer casts. Casting is
undefined behaviour and on Xtensa occasionally wrong in practice, while a
4-byte memcpy at an aligned address compiles to one load.

The fixture is a committed byte array, not a file the test opens, because
Unity runs with an unpredictable working directory. A Python test asserts the
fixture is still what the writer produces, so the C++ tests cannot pass
against a stale format."
```

---

### Task 3: Coastline into the package

`tools/build_coastline.py` needs no curation removed — it already selects
purely by bounding box — so this is a move, plus emitting the blob section
alongside the existing header.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/coastline.py`
- Test: `tools/boxradar-site/tests/test_coastline.py`
- Delete: `tools/build_coastline.py`

**Interfaces:**
- Produces:
  - `MAX_RANGE_NM = 50`, `MARGIN_NM = 15`, `MIN_FEATURE_KM = 2.0`, `SIMPLIFY_M = 500.0`
  - `query_box(lat, lon) -> tuple` — `(south, west, north, east)`, the Overpass order
  - `fetch(bbox, cache_dir) -> dict` — cached Overpass response
  - `segments(data, home_lat, home_lon) -> list[list[(lat, lon)]]` — filtered and simplified
  - `bbox_of(segment) -> tuple[float, float, float, float]` — `(minLat, maxLat, minLon, maxLon)`
  - `render_header(segments) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_coastline.py`:

```python
import math
import unittest

from boxradar_site.geo import coastline


class TestQueryBox(unittest.TestCase):
    def test_reach_is_range_plus_margin(self):
        s, w, n, e = coastline.query_box(51.9, 0.0)
        reach_deg = (coastline.MAX_RANGE_NM + coastline.MARGIN_NM) / 60.0
        self.assertAlmostEqual(n - 51.9, reach_deg, places=5)
        self.assertAlmostEqual(51.9 - s, reach_deg, places=5)

    def test_longitude_is_scaled_by_latitude(self):
        _, w, _, e = coastline.query_box(51.9, 0.0)
        reach_deg = (coastline.MAX_RANGE_NM + coastline.MARGIN_NM) / 60.0
        expected = reach_deg / math.cos(math.radians(51.9))
        self.assertAlmostEqual(e - 0.0, expected, places=4)


class TestBboxOf(unittest.TestCase):
    def test_bounds_a_segment(self):
        seg = [(51.0, -0.5), (52.0, 0.5), (51.5, 0.0)]
        self.assertEqual(coastline.bbox_of(seg), (51.0, 52.0, -0.5, 0.5))

    def test_single_point(self):
        self.assertEqual(coastline.bbox_of([(51.0, 0.0)]),
                         (51.0, 51.0, 0.0, 0.0))


class TestRenderHeader(unittest.TestCase):
    def test_emits_bboxes_because_the_header_format_carries_them(self):
        # The blob deliberately does NOT store bboxes — they are derived, and a
        # stored bbox that disagrees with its points gives a coastline that
        # silently fails to draw. The header keeps them only because the
        # current firmware expects them; phase 3b computes them at load.
        text = coastline.render_header([[(51.0, -0.5), (52.0, 0.5)]])
        self.assertIn("minLat", text)
        self.assertIn("51.00000f", text)
        self.assertIn("SEG_0_PTS", text)

    def test_declares_the_segment_table(self):
        text = coastline.render_header([[(51.0, 0.0), (51.1, 0.1)]])
        self.assertIn("static const Outline SEGMENTS[]", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.coastline'`

- [ ] **Step 3: Port the module**

Create `tools/boxradar-site/boxradar_site/geo/coastline.py` by moving the
contents of `tools/build_coastline.py`, keeping every comment (the
`MIN_FEATURE_KM` and `SIMPLIFY_M` reasoning, the Overpass cache keying on
bbox, and the note about bounding boxes being most of the render cost saving).
Restructure only as follows:

- module-level constants stay as they are
- `query_box`, `fetch`, `bbox_of` and `render_header` become public
- the segment filtering and simplification become `segments(data, home_lat, home_lon)`
- **no `main()`** — the CLI lives in `geo/__main__.py`
- `fetch` takes an explicit `cache_dir` rather than reading a module global,
  so tests never touch the real cache
- read the home position from the passed arguments, never from `config.h`

Verify the port by regenerating and diffing:

```bash
cd tools/boxradar-site
python3 - <<'PY'
import pathlib, sys
sys.path.insert(0, ".")
from boxradar_site.geo import coastline
repo = pathlib.Path("../..").resolve()
# HOME from include/config.h, as the old script read it
data = coastline.fetch(coastline.query_box(51.88501837, 0.23502732),
                       pathlib.Path("~/.cache/boxradar-coastline").expanduser())
segs = coastline.segments(data, 51.88501837, 0.23502732)
pathlib.Path("/tmp/coastline_new.h").write_text(coastline.render_header(segs))
print(f"{len(segs)} segments, {sum(len(s) for s in segs)} points")
PY
cd ../..
diff <(grep -c 'f,' src/ui/coastline_data.h) <(grep -c 'f,' /tmp/coastline_new.h)
```

Expected: `124 segments, 1918 points` and matching vertex counts, per the
header's own generated comment.

- [ ] **Step 4: Run to verify passing**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 158 tests

- [ ] **Step 5: Retire the old script and commit**

```bash
git rm tools/build_coastline.py
git add tools/boxradar-site/boxradar_site/geo/coastline.py \
        tools/boxradar-site/tests/test_coastline.py
git commit -m "feat: move coastline generation into boxradar_site.geo

A move, not a redesign: build_coastline.py already selected purely by bounding
box, so there was no curation to remove. fetch() now takes an explicit cache
directory and home comes from arguments rather than config.h, which is what
lets it be tested and what lets the Pi generate for any site."
```

---

### Task 4: Point references, and the whole blob

Transcribes `include/location.h` into the selection config, so the blob can
carry airfields, runways, fixes and towns. Pickers over OurAirports and
GeoNames are phase 4; this is the data path.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/points.py`
- Test: `tools/boxradar-site/tests/test_points.py`
- Modify: `boxradar_site/geo/selection.example.json`
- Modify: `boxradar_site/geo/selection.py`
- Modify: `boxradar_site/geo/__main__.py`

**Interfaces:**
- `selection.Selection` gains `airfields`, `runways`, `waypoints`, `towns`,
  each a list of the tuples `blob.write` expects
- `points.render_header(sel) -> str` — regenerates `include/location.h`
- `__main__.py` gains `--blob PATH` on the `build` command

- [ ] **Step 1: Extend the selection config**

Add to `boxradar_site/geo/selection.example.json`, transcribed from
`include/location.h` — copy the actual coordinates out of that file rather
than retyping them, and keep the comments' ICAO ordering:

```json
  "airfields": [["EGSS", 51.885, 0.235]],
  "runways": [[51.8795, 0.2216, 51.8905, 0.2493]],
  "waypoints": [["LOREL", 51.9825, -0.2136], ["ABBOT", 52.0842, 0.6383]],
  "towns": [["STVG", 51.9019, -0.2019]]
```

**Use the real values from `include/location.h`**, all of them — the example
above is shape, not data. There are 10 airfields, 4 waypoints and 7 towns.

- [ ] **Step 2: Write the failing tests**

Create `tools/boxradar-site/tests/test_points.py`:

```python
import pathlib
import unittest

from boxradar_site.geo import blob, points, selection

EXAMPLE = (pathlib.Path(__file__).resolve().parents[1]
           / "boxradar_site" / "geo" / "selection.example.json")
REPO = pathlib.Path(__file__).resolve().parents[3]
LOCATION_H = REPO / "include" / "location.h"


class TestSelectionCarriesPoints(unittest.TestCase):
    def test_example_has_the_current_sites_references(self):
        sel = selection.load(EXAMPLE)
        self.assertEqual(len(sel.airfields), 10)
        self.assertEqual(len(sel.waypoints), 4)
        self.assertEqual(len(sel.towns), 7)
        self.assertGreater(len(sel.runways), 0)

    def test_every_name_fits_the_blob_field(self):
        sel = selection.load(EXAMPLE)
        for group in (sel.airfields, sel.waypoints, sel.towns):
            for name, _, _ in group:
                self.assertLessEqual(len(name), blob.MAX_NAME_CHARS, name)

    def test_points_default_to_empty(self):
        sel = selection.Selection(51.9, 0.0, 65.0, [])
        self.assertEqual(sel.airfields, [])
        self.assertEqual(sel.towns, [])


@unittest.skipUnless(LOCATION_H.exists(), "needs include/location.h")
class TestReproducesLocationHeader(unittest.TestCase):
    def test_same_number_of_records_as_the_committed_header(self):
        # The transcription must be faithful, so the first thing verified is
        # "nothing moved" rather than "did I remember everything".
        text = LOCATION_H.read_text()
        sel = selection.load(EXAMPLE)
        for marker, group in (("AIRFIELDS[]", sel.airfields),
                              ("WAYPOINTS[]", sel.waypoints),
                              ("TOWNS[]", sel.towns)):
            self.assertIn(marker, text)
            block = text.split(marker, 1)[1].split("};", 1)[0]
            self.assertEqual(block.count("{"), len(group), marker)

    def test_generated_header_declares_the_same_arrays(self):
        sel = selection.load(EXAMPLE)
        generated = points.render_header(sel)
        for marker in ("AIRFIELDS[]", "RUNWAYS[]", "WAYPOINTS[]", "TOWNS[]"):
            self.assertIn(marker, generated)


class TestBlobSections(unittest.TestCase):
    def test_round_trips_through_the_blob(self):
        sel = selection.load(EXAMPLE)
        data = blob.write(sel.home_lat, sel.home_lon, {
            blob.KIND_AIRFIELDS: sel.airfields,
            blob.KIND_RUNWAYS: sel.runways,
            blob.KIND_WAYPOINTS: sel.waypoints,
            blob.KIND_TOWNS: sel.towns,
        })
        got = blob.read(data)["sections"]
        self.assertEqual([n for n, _, _ in got[blob.KIND_AIRFIELDS]],
                         [n for n, _, _ in sel.airfields])
        self.assertEqual(len(got[blob.KIND_TOWNS]), len(sel.towns))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Extend `selection.py`**

Add to `Selection.__init__` four keyword arguments defaulting to `None` and
stored as lists: `airfields`, `runways`, `waypoints`, `towns`. In `load()`,
read them with a shared validator:

```python
def _points(raw, key, arity, path):
    """Validate a list of fixed-arity tuples. Raises with the offending row."""
    entries = raw.get(key, [])
    if not isinstance(entries, list):
        raise ValueError(f"{path}: {key} must be a list")
    out = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, (list, tuple)) or len(entry) != arity:
            raise ValueError(f"{path}: {key}[{i}] must have {arity} fields")
        out.append(tuple(entry))
    return out
```

Call it as `_points(raw, "airfields", 3, path)`, `("runways", 4)`,
`("waypoints", 3)`, `("towns", 3)`.

- [ ] **Step 4: Write `points.py`**

Create `tools/boxradar-site/boxradar_site/geo/points.py` emitting
`include/location.h` in its current shape: the `AirfieldRef`, `RunwayAxis`,
`Waypoint` and `TownRef` struct definitions with their existing explanatory
comments preserved verbatim, then the four arrays. Read the committed
`include/location.h` and reproduce its structure exactly — including the notes
that headings are TRUE not magnetic, that neither the waypoint nor town array
may be empty, and where the coordinates come from.

- [ ] **Step 5: Wire `--blob` into the CLI**

In `boxradar_site/geo/__main__.py`, extend the `build` branch so it can write
either or both outputs:

```python
    if args.blob:
        from . import blob as blobmod
        sections = {
            blobmod.KIND_AIRSPACE: [[(lat, lon) for lon, lat in ring]
                                    for _, ring in outlines],
            blobmod.KIND_AIRFIELDS: sel.airfields,
            blobmod.KIND_RUNWAYS: sel.runways,
            blobmod.KIND_WAYPOINTS: sel.waypoints,
            blobmod.KIND_TOWNS: sel.towns,
        }
        data = blobmod.write(sel.home_lat, sel.home_lon, sections)
        pathlib.Path(args.blob).write_bytes(data)
        print(f"wrote {args.blob}: {len(data)} bytes", file=sys.stderr)
```

Add `p.add_argument("--blob", help="also write the binary geography blob")`.
Note the `[(lat, lon) for lon, lat in ring]` flip: `outlines` carries
`[lon, lat]` from the GeoJSON convention, the blob stores `lat, lon` to match
the firmware's `Vertex`.

Coastline is added to the same dict once Task 3's `segments()` is reachable
from the CLI; do that in this step too, gated on `--coastline` being requested,
so a build without an Overpass fetch still works.

- [ ] **Step 6: Generate a real blob and check its size**

```bash
cd tools/boxradar-site
python3 -m boxradar_site.geo build \
  --selection boxradar_site/geo/selection.example.json \
  --out /tmp/airspace_check.h --blob /tmp/site.bin
ls -l /tmp/site.bin
cd ../..
```

Expected: a few KB without coastline. Record the number — phase 3b needs it
against the 128KB LittleFS partition and the free heap.

- [ ] **Step 7: Full verification and commit**

```bash
python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site
pio test -e native
pio run -e usb
git add -A
git commit -m "feat: point references in the selection config and the blob

Transcribes include/location.h into the selection config so airfields,
runways, fixes and towns reach the blob. Pickers over OurAirports and GeoNames
are phase 4; this is the data path, and the test asserts the transcription has
the same record counts as the committed header."
```

---

### Task 5: Document the format

**Files:**
- Modify: `SPEC.md`
- Modify: `README.md`
- Modify: `tools/boxradar-site/README.md`

- [ ] **Step 1: Add the format to SPEC.md**

Append a `## Geography blob` section to `SPEC.md` containing the offset table
from the top of this plan, plus the three decisions and their reasons: 4-byte
alignment enabling zero-copy `const Vertex*`, fixed-width names instead of a
string arena, and no derived data (coastline bboxes computed at load).

State plainly that the firmware does not read it yet.

- [ ] **Step 2: Note it in both READMEs**

In `tools/boxradar-site/README.md`, add a `## Geography` section covering
`geo list`, `geo suggest`, `geo build --out` and `geo build --blob`, and that
the blob is written but not yet consumed.

In the repo `README.md` Layout block, add `lib/radarcore/geoblob.{h,cpp}` to
the `lib/radarcore/` description.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: specify the geography blob format

Records why the format is the shape it is: 4-byte alignment is what allows
zero-copy const Vertex* into the received buffer, names are fixed-width
because the longest label is five characters, and nothing derived is stored
because a bbox that disagrees with its own points fails silently."
```

---

## Notes for whoever executes this

**Alignment is the format's load-bearing property.** If a test that checks
vertex pointer alignment fails, fix the writer's padding — never the test, and
never by copying vertices into an aligned buffer on the board. Copying would
double the RAM for the whole map on a device with no PSRAM and a 76.8KB sprite
already allocated.

**The CRC must match Python's `zlib.crc32`.** That is CRC-32 IEEE 802.3,
reflected, init `0xFFFFFFFF`, final xor. Getting this subtly wrong produces a
reader that rejects every real blob while passing any test that computes the
checksum the same wrong way — which is why the fixture is generated by the
Python writer rather than hand-written.

**`pio run -e usb` is not optional after touching `lib/radarcore`.** The
device builds at `gnu++11` and the native tests at `gnu++17`. This repo has
already shipped one break that only the device build caught, in exactly this
situation.

**The firmware still reads the headers.** Nothing in this phase changes what
the board draws, and `pio run -e usb` succeeding is a compile check, not
evidence the blob is right. The native tests are that evidence.
