import unittest

from boxradar_site.geo import outlines


def square(x0, y0, size):
    return [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
            [x0, y0 + size], [x0, y0]]


class TestMergeRings(unittest.TestCase):
    def test_single_ring_survives(self):
        merged = outlines.merge_rings([square(0, 51, 0.1)])
        self.assertEqual(len(merged), 1)

    def test_overlapping_rings_become_one(self):
        merged = outlines.merge_rings([square(0, 51, 0.1),
                                       square(0.05, 51, 0.1)])
        self.assertEqual(len(merged), 1)

    def test_disjoint_rings_stay_separate(self):
        # The Stansted TMZ is two lobes either side of the field, and the gap
        # between them is real airspace. Merging them would invent airspace.
        merged = outlines.merge_rings([square(0, 51, 0.1),
                                       square(5, 51, 0.1)])
        self.assertEqual(len(merged), 2)

    def test_rings_are_closed_lon_lat(self):
        ring = outlines.merge_rings([square(0, 51, 0.1)])[0]
        self.assertEqual(ring[0], ring[-1])
        lon, lat = ring[0]
        self.assertAlmostEqual(lat, 51, places=1)


class TestBuildOutlines(unittest.TestCase):
    def test_single_shape_keeps_the_bare_name(self):
        got = outlines.build_outlines("STANSTED_CTR", [square(0, 51, 0.1)])
        self.assertEqual([n for n, _ in got], ["STANSTED_CTR"])

    def test_disjoint_shapes_are_suffixed(self):
        got = outlines.build_outlines("STANSTED_TMZ_CTR",
                                      [square(0, 51, 0.1), square(5, 51, 0.1)])
        self.assertEqual(sorted(n for n, _ in got),
                         ["STANSTED_TMZ_CTR0", "STANSTED_TMZ_CTR1"])


class TestCheckRing(unittest.TestCase):
    def test_good_ring_has_no_problems(self):
        self.assertEqual(outlines.check_ring("X", square(0, 51, 0.1)), [])

    def test_too_few_points(self):
        problems = outlines.check_ring("X", [[0, 51], [1, 51]])
        self.assertEqual(len(problems), 1)
        self.assertIn("points", problems[0])

    def test_self_intersection_is_reported(self):
        bowtie = [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]
        problems = outlines.check_ring("X", bowtie)
        self.assertTrue(any("self-intersect" in p for p in problems))

    def test_returns_problems_rather_than_raising(self):
        # The old code called SystemExit, which is fine in a one-shot script
        # and useless in a web UI that has to report to a user.
        self.assertIsInstance(outlines.check_ring("X", [[0, 0]]), list)


if __name__ == "__main__":
    unittest.main()
