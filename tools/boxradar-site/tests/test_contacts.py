import struct
import unittest

from boxradar_site import contacts

# Home is the committed site, so ranges in these tests are recognisable.
HOME_LAT, HOME_LON = 51.88501837203816, 0.23502731659204137

# One degree of latitude is 60nm, so offsetting lat alone gives an exact,
# hand-checkable range without involving the longitude scale.
def at_range_nm(nm, **extra):
    """A minimal feed entry due north of home at `nm`."""
    entry = {"hex": "400001", "lat": HOME_LAT + nm / 60.0, "lon": HOME_LON,
             "seen": 1.0}
    entry.update(extra)
    return entry


class TestSelect(unittest.TestCase):
    def select(self, feed, limit=32):
        return contacts.select(feed, HOME_LAT, HOME_LON, limit)

    def test_orders_by_range_nearest_first(self):
        picked, total = self.select([at_range_nm(30), at_range_nm(5),
                                     at_range_nm(15)])
        self.assertEqual([round(c.range_nm) for c in picked], [5, 15, 30])
        self.assertEqual(total, 3)

    def test_drops_entries_without_a_position(self):
        picked, total = self.select([{"hex": "400001", "seen": 1.0},
                                     at_range_nm(5)])
        self.assertEqual(len(picked), 1)
        self.assertEqual(total, 1, "total counts what survived filtering")

    def test_drops_one_of_a_pair_missing_lon(self):
        picked, _ = self.select([{"hex": "a", "lat": HOME_LAT, "seen": 1.0}])
        self.assertEqual(picked, [])

    def test_drops_stale_contacts(self):
        # SEEN_DROP_S is 60; parse.cpp uses >, so exactly 60 is kept.
        picked, _ = self.select([at_range_nm(5, seen=61.0),
                                 at_range_nm(6, seen=60.0)])
        self.assertEqual(len(picked), 1)
        self.assertEqual(round(picked[0].range_nm), 6)

    def test_missing_seen_is_treated_as_fresh(self):
        entry = at_range_nm(5)
        del entry["seen"]
        picked, _ = self.select([entry])
        self.assertEqual(len(picked), 1)

    def test_cap_keeps_the_nearest_and_total_reports_the_truth(self):
        feed = [at_range_nm(nm) for nm in (40, 10, 20, 30)]
        picked, total = self.select(feed, limit=2)
        self.assertEqual([round(c.range_nm) for c in picked], [10, 20])
        self.assertEqual(total, 4, "total is pre-cap, so the cliff is visible")

    def test_limit_of_zero_yields_nothing_but_still_counts(self):
        picked, total = self.select([at_range_nm(5)], limit=0)
        self.assertEqual(picked, [])
        self.assertEqual(total, 1)


class TestFieldMapping(unittest.TestCase):
    """Field-for-field parity with lib/radarcore/parse.cpp."""

    def one(self, **extra):
        picked, _ = contacts.select([at_range_nm(5, **extra)],
                                    HOME_LAT, HOME_LON, 32)
        return picked[0]

    def test_tisb_hex_prefix_is_stripped(self):
        self.assertEqual(self.one(hex="~abc123").hex, 0xABC123)

    def test_callsign_is_space_trimmed(self):
        self.assertEqual(self.one(flight="BAW123  ").callsign, "BAW123")

    def test_squawk_keeps_leading_zeros(self):
        self.assertEqual(self.one(squawk="0100").squawk, "0100")

    def test_squawk_given_as_a_number_degrades_to_empty(self):
        # parse.cpp gets nullptr from a non-string and stores "" rather than
        # a mangled code; the wire form must not invent one either.
        self.assertEqual(self.one(squawk=100).squawk, "")

    def test_ground_is_a_string_altitude(self):
        c = self.one(alt_baro="ground")
        self.assertTrue(c.on_ground)
        self.assertEqual(c.alt_ft, 0)

    def test_airborne_altitude(self):
        c = self.one(alt_baro=2500)
        self.assertFalse(c.on_ground)
        self.assertEqual(c.alt_ft, 2500)

    def test_mlat_comes_from_the_message_type_not_the_airframe_type(self):
        c = self.one(type="mlat", t="B738")
        self.assertTrue(c.is_mlat)
        self.assertEqual(c.type, "B738", "t is the airframe, type is the source")

    def test_geom_rate_is_the_fallback_for_baro_rate(self):
        self.assertEqual(self.one(geom_rate=-1280).vert_rate_fpm, -1280)
        self.assertEqual(self.one(baro_rate=64, geom_rate=-1280).vert_rate_fpm,
                         64)


