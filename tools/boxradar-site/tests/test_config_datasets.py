"""The reference datasets and their cache.

Run against small fixtures rather than the real 32MB download, but the fixture
rows are copied from the real files — including the two BKY navaids, which is
the case that matters: OurAirports idents are not globally unique, so a picker
that searched by ident without a bounding box could put a Côte d'Ivoire VOR on
an Essex map.
"""

import io
import pathlib
import tempfile
import unittest
import zipfile

from boxradar_config import datasets

# (south, north, west, east) — roughly 65nm around north Essex.
BOX = (50.82, 52.99, -1.72, 1.79)

AIRPORTS = '''"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code","gps_code"
1,"EGSS","large_airport","London Stansted Airport",51.884998,0.235,348,"EU","GB","GB-ENG","London","yes","EGSS","STN","EGSS"
2,"EGGW","large_airport","London Luton Airport",51.874722,-0.368333,526,"EU","GB","GB-ENG","London","yes","EGGW","LTN","EGGW"
3,"EGSC","medium_airport","Cambridge Airport",52.205,0.175,47,"EU","GB","GB-ENG","Cambridge","no","EGSC","CBG","EGSC"
4,"EGTR","small_airport","Elstree Airfield",51.655800,-0.325556,332,"EU","GB","GB-ENG","Watford","no","EGTR","","EGTR"
5,"GB-0123","small_airport","Someone's Field",51.9,0.1,100,"EU","GB","GB-ENG","","no","","",""
6,"EGPF","large_airport","Glasgow Airport",55.871899,-4.43306,26,"EU","GB","GB-SCT","Glasgow","yes","EGPF","GLA","EGPF"
7,"XXXX","heliport","A Hospital Pad",51.9,0.05,50,"EU","GB","GB-ENG","","no","","",""
'''

RUNWAYS = '''"id","airport_ref","airport_ident","length_ft","width_ft","surface","lighted","closed","le_ident","le_latitude_deg","le_longitude_deg","le_elevation_ft","le_heading_degT","le_displaced_threshold_ft","he_ident","he_latitude_deg","he_longitude_deg","he_elevation_ft","he_heading_degT","he_displaced_threshold_ft"
1,1,"EGSS",10000,150,"ASP",1,0,"04",51.875081,0.219933,321,42.9,0,"22",51.895166,0.250050,336,222.9,0
2,2,"EGGW",7087,150,"ASP",1,0,"07",51.872002,-0.383550,510,73.6,0,"25",51.877201,-0.353333,túl,253.6,0
3,1,"EGSS",3000,75,"GRS",0,1,"09",51.88,0.22,320,90,0,"27",51.88,0.25,320,270,0
4,3,"EGSC",6447,150,"ASP",1,0,"05",52.199,0.166,38,52.5,0,"23",52.211,0.184,45,232.5,0
5,3,"EGSC",2900,100,"GRS",0,0,"NOEND",52.2,0.17,40,90,0,"","","",,,
'''

NAVAIDS = '''"id","filename","ident","name","type","frequency_khz","latitude_deg","longitude_deg","elevation_ft","iso_country","dme_frequency_khz","dme_channel","slaved_variation_deg","magnetic_variation_deg","usageType","power","associated_airport"
86119,"Bouake_VOR-DME_CI","BKY","Bouake","VOR-DME",115100,7.747280,-5.074940,1230,"CI",115100,"098X",,,,"BOTH","HIGH","DIBK"
86120,"Barkway_VOR-DME_GB","BKY","Barkway","VOR-DME",116250,51.989700,0.061944,486,"GB",116250,"109Y",,,,"BOTH","HIGH","EGSS"
86121,"Brookmans_Park_VOR-DME_GB","BPK","Brookmans Park","VOR-DME",117500,51.749699,-0.106667,300,"GB",117500,"122X",,,,"BOTH","HIGH",""
86122,"Glasgow_VOR_GB","GOW","Glasgow","VOR",115400,55.871899,-4.433060,26,"GB",,,,,,"BOTH","HIGH",""
'''

