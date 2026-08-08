import unittest

from boxradar_site import metar


class TestAsInt(unittest.TestCase):
    def test_none_gives_default(self):
        self.assertEqual(metar.as_int(None, -1), -1)

    def test_bool_is_not_a_number(self):
        # bool is an int subclass in Python; treating True as 1 would turn a
        # flag into a wind speed.
        self.assertEqual(metar.as_int(True, 0), 0)

    def test_float_truncates(self):
        self.assertEqual(metar.as_int(12.7), 12)

    def test_string_gives_default(self):
        self.assertEqual(metar.as_int("VRB", -1), -1)


class TestVisibility(unittest.TestCase):
    def test_plus_suffix_is_unlimited(self):
        # The API reports "6+" for 6 statute miles or more. 9999 is the METAR
        # convention for "10km or more".
        self.assertEqual(metar.visibility_m("6+"), 9999)

    def test_numeric_string_converts_from_statute_miles(self):
        self.assertEqual(metar.visibility_m("3"), 4827)

    def test_number_converts_and_clamps(self):
        self.assertEqual(metar.visibility_m(2), 3218)
        self.assertEqual(metar.visibility_m(10), 9999)

    def test_garbage_is_unlimited_not_zero(self):
        # Zero would render as fog. Unknown must not look like the worst case.
        self.assertEqual(metar.visibility_m("who knows"), 9999)
        self.assertEqual(metar.visibility_m(None), 9999)


class TestCeiling(unittest.TestCase):
    def test_no_clouds(self):
        self.assertEqual(metar.ceiling([]), (0, "NCD"))
        self.assertEqual(metar.ceiling(None), (0, "NCD"))

    def test_few_only_has_no_ceiling_but_reports_cover(self):
        # 0 feet means no ceiling, which is NOT the same as no cloud.
        self.assertEqual(metar.ceiling([{"cover": "FEW", "base": 1200}]),
                         (0, "FEW"))

    def test_ceiling_is_lowest_bkn_or_ovc_cover_is_lowest_any(self):
        clouds = [{"cover": "FEW", "base": 1200},
                  {"cover": "BKN", "base": 2500},
                  {"cover": "OVC", "base": 4000}]
        self.assertEqual(metar.ceiling(clouds), (2500, "FEW"))

    def test_ignores_non_dict_layers(self):
        self.assertEqual(metar.ceiling([None, {"cover": "OVC", "base": 900}]),
                         (900, "OVC"))


class TestPickRunway(unittest.TestCase):
    RWYS = [("04", 43), ("22", 223)]

    def test_variable_wind_gives_no_runway(self):
        self.assertEqual(metar.pick_runway("VRB", 10, self.RWYS), ("", False))

    def test_missing_wind_gives_no_runway(self):
        self.assertEqual(metar.pick_runway(None, 10, self.RWYS), ("", False))

    def test_bool_is_not_a_direction(self):
        self.assertEqual(metar.pick_runway(True, 10, self.RWYS), ("", False))

    def test_empty_runway_table_gives_no_runway(self):
        # Reachable now that the proxy serves stations with no configured
        # runways. max() on an empty sequence would raise.
        self.assertEqual(metar.pick_runway(40, 10, []), ("", False))

    def test_greatest_headwind_component_wins(self):
        self.assertEqual(metar.pick_runway(40, 12, self.RWYS), ("04", True))
        self.assertEqual(metar.pick_runway(220, 12, self.RWYS), ("22", True))

    def test_light_wind_is_not_confident(self):
        # Confidence is not about the arithmetic; it is about whether wind is
        # deciding the runway at all.
        self.assertEqual(metar.pick_runway(40, 5, self.RWYS), ("04", False))

    def test_calm_threshold_is_inclusive_and_configurable(self):
        self.assertEqual(metar.pick_runway(40, 7, self.RWYS), ("04", True))
        self.assertEqual(metar.pick_runway(40, 7, self.RWYS, calm_kt=10),
                         ("04", False))


class TestNormalise(unittest.TestCase):
    RWYS = [("04", 43), ("22", 223)]

    def test_full_observation(self):
        obs = {"icaoId": "EGSS", "wdir": 43, "wspd": 12, "wgst": 20,
               "visib": "6+", "clouds": [{"cover": "BKN", "base": 2500}],
               "altim": 1013, "temp": 14, "obsTime": 1754639400}
        self.assertEqual(metar.normalise(obs, self.RWYS), {
            "id": "EGSS", "wdir": 43, "wspd": 12, "gust": 20, "vis": 9999,
            "ceil": 2500, "cov": "BKN", "qnh": 1013, "temp": 14,
            "rwy": "04", "conf": 1, "obs": 1754639400,
        })

    def test_variable_wind_direction_is_minus_one_not_zero(self):
        # 0 would render as due north.
        out = metar.normalise({"icaoId": "EGSS", "wdir": "VRB"}, self.RWYS)
        self.assertEqual(out["wdir"], -1)
        self.assertEqual(out["rwy"], "")
        self.assertEqual(out["conf"], 0)

    def test_empty_observation_yields_every_key(self):
        # The firmware's struct has no optional fields; every key must exist.
        out = metar.normalise({}, [])
        self.assertEqual(set(out), {"id", "wdir", "wspd", "gust", "vis",
                                    "ceil", "cov", "qnh", "temp", "rwy",
                                    "conf", "obs"})
        self.assertEqual(out["id"], "")
        self.assertEqual(out["cov"], "NCD")
        self.assertEqual(out["vis"], 9999)

    def test_null_gust_becomes_zero(self):
        out = metar.normalise({"icaoId": "EGSS", "wgst": None}, self.RWYS)
        self.assertEqual(out["gust"], 0)


class TestEnvelope(unittest.TestCase):
    def test_shape_matches_what_loadmetar_parses(self):
        # lib/radarcore/metar.cpp iterates root["stations"] matching on "id".
        env = metar.envelope([{"id": "EGSS"}], 1754640000)
        self.assertEqual(env, {"t": 1754640000, "stale": 0,
                               "stations": [{"id": "EGSS"}]})

    def test_stale_flag(self):
        env = metar.envelope([], 1754640000, stale=True)
        self.assertEqual(env["stale"], 1)


if __name__ == "__main__":
    unittest.main()