class TestPack(unittest.TestCase):
    def build(self, feed, limit=32):
        return contacts.build(feed, HOME_LAT, HOME_LON, limit)

    def test_header_is_twelve_bytes_so_records_start_aligned(self):
        self.assertEqual(contacts.HEADER_LEN % 4, 0)
        self.assertEqual(contacts.RECORD_LEN % 4, 0)

    def test_round_trip(self):
        feed = [at_range_nm(5, hex="400abc", flight="EZY42  ", t="A320",
                            squawk="7000", alt_baro=3000, gs=210.4,
                            track=183.7, baro_rate=-704, seen=2.5,
                            rssi=-21.5)]
        got = contacts.read(self.build(feed))
        self.assertEqual(got["total"], 1)
        c = got["contacts"][0]
        self.assertEqual(c["hex"], 0x400ABC)
        self.assertEqual(c["callsign"], "EZY42")
        self.assertEqual(c["type"], "A320")
        self.assertEqual(c["squawk"], "7000")
        self.assertEqual(c["alt_ft"], 3000)
        self.assertEqual(c["gs_kt"], 210)
        self.assertEqual(c["track_deg"], 183)
        self.assertEqual(c["vert_rate_fpm"], -704)
        self.assertEqual(c["seen_s"], 2)
        self.assertAlmostEqual(c["rssi"], -21.5, places=1)
        self.assertFalse(c["on_ground"])
        self.assertFalse(c["is_mlat"])

    def test_position_survives_the_round_trip_to_a_tenth_of_a_nm(self):
        feed = [at_range_nm(17.5)]
        c = contacts.read(self.build(feed))["contacts"][0]
        # 1e-7 degrees is ~0.6cm; the assertion is deliberately looser than
        # the encoding so it tests the encoding, not float formatting.
        self.assertAlmostEqual(c["lat"], HOME_LAT + 17.5 / 60.0, places=5)
        self.assertAlmostEqual(c["lon"], HOME_LON, places=5)

    def test_a_full_eight_character_callsign_is_not_truncated(self):
        c = contacts.read(self.build([at_range_nm(5, flight="ABCDEFGH")]))
        self.assertEqual(c["contacts"][0]["callsign"], "ABCDEFGH")

    def test_length_is_header_plus_records(self):
        feed = [at_range_nm(nm) for nm in (5, 10, 15)]
        self.assertEqual(len(self.build(feed)),
                         contacts.HEADER_LEN + 3 * contacts.RECORD_LEN)

    def test_capped_payload_still_reports_the_full_total(self):
        feed = [at_range_nm(nm) for nm in range(1, 40)]
        got = contacts.read(self.build(feed, limit=32))
        self.assertEqual(len(got["contacts"]), 32)
        self.assertEqual(got["total"], 39)

    def test_empty_feed_is_a_valid_header_with_no_records(self):
        got = contacts.read(self.build([]))
        self.assertEqual(got["contacts"], [])
        self.assertEqual(got["total"], 0)

    def test_magic_and_version_are_present(self):
        data = self.build([])
        self.assertEqual(data[:4], contacts.MAGIC)
        version, rec_len = struct.unpack_from("<HH", data, 4)
        self.assertEqual(version, contacts.VERSION)
        self.assertEqual(rec_len, contacts.RECORD_LEN)

    def test_reader_rejects_bad_magic(self):
        with self.assertRaises(ValueError):
            contacts.read(b"NOPE" + self.build([])[4:])

    def test_reader_rejects_a_record_length_it_does_not_know(self):
        data = bytearray(self.build([at_range_nm(5)]))
        struct.pack_into("<H", data, 6, contacts.RECORD_LEN + 4)
        with self.assertRaises(ValueError):
            contacts.read(bytes(data))


