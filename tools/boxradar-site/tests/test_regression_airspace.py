"""The gate: generating from the transcribed selection must reproduce the
committed header.

Compared with TOLERANCE, never equality. This repo's devShell has shapely 2.x
and the receiver Pi has 1.8 from apt — different GEOS, so buffer, union and
simplify can differ in the last decimal and occasionally in vertex count. An
equality test would pass on one machine and fail on the other, which is worse
than no test.

Hausdorff distance is the right measure: it is the largest distance from any
point on one outline to the nearest point on the other, so it catches a
genuinely wrong shape while tolerating a different sampling of the same one.
"""

import pathlib
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
COMMITTED_HEADER = REPO / "src" / "ui" / "airspace_data.h"
YAML_PATH = (pathlib.Path.home() / ".cache/boxradar-airspace/airspace"
             / "airspace.yaml")
SELECTION = (pathlib.Path(__file__).resolve().parents[1]
             / "boxradar_site" / "geo" / "selection.example.json")

# 0.0005 degrees is ~55m. SIMPLIFY_DEG is already 0.0005 (~35m), so anything
# under this is inside the noise the pipeline deliberately introduces. At the
# 10nm detail scale (11 px/nm) 55m is about a third of a pixel.
HAUSDORFF_TOLERANCE_DEG = 0.0005


@unittest.skipUnless(YAML_PATH.exists() and COMMITTED_HEADER.exists(),
                     "needs the cached YAIXM source and the committed header")
class TestReproducesCommittedHeader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import yaml
        from boxradar_site.geo import emit, selection
        with YAML_PATH.open() as f:
            features = yaml.safe_load(f).get("airspace", [])
        sel = selection.load(SELECTION)
        cls.outlines, cls.problems = emit.build_airspace_outlines(sel,
                                                                  features)
        # emit stores [lon, lat]; the header is (lat, lon).
        cls.generated = {name: [(p[1], p[0]) for p in ring]
                         for name, ring in cls.outlines}
        cls.committed = emit.parse_header(COMMITTED_HEADER.read_text())

    def test_no_geometry_problems(self):
        self.assertEqual(self.problems, [])

    def test_same_outline_names(self):
        self.assertEqual(sorted(self.generated), sorted(self.committed))

    def test_every_outline_matches_within_tolerance(self):
        from shapely.geometry import Polygon
        worst_name, worst = None, 0.0
        for name, committed_pts in self.committed.items():
            a = Polygon([(lon, lat) for lat, lon in committed_pts])
            b = Polygon([(lon, lat) for lat, lon in self.generated[name]])
            d = a.hausdorff_distance(b)
            if d > worst:
                worst_name, worst = name, d
        self.assertLess(worst, HAUSDORFF_TOLERANCE_DEG,
                        f"{worst_name} differs by {worst:.6f} degrees "
                        f"(~{worst * 60 * 1852:.0f}m)")

    def test_vertex_counts_are_close(self):
        # Not equal: a different GEOS can simplify to a different sampling.
        for name, committed_pts in self.committed.items():
            got = len(self.generated[name])
            want = len(committed_pts)
            self.assertLessEqual(abs(got - want), max(2, want // 10),
                                 f"{name}: {got} points vs {want}")


if __name__ == "__main__":
    unittest.main()