# Headerless TSV, GeoNames column order.
TOWNS = "\n".join("\t".join(row) for row in [
    ["2636940", "Stevenage", "Stevenage", "", "51.90224", "-0.20256", "P",
     "PPL", "GB", "", "ENG", "", "", "", "91774"],
    ["2647044", "Hertford", "Hertford", "", "51.79588", "-0.07854", "P",
     "PPLA2", "GB", "", "ENG", "", "", "", "25847"],
    ["1000001", "Tiny Hamlet", "Tiny Hamlet", "", "51.88", "0.10", "P",
     "PPL", "GB", "", "ENG", "", "", "", "180"],
    ["1000002", "Some Hill", "Some Hill", "", "51.88", "0.11", "T",
     "HLL", "GB", "", "ENG", "", "", "", "0"],
    ["1000003", "Glasgow", "Glasgow", "", "55.86515", "-4.25763", "P",
     "PPLA", "GB", "", "SCT", "", "", "", "1000000"],
]) + "\n"


class DatasetCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache = pathlib.Path(self.dir.name)
        root = datasets.dataset_dir(self.cache)
        root.mkdir(parents=True)
        (root / "airports.csv").write_text(AIRPORTS)
        (root / "runways.csv").write_text(RUNWAYS)
        (root / "navaids.csv").write_text(NAVAIDS)
        (root / "GB.txt").write_text(TOWNS)


class TestAirfields(DatasetCase):
    def test_large_and_medium_by_default(self):
        got = {a.ident for a in datasets.airfields(self.cache, BOX)}
        self.assertEqual(got, {"EGSS", "EGGW", "EGSC"})

    def test_small_fields_are_available_on_request(self):
        got = {a.ident for a in datasets.airfields(
            self.cache, BOX, types=datasets.AIRPORT_TYPES)}
        self.assertIn("EGTR", got)

    def test_a_field_outside_the_box_is_excluded(self):
        got = {a.ident for a in datasets.airfields(
            self.cache, BOX, types=datasets.AIRPORT_TYPES)}
        self.assertNotIn("EGPF", got)  # Glasgow

    def test_a_synthetic_ident_is_excluded(self):
        # GB-0123 has no ICAO code, and the blob label has to be the ICAO.
        got = {a.ident for a in datasets.airfields(
            self.cache, BOX, types=datasets.AIRPORT_TYPES)}
        self.assertNotIn("GB-0123", got)

    def test_heliports_are_not_offered(self):
        got = {a.ident for a in datasets.airfields(
            self.cache, BOX, types=datasets.AIRPORT_TYPES)}
        self.assertNotIn("XXXX", got)

    def test_largest_class_comes_first(self):
        got = datasets.airfields(self.cache, BOX)
        self.assertEqual(got[0].kind, "large_airport")

    def test_the_coordinates_match_location_h(self):
        by_ident = {a.ident: a for a in datasets.airfields(self.cache, BOX)}
        self.assertAlmostEqual(by_ident["EGSS"].lat, 51.885, places=4)
        self.assertAlmostEqual(by_ident["EGSS"].lon, 0.235, places=4)


