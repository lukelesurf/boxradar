"""Runway headings derived from thresholds.

The expected values are the ones curated by hand in the deployed
/etc/boxradar-site/config.json. EGSS 04 is the case worth keeping: the dataset
publishes le_heading_degT=44, the thresholds give 43, and 43 is what was
entered by hand — the coordinates win, exactly as datasets.runways() documents.
"""

import pathlib
import tempfile
import unittest

from boxradar_config import datasets, headings

RUNWAYS = '''"id","airport_ref","airport_ident","length_ft","width_ft","surface","lighted","closed","le_ident","le_latitude_deg","le_longitude_deg","le_elevation_ft","le_heading_degT","le_displaced_threshold_ft","he_ident","he_latitude_deg","he_longitude_deg","he_elevation_ft","he_heading_degT","he_displaced_threshold_ft"
1,1,"EGSS",10000,150,"ASP",1,0,"04",51.875081,0.219933,321,44,0,"22",51.895166,0.250050,336,224,0
2,2,"EGGW",7087,150,"ASP",1,0,"07",51.872002,-0.383550,510,73.6,0,"25",51.877201,-0.353333,526,253.6,0
3,3,"EGMC",6089,118,"ASP",1,0,"05",51.56719970703125,0.6862679719924927,49,54,571,"23",51.575599670410156,0.7049959897994995,37,234,479
4,1,"EGSS",3000,75,"GRS",0,1,"09",51.88,0.22,320,90,0,"27",51.88,0.25,320,270,0
5,4,"EGSC",2900,100,"GRS",0,0,"NOEND",52.2,0.17,40,90,0,"","","",,,
'''


class HeadingCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache = pathlib.Path(self.dir.name)
        root = datasets.dataset_dir(self.cache)
        root.mkdir(parents=True)
        (root / "runways.csv").write_text(RUNWAYS)


class TestBearing(HeadingCase):
    def test_due_north(self):
        self.assertAlmostEqual(headings.bearing(51.0, 0.0, 52.0, 0.0), 0.0,
                               places=6)

    def test_due_east_is_ninety_at_the_equator(self):
        self.assertAlmostEqual(headings.bearing(0.0, 0.0, 0.0, 1.0), 90.0,
                               places=6)

    def test_result_is_normalised_not_negative(self):
        # Due west is 270, not -90. A negative heading would compare wrongly
        # against wind direction in pick_runway().
        self.assertAlmostEqual(headings.bearing(0.0, 1.0, 0.0, 0.0), 270.0,
                               places=6)


class TestMetarRunways(HeadingCase):
    def test_stansted_matches_the_hand_curated_table(self):
        self.assertEqual(headings.metar_runways(self.cache, "EGSS"),
                         [("04", 43), ("22", 223)])

    def test_thresholds_beat_the_published_heading(self):
        # The fixture publishes le_heading_degT=44 for EGSS 04. The threshold
        # coordinates give 43, and 43 is the hand-entered value.
        got = dict(headings.metar_runways(self.cache, "EGSS"))
        self.assertEqual(got["04"], 43)

    def test_luton_matches(self):
        self.assertEqual(headings.metar_runways(self.cache, "EGGW"),
                         [("07", 74), ("25", 254)])

    def test_southend_matches(self):
        self.assertEqual(headings.metar_runways(self.cache, "EGMC"),
                         [("05", 54), ("23", 234)])

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(headings.metar_runways(self.cache, "egss"),
                         [("04", 43), ("22", 223)])

    def test_closed_runways_are_excluded(self):
        # EGSS 09/27 is closed=1 in the fixture.
        got = dict(headings.metar_runways(self.cache, "EGSS"))
        self.assertNotIn("09", got)

    def test_a_runway_missing_an_end_is_skipped(self):
        # EGSC NOEND has no he threshold, so it has no axis.
        self.assertEqual(headings.metar_runways(self.cache, "EGSC"), [])

    def test_an_unknown_station_gives_nothing(self):
        self.assertEqual(headings.metar_runways(self.cache, "ZZZZ"), [])