class TestClamping(unittest.TestCase):
    """Out-of-range values must saturate, never wrap into a plausible lie."""

    def field(self, name, **extra):
        data = contacts.build([at_range_nm(5, **extra)], HOME_LAT, HOME_LON, 32)
        return contacts.read(data)["contacts"][0][name]

    def test_absurd_altitude_saturates_rather_than_wrapping(self):
        self.assertEqual(self.field("alt_ft", alt_baro=10_000_000),
                         contacts.MAX_ALT_FT)

    def test_absurd_climb_rate_saturates(self):
        self.assertEqual(self.field("vert_rate_fpm", baro_rate=9_000_000),
                         contacts.MAX_VERT_RATE_FPM)

    def test_negative_groundspeed_floors_at_zero(self):
        self.assertEqual(self.field("gs_kt", gs=-5.0), 0)

    def test_track_wraps_into_range(self):
        self.assertEqual(self.field("track_deg", track=370.0), 10)

    def test_very_weak_signal_saturates(self):
        self.assertEqual(self.field("rssi", rssi=-200.0), contacts.MIN_RSSI)

    def test_overlong_callsign_is_truncated_to_the_field(self):
        self.assertEqual(self.field("callsign", flight="ABCDEFGHIJ"),
                         "ABCDEFGH")

    def test_overlong_type_is_truncated_to_the_field(self):
        self.assertEqual(self.field("type", t="TOOLONG"), "TOOL")


class TestAltitudeBand(unittest.TestCase):
    """The band is applied HERE, not on the board.

    The cap saturates continuously — a real feed runs 54-65 aircraft against
    32 slots — so a filter behind the cap would spend every slot and then hide
    most of them. These check that the band runs before the sort and the cap,
    and that the two ways it can be asked a nonsense question fail toward
    showing traffic rather than toward a blank scope.
    """

    def band(self, feed, low, high, limit=32):
        return contacts.select(feed, HOME_LAT, HOME_LON, limit,
                               alt_min=low, alt_max=high)

    def test_a_floor_drops_what_is_below_it(self):
        picked, total = self.band([at_range_nm(5, alt_baro=500),
                                   at_range_nm(10, alt_baro=5000)], 1000, 70000)
        self.assertEqual([c.alt_ft for c in picked], [5000])
        # Excluded traffic is not counted either: "+N" has to mean "aircraft
        # you asked for that did not fit", or it becomes a permanent number.
        self.assertEqual(total, 1)

    def test_a_ceiling_drops_what_is_above_it(self):
        picked, _ = self.band([at_range_nm(5, alt_baro=38000),
                               at_range_nm(10, alt_baro=3000)], 0, 10000)
        self.assertEqual([c.alt_ft for c in picked], [3000])

    def test_the_band_runs_before_the_cap_not_after(self):
        # Three low, one high, one slot. Filtering after the cap would take
        # the nearest (low, excluded) and return nothing at all.
        feed = [at_range_nm(1, alt_baro=200), at_range_nm(2, alt_baro=200),
                at_range_nm(3, alt_baro=200), at_range_nm(9, alt_baro=9000)]
        picked, total = self.band(feed, 1000, 70000, limit=1)
        self.assertEqual([c.alt_ft for c in picked], [9000])
        self.assertEqual(total, 1)

    def test_a_floor_of_zero_means_no_floor(self):
        # Baro altitude reads negative at a low airfield under high pressure.
        # A literal floor of 0 would hide ground traffic at the SHIPPED
        # setting, which is the worst place for a surprise.
        picked, _ = self.band([at_range_nm(5, alt_baro=-75)], 0, 70000)
        self.assertEqual([c.alt_ft for c in picked], [-75])

    def test_a_real_floor_does_drop_negative_altitudes(self):
        picked, _ = self.band([at_range_nm(5, alt_baro=-75)], 500, 70000)
        self.assertEqual(picked, [])

    def test_ground_traffic_is_governed_by_the_floor(self):
        onground = [at_range_nm(2, alt_baro="ground")]
        self.assertEqual(len(self.band(onground, 0, 70000)[0]), 1)
        self.assertEqual(self.band(onground, 1000, 70000)[0], [])

    def test_an_unknown_altitude_always_passes(self):
        # alt_baro simply absent lands as 0 through _number's default, so
        # without alt_known it would be indistinguishable from a genuine 0 and
        # a jet with a dropped altitude field would vanish behind any floor.
        entry = at_range_nm(5)
        entry.pop("alt_baro", None)
        picked, _ = self.band([entry], 20000, 30000)
        self.assertEqual(len(picked), 1)
        self.assertFalse(picked[0].alt_known)

    def test_a_boolean_altitude_is_not_a_number(self):
        # isinstance(True, int) is True in Python, so a stray `true` would
        # otherwise read as a known 1ft.
        picked, _ = self.band([at_range_nm(5, alt_baro=True)], 20000, 30000)
        self.assertEqual(len(picked), 1)
        self.assertFalse(picked[0].alt_known)

    def test_an_inverted_band_is_ignored_rather_than_obeyed(self):
        # Obeying it empties the scope, and an empty scope reads as a dead
        # board rather than as a setting someone typed. The firmware accepts
        # the pair because each field is validated alone; this is the backstop.
        feed = [at_range_nm(5, alt_baro=3000), at_range_nm(9, alt_baro=38000)]
        picked, total = self.band(feed, 40000, 1000)
        self.assertEqual(len(picked), 2)
        self.assertEqual(total, 2)

    def test_no_band_asked_for_behaves_as_before(self):
        feed = [at_range_nm(5, alt_baro=200), at_range_nm(9, alt_baro=41000)]
        picked, _ = contacts.select(feed, HOME_LAT, HOME_LON, 32)
        self.assertEqual(len(picked), 2)

    def test_build_passes_the_band_through(self):
        feed = [at_range_nm(5, alt_baro=200), at_range_nm(9, alt_baro=9000)]
        data = contacts.build(feed, HOME_LAT, HOME_LON, 32,
                              alt_min=1000, alt_max=70000)
        out = contacts.read(data)
        self.assertEqual([c["alt_ft"] for c in out["contacts"]], [9000])