class TestRunways(DatasetCase):
    def test_both_thresholds_become_an_axis(self):
        got = datasets.runways(self.cache, ["EGSS"])
        self.assertEqual(len(got), 1)
        rwy = got[0]
        self.assertEqual(rwy.ident, "04/22")
        self.assertAlmostEqual(rwy.lat0, 51.875081, places=5)
        self.assertAlmostEqual(rwy.lon1, 0.250050, places=5)

    def test_a_closed_runway_is_excluded(self):
        self.assertEqual([r.ident for r in datasets.runways(self.cache,
                                                            ["EGSS"])],
                         ["04/22"])

    def test_a_runway_missing_an_end_has_no_axis(self):
        # The axis is the two points, never a published heading, so one end is
        # not enough.
        got = [r.ident for r in datasets.runways(self.cache, ["EGSC"])]
        self.assertEqual(got, ["05/23"])

    def test_only_the_requested_airfields(self):
        got = {r.airport for r in datasets.runways(self.cache, ["EGSS"])}
        self.assertEqual(got, {"EGSS"})

    def test_a_malformed_row_does_not_kill_the_file(self):
        # EGGW's row has a corrupt elevation column; its coordinates are fine.
        got = datasets.runways(self.cache, ["EGGW"])
        self.assertEqual(len(got), 1)

    def test_grouped_by_airfield(self):
        got = datasets.runways(self.cache, ["EGSS", "EGSC"])
        self.assertEqual([r.airport for r in got], ["EGSC", "EGSS"])
        self.assertEqual(got[0].length_ft, 6447.0)


class TestNavaids(DatasetCase):
    def test_the_box_disambiguates_a_reused_ident(self):
        # BKY is Barkway AND Bouake. Only one of them is in Hertfordshire.
        got = datasets.navaids(self.cache, BOX)
        bky = [n for n in got if n.ident == "BKY"]
        self.assertEqual(len(bky), 1)
        self.assertEqual(bky[0].name, "Barkway")
        self.assertAlmostEqual(bky[0].lat, 51.98970, places=4)

    def test_a_navaid_outside_the_box_is_excluded(self):
        got = {n.ident for n in datasets.navaids(self.cache, BOX)}
        self.assertNotIn("GOW", got)  # Glasgow

    def test_brookmans_park_matches_location_h(self):
        by_ident = {n.ident: n for n in datasets.navaids(self.cache, BOX)}
        self.assertAlmostEqual(by_ident["BPK"].lat, 51.74970, places=4)
        self.assertAlmostEqual(by_ident["BPK"].lon, -0.10667, places=4)


class TestTowns(DatasetCase):
    def test_populated_places_only(self):
        got = {t.name for t in datasets.towns(self.cache, BOX)}
        self.assertNotIn("Some Hill", got)  # feature class T

    def test_largest_population_first(self):
        got = datasets.towns(self.cache, BOX)
        self.assertEqual(got[0].name, "Stevenage")

    def test_population_ranks_but_does_not_gate(self):
        # A village you happen to know is a legitimate ground reference.
        got = {t.name for t in datasets.towns(self.cache, BOX)}
        self.assertIn("Tiny Hamlet", got)

    def test_a_floor_can_be_asked_for(self):
        got = {t.name for t in datasets.towns(self.cache, BOX,
                                              min_population=1000)}
        self.assertNotIn("Tiny Hamlet", got)
        self.assertIn("Hertford", got)

    def test_outside_the_box_is_excluded(self):
        got = {t.name for t in datasets.towns(self.cache, BOX)}
        self.assertNotIn("Glasgow", got)

    def test_the_coordinates_are_close_to_location_h(self):
        by_name = {t.name: t for t in datasets.towns(self.cache, BOX)}
        self.assertAlmostEqual(by_name["Hertford"].lat, 51.79574, places=3)


class TestCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache = pathlib.Path(self.dir.name)

    def test_require_raises_before_a_download(self):
        with self.assertRaises(datasets.DatasetMissing):
            datasets.require("airports", self.cache)

    def test_age_is_none_before_a_download(self):
        self.assertIsNone(datasets.age_days("airports", self.cache))

    def test_fetch_writes_the_file(self):
        def opener(url):
            self.assertIn("airports.csv", url)
            return io.BytesIO(AIRPORTS.encode())

        datasets.fetch("airports", self.cache, opener=opener)
        self.assertEqual(datasets.path_for("airports", self.cache).read_text(),
                         AIRPORTS)
        self.assertIsNotNone(datasets.age_days("airports", self.cache))

    def test_fetch_extracts_the_zip_member(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("GB.txt", TOWNS)
            archive.writestr("readme.txt", "ignore me")
        buffer.seek(0)

        datasets.fetch("towns", self.cache, opener=lambda url: io.BytesIO(
            buffer.getvalue()))
        self.assertEqual(datasets.path_for("towns", self.cache).read_text(),
                         TOWNS)

    def test_no_partial_file_is_left_where_the_parser_looks(self):
        datasets.fetch("airports", self.cache,
                       opener=lambda url: io.BytesIO(AIRPORTS.encode()))
        names = {p.name for p in datasets.dataset_dir(self.cache).iterdir()}
        self.assertEqual(names, {"airports.csv"})

    def test_no_partial_file_is_left_after_a_zip_extraction_either(self):
        datasets.fetch("towns", self.cache, opener=lambda url: io.BytesIO(
            self.zipped()))
        names = {p.name for p in datasets.dataset_dir(self.cache).iterdir()}
        self.assertEqual(names, {"GB.txt"})

    def zipped(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("GB.txt", TOWNS)
        return buffer.getvalue()


class TestFetchProgress(unittest.TestCase):
    """Downloads are the slowest thing this UI does, and on a Pi over wifi the
    whole set is ~32MB. Reporting bytes as they land is what turns a page that
    looks hung into one that is visibly working.

    An empty cache, like TestCache — DatasetCase pre-populates the files these
    tests are trying to create.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cache = pathlib.Path(self.dir.name)

    class Sized(io.BytesIO):
        """A response that knows its length, as a real HTTP one does."""

        def __init__(self, payload):
            super().__init__(payload)
            self.headers = {"Content-Length": str(len(payload))}

    def test_progress_reports_bytes_against_a_total(self):
        payload = (AIRPORTS * 400).encode()
        seen = []
        datasets.fetch("airports", self.cache,
                       opener=lambda url: self.Sized(payload),
                       progress=lambda done, total: seen.append((done, total)))
        self.assertTrue(seen)
        self.assertTrue(all(total == len(payload) for _, total in seen))
        self.assertEqual(seen[-1][0], len(payload))

    def test_it_reads_in_chunks_rather_than_all_at_once(self):
        # Not a micro-optimisation: read() on the whole response held a 14MB
        # payload in memory, on a Pi with 906MB where a third is already gone
        # to the desktop. Chunking is also what makes progress possible at all.
        payload = (AIRPORTS * 400).encode()
        seen = []
        datasets.fetch("airports", self.cache,
                       opener=lambda url: self.Sized(payload),
                       progress=lambda done, total: seen.append(done))
        self.assertGreater(len(seen), 1,
                           "one progress call means it read the lot in one go")

    def test_a_response_without_a_length_reports_no_total(self):
        # Reporting a total it does not know would render as a bar that jumps
        # or sticks. None means "count up, no percentage".
        seen = []
        datasets.fetch("airports", self.cache,
                       opener=lambda url: io.BytesIO(AIRPORTS.encode()),
                       progress=lambda done, total: seen.append(total))
        self.assertTrue(all(total is None for total in seen), seen)

    def test_the_file_is_still_correct_with_progress_on(self):
        datasets.fetch("airports", self.cache,
                       opener=lambda url: io.BytesIO(AIRPORTS.encode()),
                       progress=lambda done, total: None)
        self.assertEqual(datasets.path_for("airports", self.cache).read_text(),
                         AIRPORTS)

    def test_fetching_without_a_progress_callback_still_works(self):
        datasets.fetch("airports", self.cache,
                       opener=lambda url: io.BytesIO(AIRPORTS.encode()))
        self.assertEqual(datasets.path_for("airports", self.cache).read_text(),
                         AIRPORTS)


if __name__ == "__main__":
    unittest.main()
