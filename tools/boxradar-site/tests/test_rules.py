import pathlib
import unittest

from boxradar_site.geo import catalog, rules

YAML_PATH = (pathlib.Path.home() / ".cache/boxradar-airspace/airspace"
             / "airspace.yaml")
HOME_LAT, HOME_LON = 51.88501837203816, 0.23502731659204137
REACH_NM = 65.0

# What tools/build_airspace.py curated by hand, as feature names.
HAND_CURATED = {
    "LONDON STANSTED CTR", "LONDON STANSTED CTA",
    "LONDON LUTON CTR", "LONDON LUTON CTA",
    "LONDON CITY CTR", "LONDON CITY CTA",
    "LONDON GATWICK CTR", "LONDON GATWICK CTA",
    "SOUTHEND CTR", "SOUTHEND CTA",
    "LONDON CTR",
    "LONDON STANSTED TMZ",
}

# Measured 2026-08-08 as larger on screen than the panel is wide, AND of an
# allowed kind — so the size rule is the only thing standing between them and
# the map. These are what justify having a size rule at all.
OVERSIZE_CTAS = {"DAVENTRY CTA", "COTSWOLD CTA", "CLACTON CTA",
                 "PORTSMOUTH CTA", "WORTHING CTA", "NORTH SEA CTA"}


@unittest.skipUnless(YAML_PATH.exists(), f"needs {YAML_PATH}")
class TestSuggestAgainstRealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml
        with YAML_PATH.open() as f:
            features = yaml.safe_load(f).get("airspace", [])
        cls.cands = catalog.catalog(features, HOME_LAT, HOME_LON, REACH_NM)
        cls.accepted, cls.rejected = rules.suggest(cls.cands)
        cls.accepted_names = {c.name for c in cls.accepted}
        cls.reasons = {c.name: r for c, r in cls.rejected}

    def test_suggestion_is_a_small_set_not_everything(self):
        self.assertLess(len(self.accepted), 30)
        self.assertGreater(len(self.accepted), 8)

    def test_every_oversize_cta_is_rejected_for_size(self):
        # The point of the size rule: these are CTAs, so the kind allowlist
        # lets them through and only their on-screen extent stops them.
        for name in OVERSIZE_CTAS:
            self.assertIn(name, self.reasons, f"{name} should be rejected")
            self.assertIn("wide", self.reasons[name],
                          f"{name} rejected for the wrong reason")

    def test_the_london_tma_is_excluded_on_two_independent_grounds(self):
        # It is both the wrong kind and far wider than the panel. Kind is
        # checked first, so that is the reason reported — worth pinning, since
        # build_airspace.py excluded it by hand for the SIZE reason and it
        # would be easy to assume that is what catches it now.
        self.assertIn("kind TMA", self.reasons["LONDON TMA"])
        tma = next(c for c in self.cands if c.name == "LONDON TMA")
        self.assertGreater(tma.diag_nm, rules.DEFAULT_MAX_DIAG_NM)

    def test_the_stansted_tmz_survives(self):
        # An OTHER/TMZ, which a type-only allowlist would have dropped.
        self.assertIn("LONDON STANSTED TMZ", self.accepted_names)

    def test_atzs_are_rejected_by_kind(self):
        atzs = [c for c in self.cands if c.kind == "ATZ"]
        self.assertTrue(atzs)
        for c in atzs:
            self.assertIn("kind", self.reasons[c.name])

    def test_suggestion_covers_the_hand_curated_set(self):
        # The gate: whatever else the rules pick, they must not LOSE anything
        # a human chose deliberately.
        missing = HAND_CURATED - self.accepted_names
        self.assertEqual(missing, set(),
                         f"suggestion dropped hand-curated airspace: {missing}")

    def test_every_candidate_is_either_accepted_or_explained(self):
        self.assertEqual(len(self.accepted) + len(self.rejected),
                         len(self.cands))


class TestRuleThresholds(unittest.TestCase):
    class FakeCand:
        def __init__(self, kind, diag_nm, distance_nm):
            self.name = "X"
            self.kind = kind
            self.diag_nm = diag_nm
            self.distance_nm = distance_nm

    def test_accepts_within_all_limits(self):
        r = rules.SuggestRules()
        self.assertTrue(r.accepts(self.FakeCand("CTR", 10, 10)))

    def test_rejects_wrong_kind(self):
        r = rules.SuggestRules()
        self.assertIn("kind", r.reject_reason(self.FakeCand("ATZ", 10, 10)))

    def test_rejects_too_wide(self):
        r = rules.SuggestRules()
        self.assertIn("wide", r.reject_reason(self.FakeCand("CTA", 200, 10)))

    def test_rejects_too_far(self):
        r = rules.SuggestRules()
        self.assertIn("far", r.reject_reason(self.FakeCand("CTR", 10, 200)))

    def test_thresholds_are_configurable(self):
        r = rules.SuggestRules(kinds=("ATZ",), max_diag_nm=1000,
                               max_distance_nm=1000)
        self.assertTrue(r.accepts(self.FakeCand("ATZ", 500, 500)))


if __name__ == "__main__":
    unittest.main()