class TestMlatFilter(unittest.TestCase):
    """Dropped on the Pi with the altitude band, and for the same reason.

    MLAT contacts occupy cap slots, so a draw-time filter would spend them and
    then hide the result. What these pin down is that hiding is a filter on
    the FEED — the contact never arrives — rather than a styling change, and
    that the excluded traffic leaves the total with it.
    """

    def mlat(self, feed, include, limit=32):
        return contacts.select(feed, HOME_LAT, HOME_LON, limit,
                               include_mlat=include)

    def test_mlat_is_included_by_default(self):
        picked, _ = contacts.select([at_range_nm(5, type="mlat")],
                                    HOME_LAT, HOME_LON, 32)
        self.assertEqual([c.is_mlat for c in picked], [True])

    def test_hiding_drops_them_from_the_feed_and_the_total(self):
        feed = [at_range_nm(5, type="mlat"), at_range_nm(9, type="adsb_icao")]
        picked, total = self.mlat(feed, include=False)
        self.assertEqual([c.is_mlat for c in picked], [False])
        self.assertEqual(total, 1)

    def test_hiding_frees_cap_slots_for_transmitted_positions(self):
        # Three MLAT nearer than the one ADS-B, one slot. This is the whole
        # argument for filtering ahead of the cap rather than behind it.
        feed = [at_range_nm(1, type="mlat"), at_range_nm(2, type="mlat"),
                at_range_nm(3, type="mlat"), at_range_nm(9, type="adsb_icao")]
        picked, total = self.mlat(feed, include=False, limit=1)
        self.assertEqual(len(picked), 1)
        self.assertFalse(picked[0].is_mlat)
        self.assertEqual(total, 1)

    def test_the_two_filters_compose(self):
        feed = [at_range_nm(2, type="mlat", alt_baro=9000),
                at_range_nm(3, type="adsb_icao", alt_baro=500),
                at_range_nm(4, type="adsb_icao", alt_baro=9000)]
        picked, _ = contacts.select(feed, HOME_LAT, HOME_LON, 32,
                                    alt_min=1000, alt_max=70000,
                                    include_mlat=False)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0].alt_ft, 9000)
        self.assertFalse(picked[0].is_mlat)

    def test_build_passes_the_switch_through(self):
        feed = [at_range_nm(5, type="mlat"), at_range_nm(9, type="adsb_icao")]
        out = contacts.read(contacts.build(feed, HOME_LAT, HOME_LON, 32,
                                           include_mlat=False))
        self.assertEqual([c["is_mlat"] for c in out["contacts"]], [False])
