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

    def test_unknown_section_kind_rejected(self):
        with self.assertRaises(ValueError):
            blob.write(51.9, 0.0, {99: [("X", 51.9, 0.0)]})


if __name__ == "__main__":
    unittest.main()
