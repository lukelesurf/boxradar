# Airspace Selection Implementation Plan (phase 2a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `CURATED_AIRPORTS` with a selection config plus a searchable candidate list, so choosing local airspace stops requiring you to know the YAIXM feature names.

**Architecture:** The airspace geometry pipeline moves out of `tools/build_airspace.py` into `boxradar_site/geo/`, split into a stdlib-only YAIXM parser and a shapely-dependent outline builder. On top of that sit two new things: a *catalog* query that lists every feature in the box with the metadata a human needs to choose (kind, on-screen size, distance, vertex count), and a *rules* module implementing the four measured defaults behind a "suggest" call. Output is still `src/ui/airspace_data.h` — the binary blob is phase 2b.

**Tech Stack:** Python 3 with PyYAML and shapely for the generator; stdlib only for the METAR service. Those are two distinct dependency profiles in one package and must not leak into each other.

## Global Constraints

- **Two dependency profiles, enforced.** `boxradar_site/{metar,cache,server,upstream,config,__main__}.py` are the systemd service and must stay importable with **stdlib only** — the reason is unchanged from phase 1: "Debian's Python is externally managed (PEP 668) and this should not need a venv or pip on a receiver box." `boxradar_site/geo/*` may use shapely and yaml. Nothing under `geo/` may be imported by the service modules.
- **Dependencies come from apt, not pip.** `sudo apt install python3-shapely python3-yaml` on the Pi (`python3-shapely 1.8.5-2+b1`, `python3-yaml 6.0-3+b2` in bookworm). apt is outside PEP 668's scope, so no venv is needed and `install.sh` stays simple.
- **Shapely versions differ between dev and target: 2.1.2 here, 1.8.5 on the Pi.** Different GEOS, so buffer/union/simplify output can differ in the last decimal and possibly in vertex count. Every geometry comparison in this plan is therefore a **tolerance** comparison, never equality. See Task 7.
- **The selection config is the source of truth for what gets drawn.** The four rules only produce a *suggestion*; they never filter the output.
- `BOUNDS_LAT`/`BOUNDS_LON` are retired. Their documented purpose was "a guard against a mistyped feature name silently emitting airspace from the other end of the country" — names now come from a list, and the box is the selection scope.
- Run tests from the repo root:
  `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
- Measurements this plan relies on, from the 65nm box at home 51.8850, 0.2350: **250 features intersect, 9,047 vertices.** By type: OTHER 107, ATZ 47, D_OTHER 39, D 21, CTA 16, CTR 13, R 6, TMA 1. Largest on screen at 2.2px/nm: `DAVENTRY CTA` 334px, `LONDON TMA` 313, `COTSWOLD CTA` 278, `CLACTON CTA` 278, `PORTSMOUTH CTA` 243, `WORTHING CTA` 235, `NORTH SEA CTA` 213.

---

## File Structure

**Created:**

| file | responsibility |
|---|---|
| `boxradar_site/geo/__init__.py` | package marker |
| `boxradar_site/geo/yaixm.py` | YAIXM source parsing: DMS coordinates, arc and circle interpolation, boundary to ring. **stdlib + math only** |
| `boxradar_site/geo/outlines.py` | shapely: ring merging, envelope building, self-intersection checks |
| `boxradar_site/geo/catalog.py` | the candidate list — every feature in the box with kind, size, distance, vertex count |
| `boxradar_site/geo/rules.py` | the four measured rules, as a `suggest()` over a catalog |
| `boxradar_site/geo/selection.py` | the selection config: load, validate, report names that no longer exist |
| `boxradar_site/geo/emit.py` | writes `src/ui/airspace_data.h` |
| `boxradar_site/geo/__main__.py` | CLI: `list`, `suggest`, `build` |
| `tests/test_yaixm.py` | coordinate and arc parsing |
| `tests/test_outlines.py` | merging, disjoint volumes, degenerate rings |
| `tests/test_catalog.py` | bbox intersection and metadata, against the real YAIXM |
| `tests/test_rules.py` | the suggestion reproduces today's selection |
| `tests/test_selection.py` | config loading and missing-name reporting |
| `tests/test_regression_airspace.py` | generated geometry matches the committed header within tolerance |
| `boxradar_site/geo/selection.example.json` | the transcription of `CURATED_AIRPORTS` |

**Modified:** `tools/boxradar-site/install.sh`, `tools/boxradar-site/README.md`, `flake.nix`
**Deleted (last task only):** `tools/build_airspace.py`

Why `geo/` is a subpackage rather than flat modules: it is the dependency boundary. A reader can tell at a glance which half of this package the systemd service is allowed to touch, and a test can assert it.

---

### Task 1: Dependency boundary

Before any geometry code exists, make the constraint that keeps the service deployable into a test, so it cannot rot silently.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/__init__.py`
- Create: `tools/boxradar-site/tests/test_dependency_boundary.py`
- Modify: `tools/boxradar-site/install.sh`
- Modify: `tools/boxradar-site/README.md`
- Modify: `flake.nix`

**Interfaces:**
- Consumes: nothing.
- Produces: `boxradar_site.geo` as an importable subpackage.

- [ ] **Step 1: Write the failing test**

Create `tools/boxradar-site/tests/test_dependency_boundary.py`:

```python
"""The METAR service must stay stdlib-only so it can run on a Debian Pi with
no venv and no pip. The geography generator may use shapely and yaml. This
test is what stops the second set leaking into the first.

It works by source inspection rather than by import, because importing proves
nothing on a dev machine that happens to have shapely installed.
"""

import ast
import pathlib
import unittest

PKG = pathlib.Path(__file__).resolve().parents[1] / "boxradar_site"

SERVICE_MODULES = ["metar.py", "cache.py", "server.py", "upstream.py",
                   "config.py", "__main__.py", "__init__.py"]

# Anything not in the standard library, plus the geo subpackage itself.
FORBIDDEN_IN_SERVICE = {"shapely", "yaml", "boxradar_site.geo", "geo"}


def imported_names(path):
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, e.g. "from .geo import x"
                out.add((node.module or "").split(".")[0])
            elif node.module:
                out.add(node.module.split(".")[0])
    return out


class TestServiceStaysStdlibOnly(unittest.TestCase):
    def test_no_third_party_or_geo_imports(self):
        offenders = {}
        for name in SERVICE_MODULES:
            path = PKG / name
            bad = imported_names(path) & FORBIDDEN_IN_SERVICE
            if bad:
                offenders[name] = sorted(bad)
        self.assertEqual(offenders, {},
                         "service modules must not import shapely, yaml or geo")

    def test_every_service_module_exists(self):
        # Guards against the list above silently drifting from reality.
        for name in SERVICE_MODULES:
            self.assertTrue((PKG / name).is_file(), f"missing {name}")


class TestGeoSubpackageExists(unittest.TestCase):
    def test_geo_is_a_package(self):
        self.assertTrue((PKG / "geo" / "__init__.py").is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL on `test_geo_is_a_package` — the other two pass already, which is the point: they are a guard, not a goal.

- [ ] **Step 3: Create the subpackage marker**

Create `tools/boxradar-site/boxradar_site/geo/__init__.py`:

```python
"""Geography generation: airspace and coastline selection and codegen.

Requires PyYAML and shapely. Deliberately a subpackage rather than flat
modules, because it is a dependency boundary: the METAR service under
boxradar_site/ is stdlib-only so it can run on a Debian Pi without a venv,
and tests/test_dependency_boundary.py enforces that nothing here is imported
from there.

Install the dependencies from apt, not pip — Debian's Python is externally
managed (PEP 668), and apt is outside its scope:

    sudo apt install python3-shapely python3-yaml
"""
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 67 tests

- [ ] **Step 5: Install the dependencies on the Pi**

```bash
ssh pi@192.0.2.10 'sudo apt-get install -y python3-shapely python3-yaml && \
  python3 -c "import shapely, yaml; print(shapely.__version__, yaml.__version__)"'
```

Expected: `1.8.5 6.0` or similar. Note the shapely major version differs from
the dev machine's 2.x — that is why Task 7 compares with tolerance.

- [ ] **Step 6: Note the split in the installer and README**

In `tools/boxradar-site/install.sh`, after the `python3 >= 3.7` check, add:

```bash
# The METAR service is stdlib-only on purpose, so it is installed and started
# regardless. The geography generator additionally needs shapely and yaml;
# report rather than fail, so a receiver that only wants weather still works.
if python3 -c 'import shapely, yaml' 2>/dev/null; then
  echo "geography generator dependencies present"
else
  echo "note: geography generation unavailable (that is fine for METAR only)"
  echo "      to enable: sudo apt install python3-shapely python3-yaml"
fi
```

In `tools/boxradar-site/README.md`, append to the Tests section:

```markdown
## Dependencies

Two profiles in one package, and the split is enforced by
`tests/test_dependency_boundary.py`:

| part | needs | why |
|---|---|---|
| METAR service (`boxradar_site/*.py`) | stdlib only | runs as a systemd unit on a Debian Pi where PEP 668 blocks pip and a venv would be extra machinery |
| geography generator (`boxradar_site/geo/*`) | PyYAML, shapely | polygon union and simplification have no stdlib equivalent |

Install the generator's dependencies from apt, which is outside PEP 668's
scope:

```bash
sudo apt install python3-shapely python3-yaml
```

The Pi has shapely 1.8, this repo's devShell has 2.x. Different GEOS, so
generated vertices can differ in the last decimal and occasionally in count.
Geometry tests compare with tolerance for exactly that reason.
```

In `flake.nix`, the devShell comment says "airspace codegen
(tools/build_airspace.py)". Change it to:

```nix
            # airspace codegen (boxradar_site.geo) — note the Pi runs
            # shapely 1.8 from apt while this is 2.x, so geometry tests
            # compare with tolerance rather than equality
            (python3.withPackages (ps: [ ps.pyyaml ps.shapely ]))
```

- [ ] **Step 7: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/__init__.py \
        tools/boxradar-site/tests/test_dependency_boundary.py \
        tools/boxradar-site/install.sh \
        tools/boxradar-site/README.md flake.nix
git commit -m "feat: dependency boundary between the METAR service and geo codegen

The service stays stdlib-only so it can run on a Debian Pi with no venv;
the generator needs shapely and yaml from apt. Enforced by source inspection
rather than by import, because importing proves nothing on a dev machine that
already has shapely."
```

---

### Task 2: YAIXM parsing

Move the source-format parsing across unchanged in behaviour. It is stdlib-only
and pure, which is what makes it the easy half to test.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/yaixm.py`
- Test: `tools/boxradar-site/tests/test_yaixm.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ARC_RESOLUTION: int = 36`
  - `parse_latlon(s: str) -> tuple[float, float]`
  - `boundary_to_ring(boundary: list[dict]) -> list[list[float]] | None` — closed `[lon, lat]` ring, or `None` if unparseable
  - `feature_rings(feature: dict) -> list[list[list[float]]]`
  - `feature_kind(feature: dict) -> str` — a single display string from `(type, localtype, rules)`, e.g. `"CTR"`, `"OTHER/TMZ"`, `"OTHER/MATZ"`

`feature_kind()` is new, and it exists because the measurements showed `type`
alone cannot express what gets drawn: the Stansted TMZ is
`type: OTHER, localtype: TMZ, rules: [TMZ]`, while `OTHER` also holds 12 MATZs
and a pile of ILS feathers.

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_yaixm.py`:

```python
import unittest

from boxradar_site.geo import yaixm


class TestParseLatLon(unittest.TestCase):
    def test_north_east(self):
        lat, lon = yaixm.parse_latlon("515152N 0000345E")
        self.assertAlmostEqual(lat, 51.86444, places=4)
        self.assertAlmostEqual(lon, 0.06250, places=4)

    def test_south_west_are_negative(self):
        lat, lon = yaixm.parse_latlon("515152S 0000345W")
        self.assertAlmostEqual(lat, -51.86444, places=4)
        self.assertAlmostEqual(lon, -0.06250, places=4)

    def test_three_digit_longitude_degrees(self):
        lat, lon = yaixm.parse_latlon("515152N 1000345W")
        self.assertAlmostEqual(lon, -100.06250, places=4)

    def test_fractional_seconds(self):
        lat, _ = yaixm.parse_latlon("515152.50N 0000345E")
        self.assertAlmostEqual(lat, 51.864583, places=5)


class TestFeatureKind(unittest.TestCase):
    def test_plain_type(self):
        self.assertEqual(yaixm.feature_kind({"type": "CTR"}), "CTR")

    def test_localtype_qualifies_other(self):
        # The reason type alone is not enough: OTHER holds both the Stansted
        # TMZ we draw and a dozen MATZs we do not.
        self.assertEqual(
            yaixm.feature_kind({"type": "OTHER", "localtype": "TMZ"}),
            "OTHER/TMZ")
        self.assertEqual(
            yaixm.feature_kind({"type": "OTHER", "localtype": "MATZ"}),
            "OTHER/MATZ")

    def test_tmz_rule_without_localtype_still_shows_as_tmz(self):
        self.assertEqual(
            yaixm.feature_kind({"type": "OTHER", "rules": ["TMZ"]}),
            "OTHER/TMZ")

    def test_missing_type(self):
        self.assertEqual(yaixm.feature_kind({}), "?")


class TestBoundaryToRing(unittest.TestCase):
    def test_simple_polygon_closes_itself(self):
        ring = yaixm.boundary_to_ring([
            {"line": ["515152N 0000345E", "520000N 0001500E",
                      "515000N 0001500E"]}])
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(len(ring), 4)

    def test_circle_is_interpolated(self):
        ring = yaixm.boundary_to_ring([
            {"circle": {"centre": "515152N 0000345E", "radius": "2 nm"}}])
        self.assertEqual(len(ring), yaixm.ARC_RESOLUTION + 1)
        self.assertEqual(ring[0], ring[-1])

    def test_unparseable_returns_none(self):
        self.assertIsNone(yaixm.boundary_to_ring([{"nonsense": 1}]))

    def test_empty_returns_none(self):
        self.assertIsNone(yaixm.boundary_to_ring([]))


class TestFeatureRings(unittest.TestCase):
    def test_one_ring_per_volume(self):
        feature = {"geometry": [
            {"boundary": [{"circle": {"centre": "515152N 0000345E",
                                      "radius": "2 nm"}}]},
            {"boundary": [{"circle": {"centre": "520000N 0001500E",
                                      "radius": "3 nm"}}]},
        ]}
        self.assertEqual(len(yaixm.feature_rings(feature)), 2)

    def test_no_geometry_is_empty_not_an_error(self):
        self.assertEqual(yaixm.feature_rings({}), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.yaixm'`

- [ ] **Step 3: Port the implementation**

Copy `parse_latlon`, `_parse_deg`, `_nm_to_deg`, `_deg_to_rad`, `_rad_to_deg`,
`_geojson_coord`, `_interpolate_arc`, `_interpolate_circle`,
`_boundary_to_ring` and `feature_rings` from `tools/build_airspace.py`
(lines 79–290) into `tools/boxradar-site/boxradar_site/geo/yaixm.py` verbatim,
renaming `_boundary_to_ring` to the public `boundary_to_ring`. Keep every
comment — the DMS pattern and the arc interpolation notes are the reason this
code is correct.

Then change `feature_rings` so it **returns `[]` rather than raising** on an
unparseable boundary, and add:

```python
def feature_kind(feature):
    """A single display string from (type, localtype, rules).

    type alone is not enough. The Stansted TMZ is type OTHER with localtype
    TMZ, and OTHER also holds a dozen MATZs, ILS feathers and gliding sites —
    so a picker that showed only `type` would present them as identical.
    """
    base = str(feature.get("type") or "") or "?"
    local = str(feature.get("localtype") or "")
    if not local:
        rules = feature.get("rules") or []
        if "TMZ" in rules:
            local = "TMZ"
    return f"{base}/{local}" if local else base
```

Note the behaviour change to `feature_rings`: the old code raised `SystemExit`
because it only ever saw hand-picked features. The catalog walks all 703, so an
unparseable boundary must be skippable.

- [ ] **Step 4: Run to verify passing**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 82 tests

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/yaixm.py \
        tools/boxradar-site/tests/test_yaixm.py
git commit -m "feat: YAIXM parsing as a tested stdlib-only module

Ported from tools/build_airspace.py with two changes. feature_rings() returns
empty instead of raising, because the catalog walks all 703 UK features rather
than a hand-picked dozen. And feature_kind() collapses (type, localtype,
rules) into one string, because type alone cannot distinguish the Stansted TMZ
we draw from the MATZs we do not — both are type OTHER."
```

---

### Task 3: Outline building

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/outlines.py`
- Test: `tools/boxradar-site/tests/test_outlines.py`

**Interfaces:**
- Consumes: nothing (operates on `[lon, lat]` rings from `yaixm`)
- Produces:
  - `BUFFER_DEG: float = 0.001`, `SIMPLIFY_DEG: float = 0.0005`
  - `merge_rings(rings) -> list[list[list[float]]]`
  - `build_outlines(name: str, rings) -> list[tuple[str, list]]` — suffixes `0`, `1`… when volumes are genuinely disjoint
  - `check_ring(name: str, ring) -> list[str]` — returns problems rather than raising

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_outlines.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.outlines'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/geo/outlines.py`:

```python
"""Ring merging and validation. The only shapely-dependent module.

Ported from tools/build_airspace.py. One behaviour change: check_ring()
returns a list of problems instead of raising SystemExit, because these
messages now have to reach a user in a browser rather than a terminal.
"""

from shapely.geometry import LinearRing, Polygon
from shapely.ops import unary_union

# ~60m: merges near-coincident arc discretisations. Adjacent volumes
# discretise shared arcs from different endpoints, so their edges are near-
# but not exactly coincident; the buffer in/out absorbs those slivers before
# taking the exterior.
BUFFER_DEG = 0.001
# ~35m: invisible at scope scale, trims point count.
SIMPLIFY_DEG = 0.0005

MIN_RING_POINTS = 4


def merge_rings(rings):
    """Exterior ring(s) of the union of all rings, as closed [lon,lat] rings.

    Returns ONE ring when the volumes touch or overlap — the common case,
    where a CTR and its CTA shelves form a single envelope. Returns several
    when they are genuinely disjoint, which is not an error: the Stansted TMZ
    is two separate lobes either side of the field, under the 04 and 22
    approaches, and merging them would invent airspace between them.
    """
    polys = [Polygon(r).buffer(BUFFER_DEG) for r in rings]
    merged = unary_union(polys).buffer(-BUFFER_DEG).simplify(SIMPLIFY_DEG)
    geoms = list(merged.geoms) if merged.geom_type == "MultiPolygon" \
        else [merged]
    out = []
    for g in geoms:
        if g.geom_type != "Polygon":
            continue
        out.append([[round(lon, 6), round(lat, 6)]
                    for lon, lat in g.exterior.coords])
    return out


def build_outlines(name, rings):
    """One outline, or several suffixed ones if the volumes are disjoint."""
    merged = merge_rings(rings)
    if len(merged) == 1:
        return [(name, merged[0])]
    return [(f"{name}{i}", r) for i, r in enumerate(merged)]


def check_ring(name, ring):
    """Problems with a ring, as human-readable strings. Empty means fine."""
    problems = []
    if len(ring) < MIN_RING_POINTS:
        problems.append(f"{name}: only {len(ring)} points")
        return problems  # the geometry checks below would raise on this
    try:
        if not LinearRing([(lon, lat) for lon, lat in ring]).is_simple:
            problems.append(f"{name}: ring self-intersects")
    except Exception as e:  # shapely raises various things on degenerate input
        problems.append(f"{name}: unusable ring ({e})")
    return problems
```

- [ ] **Step 4: Run to verify passing**

Expected: PASS, 93 tests

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/outlines.py \
        tools/boxradar-site/tests/test_outlines.py
git commit -m "feat: ring merging and validation as a tested module

Ported from tools/build_airspace.py, keeping the buffer-in/out trick that
absorbs near-coincident arc discretisations and the disjoint-volume handling
the Stansted TMZ needs. check_ring() now returns problems instead of calling
SystemExit, because these messages have to reach a browser."
```

---

### Task 4: The candidate catalog

This is the module that solves the actual problem — it is what makes airspace
discoverable without knowing the dataset's names.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/catalog.py`
- Test: `tools/boxradar-site/tests/test_catalog.py`

**Interfaces:**
- Consumes: `yaixm.feature_rings`, `yaixm.feature_kind`
- Produces:
  - `NM_PER_DEG_LAT: float = 60.0`
  - `class Candidate` with `name, kind, vertices, volumes, diag_nm, distance_nm, min_lat, max_lat, min_lon, max_lon`, and `diag_px(px_per_nm)`
  - `bbox_for(home_lat, home_lon, reach_nm) -> tuple[float, float, float, float]` returning `(south, north, west, east)`
  - `catalog(features: list[dict], home_lat, home_lon, reach_nm) -> list[Candidate]` sorted by `distance_nm`

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_catalog.py`:

```python
import pathlib
import unittest

from boxradar_site.geo import catalog

# The real dataset, cached by the existing generator. Tests that need it skip
# rather than fail when it is absent, so the suite still runs on a machine
# that has never fetched it.
YAML_PATH = (pathlib.Path.home() / ".cache/boxradar-airspace/airspace"
             / "airspace.yaml")

HOME_LAT, HOME_LON = 51.88501837203816, 0.23502731659204137
REACH_NM = 65.0


def load_features():
    import yaml
    with YAML_PATH.open() as f:
        return yaml.safe_load(f).get("airspace", [])


class TestBboxFor(unittest.TestCase):
    def test_latitude_span_is_reach_in_both_directions(self):
        s, n, w, e = catalog.bbox_for(51.9, 0.0, 60.0)
        self.assertAlmostEqual(n - 51.9, 1.0, places=6)
        self.assertAlmostEqual(51.9 - s, 1.0, places=6)

    def test_longitude_span_widens_with_latitude(self):
        _, _, w, e = catalog.bbox_for(51.9, 0.0, 60.0)
        # 1 degree of latitude is 60nm; a degree of longitude at 51.9N is
        # only ~37nm, so the box must be wider in degrees to reach as far.
        self.assertGreater(e - w, 2.0)
        self.assertLess(e - w, 4.0)


@unittest.skipUnless(YAML_PATH.exists(), f"needs {YAML_PATH}")
class TestCatalogAgainstRealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = load_features()
        cls.cands = catalog.catalog(cls.features, HOME_LAT, HOME_LON, REACH_NM)
        cls.by_name = {c.name: c for c in cls.cands}

    def test_finds_the_measured_number_of_features(self):
        # Measured 2026-08-08: 250 of 703 UK features intersect this box.
        # A wide assertion, because the upstream dataset is updated.
        self.assertGreater(len(self.cands), 200)
        self.assertLess(len(self.cands), 320)

    def test_includes_the_local_ctrs(self):
        for name in ["LONDON STANSTED CTR", "LONDON LUTON CTR",
                     "LONDON CITY CTR", "SOUTHEND CTR", "LONDON CTR"]:
            self.assertIn(name, self.by_name)

    def test_excludes_far_away_airspace(self):
        self.assertNotIn("SCOTTISH TMA", self.by_name)

    def test_sorted_by_distance_from_home(self):
        distances = [c.distance_nm for c in self.cands]
        self.assertEqual(distances, sorted(distances))

    def test_kind_distinguishes_tmz_from_other(self):
        tmz = self.by_name["LONDON STANSTED TMZ"]
        self.assertEqual(tmz.kind, "OTHER/TMZ")

    def test_on_screen_size_identifies_the_oversize_ctas(self):
        # The London TMA is not even the worst: DAVENTRY CTA is larger.
        daventry = self.by_name["DAVENTRY CTA"].diag_px(2.2)
        tma = self.by_name["LONDON TMA"].diag_px(2.2)
        stansted_cta = self.by_name["LONDON STANSTED CTA"].diag_px(2.2)
        self.assertGreater(daventry, tma)
        self.assertGreater(tma, 250)
        self.assertLess(stansted_cta, 110)

    def test_vertex_counts_are_populated(self):
        self.assertGreater(self.by_name["LONDON STANSTED CTR"].vertices, 10)

    def test_atzs_are_present_but_tiny(self):
        atzs = [c for c in self.cands if c.kind == "ATZ"]
        self.assertGreater(len(atzs), 20)
        self.assertTrue(all(c.diag_px(2.2) < 30 for c in atzs))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.catalog'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/geo/catalog.py`:

```python
"""The candidate list: what airspace is near me, and how would it look?

This is the module that replaces CURATED_AIRPORTS. That list was hard to
maintain not because choosing is hard but because *discovery* was: you had to
know which controlled airspace mattered near you and how the YAIXM source
spelled it. Listing every feature in the box, with the numbers a human decides
on, removes that entirely.

The columns are chosen from what the decision actually turns on:

  kind         (type, localtype, rules) collapsed — OTHER/TMZ is drawn,
               OTHER/MATZ is not, and `type` alone cannot tell them apart
  diag_px      on-screen extent at the overview scale. An outline larger than
               the panel cannot read as an enclosure, which is the recorded
               reason the London TMA was excluded by hand
  distance_nm  catches far-but-small: BOURNEMOUTH CTR is 43px and ~110nm away
  vertices     the only column with a device cost
"""

import math

from .yaixm import feature_kind, feature_rings

NM_PER_DEG_LAT = 60.0


class Candidate:
    def __init__(self, name, kind, rings, home_lat, home_lon):
        self.name = name
        self.kind = kind
        self.volumes = len(rings)
        self.vertices = sum(len(r) for r in rings)
        lats = [lat for r in rings for _, lat in r]
        lons = [lon for r in rings for lon, _ in r]
        self.min_lat, self.max_lat = min(lats), max(lats)
        self.min_lon, self.max_lon = min(lons), max(lons)
        mid_lat = (self.min_lat + self.max_lat) / 2.0
        scale = math.cos(math.radians(mid_lat))
        h_nm = (self.max_lat - self.min_lat) * NM_PER_DEG_LAT
        w_nm = (self.max_lon - self.min_lon) * NM_PER_DEG_LAT * scale
        self.diag_nm = math.hypot(h_nm, w_nm)
        d_lat = (mid_lat - home_lat) * NM_PER_DEG_LAT
        d_lon = (((self.min_lon + self.max_lon) / 2.0) - home_lon) \
            * NM_PER_DEG_LAT * math.cos(math.radians(home_lat))
        self.distance_nm = math.hypot(d_lat, d_lon)

    def diag_px(self, px_per_nm):
        return self.diag_nm * px_per_nm

    def intersects(self, south, north, west, east):
        return not (self.max_lat < south or self.min_lat > north
                    or self.max_lon < west or self.min_lon > east)

    def __repr__(self):
        return (f"<Candidate {self.name!r} {self.kind} "
                f"{self.diag_nm:.0f}nm @{self.distance_nm:.0f}nm "
                f"{self.vertices}v>")


def bbox_for(home_lat, home_lon, reach_nm):
    """(south, north, west, east) for a reach in nautical miles.

    Longitude is scaled by cos(latitude): a degree of longitude at 51.9N is
    only about 37nm, so reaching the same distance east needs more degrees
    than reaching the same distance north.
    """
    d_lat = reach_nm / NM_PER_DEG_LAT
    d_lon = d_lat / math.cos(math.radians(home_lat))
    return (home_lat - d_lat, home_lat + d_lat,
            home_lon - d_lon, home_lon + d_lon)


def catalog(features, home_lat, home_lon, reach_nm):
    """Every feature whose geometry intersects the box, nearest first."""
    south, north, west, east = bbox_for(home_lat, home_lon, reach_nm)
    out = []
    for feature in features:
        rings = feature_rings(feature)
        if not rings:
            continue  # unparseable or geometry-less; not our problem here
        cand = Candidate(str(feature.get("name") or "?"),
                         feature_kind(feature), rings, home_lat, home_lon)
        if cand.intersects(south, north, west, east):
            out.append(cand)
    out.sort(key=lambda c: c.distance_nm)
    return out
```

- [ ] **Step 4: Run to verify passing**

Expected: PASS, 103 tests

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/catalog.py \
        tools/boxradar-site/tests/test_catalog.py
git commit -m "feat: candidate catalog — what airspace is in my box

The module that actually replaces CURATED_AIRPORTS. That list was hard to
maintain because of discovery, not judgement: you had to know which CTRs
mattered near you and how YAIXM spelled them. Listing the box with kind,
on-screen size, distance and vertex count removes that.

Tested against the real dataset, including the finding that motivated the
design: DAVENTRY CTA is larger on screen than the London TMA that
build_airspace.py excluded by hand."
```

---

### Task 5: Suggested defaults

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/rules.py`
- Test: `tools/boxradar-site/tests/test_rules.py`

**Interfaces:**
- Consumes: `catalog.Candidate`
- Produces:
  - `DEFAULT_KINDS: tuple = ("CTR", "CTA", "OTHER/TMZ")`
  - `DEFAULT_MAX_DIAG_NM: float = 50.0`
  - `DEFAULT_MAX_DISTANCE_NM: float = 50.0`
  - `class SuggestRules(kinds=..., max_diag_nm=..., max_distance_nm=...)` with `accepts(cand) -> bool` and `reject_reason(cand) -> str | None`
  - `suggest(candidates, rules=None) -> tuple[list[Candidate], list[tuple[Candidate, str]]]` — `(accepted, [(rejected, reason)])`

Returning reasons is the point: a picker that says "hidden because 334px is
wider than the panel" is usable, and one that silently drops things is not.

- [ ] **Step 1: Write the failing tests**

Create `tools/boxradar-site/tests/test_rules.py`:

```python
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

# Measured 2026-08-08 as larger on screen than the panel is wide.
OVERSIZE = {"DAVENTRY CTA", "LONDON TMA", "COTSWOLD CTA", "CLACTON CTA",
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
        for name in OVERSIZE:
            self.assertIn(name, self.reasons, f"{name} should be rejected")
            self.assertIn("wide", self.reasons[name],
                          f"{name} rejected for the wrong reason")

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
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.rules'`

- [ ] **Step 3: Write the implementation**

Create `tools/boxradar-site/boxradar_site/geo/rules.py`:

```python
"""The four measured rules — as a suggestion, never as a filter.

These began as a proposal to select airspace automatically, and the
measurements are what argued them down to a default. Selecting by rule needs a
size ceiling AND a distance ceiling AND a preview to tune them, all
site-dependent; that is more machinery than a checkbox list eyeballed once. So
what remains is a starting set the user adjusts.

Every rejection carries a reason. A picker that says "hidden: 334px is wider
than the panel" is usable; one that silently drops things is not.

Defaults derived from the 65nm box at 51.8850, 0.2350 on 2026-08-08:
CTR/CTA/TMZ reproduces the hand-curated editorial choice, a 50nm diagonal
(~110px, half the 109nm overview panel) cuts the seven enroute CTAs that are
larger on screen than the London TMA, and 50nm of distance cuts far-but-small
outliers like BOURNEMOUTH CTR at 43px and ~110nm away.
"""

DEFAULT_KINDS = ("CTR", "CTA", "OTHER/TMZ")
DEFAULT_MAX_DIAG_NM = 50.0
DEFAULT_MAX_DISTANCE_NM = 50.0


class SuggestRules:
    def __init__(self, kinds=DEFAULT_KINDS,
                 max_diag_nm=DEFAULT_MAX_DIAG_NM,
                 max_distance_nm=DEFAULT_MAX_DISTANCE_NM):
        self.kinds = tuple(kinds)
        self.max_diag_nm = max_diag_nm
        self.max_distance_nm = max_distance_nm

    def reject_reason(self, cand):
        """Why this would not be suggested, or None if it would."""
        if cand.kind not in self.kinds:
            return f"kind {cand.kind} not in {', '.join(self.kinds)}"
        if cand.diag_nm > self.max_diag_nm:
            return (f"{cand.diag_nm:.0f}nm wide, over the "
                    f"{self.max_diag_nm:.0f}nm limit — too wide to read as an "
                    f"enclosure")
        if cand.distance_nm > self.max_distance_nm:
            return (f"{cand.distance_nm:.0f}nm away, over the "
                    f"{self.max_distance_nm:.0f}nm limit — too far to matter")
        return None

    def accepts(self, cand):
        return self.reject_reason(cand) is None


def suggest(candidates, rules=None):
    """(accepted, [(rejected, reason)]) — every candidate accounted for."""
    rules = rules or SuggestRules()
    accepted, rejected = [], []
    for cand in candidates:
        reason = rules.reject_reason(cand)
        if reason is None:
            accepted.append(cand)
        else:
            rejected.append((cand, reason))
    return accepted, rejected
```

- [ ] **Step 4: Run to verify passing**

Expected: PASS, 116 tests. If
`test_suggestion_covers_the_hand_curated_set` fails, **do not loosen the
test** — the missing feature names are the specification of what the defaults
are still getting wrong. Widen the threshold that excludes them and record why
in the module docstring.

- [ ] **Step 5: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/rules.py \
        tools/boxradar-site/tests/test_rules.py
git commit -m "feat: the four measured rules, as a suggestion not a filter

Every rejection carries a reason, because a picker that explains why the
London TMA is hidden is usable and one that silently drops it is not.

The gate test asserts the suggestion never LOSES anything the hand-curated
CURATED_AIRPORTS chose. If it fails, the missing names are the specification
of what the defaults still get wrong."
```

---

### Task 6: Selection config

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/selection.py`
- Create: `tools/boxradar-site/boxradar_site/geo/selection.example.json`
- Test: `tools/boxradar-site/tests/test_selection.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class Group(name: str, primary: str, envelope: list[str])`
  - `class Selection(home_lat, home_lon, reach_nm, groups: list[Group])`
  - `load(path) -> Selection` — raises `ValueError` with a readable message on a malformed file
  - `missing_features(sel: Selection, features: list[dict]) -> list[str]`

The config is `CURATED_AIRPORTS` in JSON. `primary` is the feature drawn alone
(emitted as `<NAME>_CTR`); `envelope` lists features merged *with* the primary
into `<NAME>_ENV`. Heathrow has an empty `envelope`, which is exactly the
`("HEATHROW", "LONDON CTR", None)` tuple it replaces.

- [ ] **Step 1: Write the example config**

Create `tools/boxradar-site/boxradar_site/geo/selection.example.json`:

```json
{
  "home_lat": 51.8850,
  "home_lon": 0.2350,
  "reach_nm": 65,
  "airspace": [
    {"name": "STANSTED", "primary": "LONDON STANSTED CTR",
     "envelope": ["LONDON STANSTED CTA"]},
    {"name": "LUTON", "primary": "LONDON LUTON CTR",
     "envelope": ["LONDON LUTON CTA"]},
    {"name": "CITY", "primary": "LONDON CITY CTR",
     "envelope": ["LONDON CITY CTA"]},
    {"name": "GATWICK", "primary": "LONDON GATWICK CTR",
     "envelope": ["LONDON GATWICK CTA"]},
    {"name": "SOUTHEND", "primary": "SOUTHEND CTR",
     "envelope": ["SOUTHEND CTA"]},
    {"name": "HEATHROW", "primary": "LONDON CTR", "envelope": []},
    {"name": "STANSTED_TMZ", "primary": "LONDON STANSTED TMZ",
     "envelope": []}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `tools/boxradar-site/tests/test_selection.py`:

```python
import json
import os
import pathlib
import tempfile
import unittest

from boxradar_site.geo import selection

EXAMPLE = (pathlib.Path(__file__).resolve().parents[1]
           / "boxradar_site" / "geo" / "selection.example.json")


class SelectionTest(unittest.TestCase):
    def write(self, obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        self.addCleanup(os.unlink, path)
        return path


class TestLoadExample(unittest.TestCase):
    def test_example_transcribes_curated_airports(self):
        sel = selection.load(EXAMPLE)
        self.assertEqual(len(sel.groups), 7)
        by_name = {g.name: g for g in sel.groups}
        self.assertEqual(by_name["STANSTED"].primary, "LONDON STANSTED CTR")
        self.assertEqual(by_name["STANSTED"].envelope,
                         ["LONDON STANSTED CTA"])
        # Heathrow has no CTA of its own: its zone is LONDON CTR and its CTA
        # is the TMA. An empty envelope is the whole representation.
        self.assertEqual(by_name["HEATHROW"].envelope, [])
        self.assertAlmostEqual(sel.reach_nm, 65.0)


class TestLoadErrors(SelectionTest):
    def test_missing_file(self):
        with self.assertRaises(ValueError) as cm:
            selection.load("/nonexistent/selection.json")
        self.assertIn("nonexistent", str(cm.exception))

    def test_malformed_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{nope")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(ValueError):
            selection.load(path)

    def test_missing_home_is_rejected(self):
        path = self.write({"airspace": []})
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("home_lat", str(cm.exception))

    def test_group_without_primary_is_rejected(self):
        path = self.write({"home_lat": 51.9, "home_lon": 0.0,
                           "airspace": [{"name": "X"}]})
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("primary", str(cm.exception))

    def test_duplicate_group_names_are_rejected(self):
        # Two groups with one name would silently overwrite each other's
        # generated symbols.
        path = self.write({"home_lat": 51.9, "home_lon": 0.0, "airspace": [
            {"name": "X", "primary": "A"}, {"name": "X", "primary": "B"}]})
        with self.assertRaises(ValueError) as cm:
            selection.load(path)
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_envelope_defaults_to_empty(self):
        path = self.write({"home_lat": 51.9, "home_lon": 0.0,
                           "airspace": [{"name": "X", "primary": "A"}]})
        self.assertEqual(selection.load(path).groups[0].envelope, [])

    def test_reach_defaults(self):
        path = self.write({"home_lat": 51.9, "home_lon": 0.0,
                           "airspace": []})
        self.assertEqual(selection.load(path).reach_nm,
                         selection.DEFAULT_REACH_NM)


class TestMissingFeatures(unittest.TestCase):
    def test_reports_names_absent_from_the_dataset(self):
        sel = selection.Selection(51.9, 0.0, 65.0, [
            selection.Group("X", "GONE CTR", ["STILL HERE CTA"])])
        features = [{"name": "STILL HERE CTA"}]
        self.assertEqual(selection.missing_features(sel, features),
                         ["GONE CTR"])

    def test_nothing_missing_is_empty(self):
        sel = selection.Selection(51.9, 0.0, 65.0, [
            selection.Group("X", "A", [])])
        self.assertEqual(selection.missing_features(sel, [{"name": "A"}]), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run to verify failure**

Expected: FAIL with `ModuleNotFoundError: No module named 'boxradar_site.geo.selection'`

- [ ] **Step 4: Write the implementation**

Create `tools/boxradar-site/boxradar_site/geo/selection.py`:

```python
"""The selection config: which airspace this site draws.

Structurally this is CURATED_AIRPORTS in JSON, and that is deliberate — the
transcription has to be faithful enough that the generated header is unchanged
on day one, so the first thing verified is "nothing moved".

`primary` is the feature drawn on its own, emitted as <NAME>_CTR. `envelope`
lists features merged WITH the primary into <NAME>_ENV. Grouping is explicit
rather than inferred, which is what makes the dataset's awkward case ordinary:
Heathrow has no HEATHROW feature, because its zone is LONDON CTR and its CTA
is the London TMA, so it is simply a primary with an empty envelope.

Unlike the METAR config, load() RAISES on a malformed file. A bad runway table
costs a runway recommendation; a bad selection would silently produce a map
missing airspace, and there is nothing safe to fall back to.
"""

import json

DEFAULT_REACH_NM = 65.0


class Group:
    def __init__(self, name, primary, envelope=None):
        self.name = name
        self.primary = primary
        self.envelope = list(envelope or [])

    def feature_names(self):
        return [self.primary] + self.envelope

    def __repr__(self):
        return f"<Group {self.name} primary={self.primary!r} " \
               f"envelope={self.envelope}>"


class Selection:
    def __init__(self, home_lat, home_lon, reach_nm, groups):
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.reach_nm = reach_nm
        self.groups = groups

    def feature_names(self):
        out = []
        for g in self.groups:
            out.extend(g.feature_names())
        return out


def load(path):
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except FileNotFoundError as e:
        raise ValueError(f"selection config not found: {path}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"cannot read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    for key in ("home_lat", "home_lon"):
        if not isinstance(raw.get(key), (int, float)) \
                or isinstance(raw.get(key), bool):
            raise ValueError(f"{path}: {key} missing or not a number")
    reach = raw.get("reach_nm", DEFAULT_REACH_NM)
    if isinstance(reach, bool) or not isinstance(reach, (int, float)):
        raise ValueError(f"{path}: reach_nm must be a number")

    groups, seen = [], set()
    entries = raw.get("airspace", [])
    if not isinstance(entries, list):
        raise ValueError(f"{path}: airspace must be a list")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: airspace[{i}] is not an object")
        name = entry.get("name")
        primary = entry.get("primary")
        if not name:
            raise ValueError(f"{path}: airspace[{i}] has no name")
        if not primary:
            raise ValueError(f"{path}: airspace[{i}] ({name}) has no primary")
        if name in seen:
            raise ValueError(f"{path}: duplicate group name {name!r} — the "
                             f"generated symbols would collide")
        seen.add(name)
        envelope = entry.get("envelope", [])
        if not isinstance(envelope, list):
            raise ValueError(f"{path}: {name} envelope must be a list")
        groups.append(Group(str(name), str(primary), [str(e) for e in envelope]))

    return Selection(float(raw["home_lat"]), float(raw["home_lon"]),
                     float(reach), groups)


def missing_features(sel, features):
    """Selected names that no longer exist in the dataset, in config order.

    The YAIXM source is updated, and a renamed feature would otherwise vanish
    from the map silently. find_feature() in the old generator was right to
    fail loudly on an unknown name; this is that behaviour made reportable
    rather than fatal, so a UI can say "2 selected features no longer exist".
    """
    available = {str(f.get("name") or "") for f in features}
    missing, seen = [], set()
    for name in sel.feature_names():
        if name not in available and name not in seen:
            seen.add(name)
            missing.append(name)
    return missing
```

- [ ] **Step 5: Run to verify passing**

Expected: PASS, 127 tests

- [ ] **Step 6: Commit**

```bash
git add tools/boxradar-site/boxradar_site/geo/selection.py \
        tools/boxradar-site/boxradar_site/geo/selection.example.json \
        tools/boxradar-site/tests/test_selection.py
git commit -m "feat: selection config, transcribed from CURATED_AIRPORTS

Explicit envelope grouping is what makes the dataset's awkward case ordinary:
Heathrow has no HEATHROW feature because its zone is LONDON CTR and its CTA is
the TMA, so it is a primary with an empty envelope rather than the case that
breaks name inference.

Unlike the METAR config this raises on a malformed file. A bad runway table
costs a runway recommendation; a bad selection would silently draw a map with
airspace missing."
```

---

### Task 7: Emit the header, and prove equivalence

The gate for the whole phase.

**Files:**
- Create: `tools/boxradar-site/boxradar_site/geo/emit.py`
- Create: `tools/boxradar-site/boxradar_site/geo/__main__.py`
- Test: `tools/boxradar-site/tests/test_regression_airspace.py`
- Delete: `tools/build_airspace.py`

**Interfaces:**
- Consumes: everything from tasks 2–6
- Produces:
  - `build_airspace_outlines(sel, features) -> tuple[list[tuple[str, list]], list[str]]` — `(outlines, problems)`
  - `render_header(outlines) -> str`
  - `parse_header(text) -> dict[str, list[tuple[float, float]]]` — reads a generated header back, for the regression test
  - CLI: `python3 -m boxradar_site.geo list|suggest|build`

- [ ] **Step 1: Write the failing regression test**

Create `tools/boxradar-site/tests/test_regression_airspace.py`:

```python
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
        cls.generated = {name: [(lat, lon) for lat, lon in
                                [(p[1], p[0]) for p in ring]]
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
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL with `ImportError: cannot import name 'emit'`

- [ ] **Step 3: Write emit.py**

Create `tools/boxradar-site/boxradar_site/geo/emit.py`:

```python
"""Build outlines from a selection, and render src/ui/airspace_data.h.

The header format is unchanged from tools/build_airspace.py so the firmware
needs no change in this phase. The binary blob is phase 2b.
"""

import re

from .outlines import build_outlines, check_ring
from .yaixm import feature_rings


def _find(features, name):
    for f in features:
        if f.get("name") == name:
            return f
    return None


def build_airspace_outlines(sel, features):
    """(outlines, problems) for a selection.

    Problems are collected rather than raised, so a UI can show all of them at
    once instead of one per run.
    """
    outlines, problems = [], []
    for group in sel.groups:
        primary = _find(features, group.primary)
        if primary is None:
            problems.append(f"{group.name}: feature "
                            f"{group.primary!r} not in the dataset")
            continue
        primary_rings = feature_rings(primary)
        if not primary_rings:
            problems.append(f"{group.name}: {group.primary!r} has no usable "
                            f"geometry")
            continue
        outlines.extend(build_outlines(f"{group.name}_CTR", primary_rings))

        env_rings = list(primary_rings)
        missing = False
        for extra in group.envelope:
            feature = _find(features, extra)
            if feature is None:
                problems.append(f"{group.name}: envelope feature "
                                f"{extra!r} not in the dataset")
                missing = True
                continue
            env_rings.extend(feature_rings(feature))
        if group.envelope and not missing:
            outlines.extend(build_outlines(f"{group.name}_ENV", env_rings))

    for name, ring in outlines:
        problems.extend(check_ring(name, ring))
    return outlines, problems


def render_header(outlines):
    out = [
        "// GENERATED by boxradar_site.geo — do not edit by hand.",
        "// Source: https://github.com/ahsparrow/airspace (airspace.yaml)",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "namespace airspace {",
        "",
        "struct Vertex { float lat, lon; };",
        "struct Outline { const Vertex *pts; uint16_t count; };",
        "",
    ]
    for name, ring in outlines:
        out.append(f"static const Vertex {name}_PTS[] = {{")
        for lon, lat in ring:
            out.append(f"    {{{lat:.5f}f, {lon:.5f}f}},")
        out.append("};")
        out.append("")
    out.append("static const Outline OUTLINES[] = {")
    for name, ring in outlines:
        out.append(f"    {{{name}_PTS, {len(ring)}}},")
    out.append("};")
    out.append("")
    out.append("} // namespace airspace")
    return "\n".join(out) + "\n"


_ARRAY_RE = re.compile(r"static const Vertex (\w+)_PTS\[\] = \{(.*?)\};",
                       re.S)
_VERTEX_RE = re.compile(r"\{\s*(-?[\d.]+)f,\s*(-?[\d.]+)f\s*\}")


def parse_header(text):
    """Read a generated header back as {name: [(lat, lon), ...]}.

    Exists for the regression test: comparing against the committed header is
    the only way to prove the new pipeline reproduces the hand-curated output.
    """
    out = {}
    for name, body in _ARRAY_RE.findall(text):
        out[name] = [(float(a), float(b))
                     for a, b in _VERTEX_RE.findall(body)]
    return out
```

- [ ] **Step 4: Run the regression test**

Run: `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v`
Expected: PASS, 131 tests.

**If `test_same_outline_names` fails**, the transcription in
`selection.example.json` is wrong — compare against `CURATED_AIRPORTS` in
`tools/build_airspace.py` before it is deleted. **If
`test_every_outline_matches_within_tolerance` fails**, report the offending
outline and its distance and stop; do not raise the tolerance to make it pass.

- [ ] **Step 5: Write the CLI**

Create `tools/boxradar-site/boxradar_site/geo/__main__.py`:

```python
"""Geography generation CLI.

    python3 -m boxradar_site.geo list      --selection sel.json
    python3 -m boxradar_site.geo suggest   --selection sel.json
    python3 -m boxradar_site.geo build     --selection sel.json --out path.h

`list` is the candidate catalog as a table — the thing that replaces having to
know your local CTRs by their YAIXM names. `suggest` shows what the four
default rules would tick, and why it rejected the rest.
"""

import argparse
import pathlib
import subprocess
import sys

CACHE_DIR = pathlib.Path("~/.cache/boxradar-airspace").expanduser()
REPO_DIR = CACHE_DIR / "airspace"
YAML_PATH = REPO_DIR / "airspace.yaml"
REPO_URL = "https://github.com/ahsparrow/airspace"

PX_PER_NM_OVERVIEW = 2.2  # 50nm overview, per docs/viewport-design.md


def fetch_source():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if REPO_DIR.exists():
        subprocess.run(["git", "-C", str(REPO_DIR), "pull", "--ff-only"],
                       check=True)
    else:
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL,
                        str(REPO_DIR)], check=True)


def load_features(fetch):
    if fetch:
        fetch_source()
    if not YAML_PATH.exists():
        raise SystemExit(f"{YAML_PATH} not found — run with --fetch")
    import yaml
    with YAML_PATH.open() as f:
        return yaml.safe_load(f).get("airspace", [])


def main(argv=None):
    p = argparse.ArgumentParser(prog="boxradar_site.geo")
    p.add_argument("command", choices=["list", "suggest", "build"])
    p.add_argument("--selection", required=True)
    p.add_argument("--out")
    p.add_argument("--fetch", action="store_true",
                   help="git pull the YAIXM source first")
    p.add_argument("--kind", action="append",
                   help="restrict the listing to a kind (repeatable)")
    args = p.parse_args(argv)

    from . import catalog, emit, rules, selection
    sel = selection.load(args.selection)
    features = load_features(args.fetch)

    gone = selection.missing_features(sel, features)
    if gone:
        print(f"WARNING: {len(gone)} selected feature(s) no longer in the "
              f"dataset: {', '.join(gone)}", file=sys.stderr)

    if args.command in ("list", "suggest"):
        cands = catalog.catalog(features, sel.home_lat, sel.home_lon,
                                sel.reach_nm)
        if args.command == "list":
            if args.kind:
                cands = [c for c in cands if c.kind in args.kind]
            print(f"{'dist':>5} {'size':>5} {'px':>5} {'verts':>6} "
                  f"{'kind':<12} name")
            for c in cands:
                print(f"{c.distance_nm:>5.0f} {c.diag_nm:>5.0f} "
                      f"{c.diag_px(PX_PER_NM_OVERVIEW):>5.0f} "
                      f"{c.vertices:>6} {c.kind:<12} {c.name}")
            print(f"\n{len(cands)} features, "
                  f"{sum(c.vertices for c in cands)} vertices")
            return 0
        accepted, rejected = rules.suggest(cands)
        print(f"SUGGESTED ({len(accepted)}):")
        for c in accepted:
            print(f"  {c.name}  [{c.kind}] "
                  f"{c.diag_px(PX_PER_NM_OVERVIEW):.0f}px "
                  f"@{c.distance_nm:.0f}nm")
        print(f"\nREJECTED ({len(rejected)}), most notable first:")
        for c, reason in sorted(rejected, key=lambda t: -t[0].diag_nm)[:15]:
            print(f"  {c.name}: {reason}")
        return 0

    outlines, problems = emit.build_airspace_outlines(sel, features)
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if problems:
        return 1
    text = emit.render_header(outlines)
    if args.out:
        pathlib.Path(args.out).write_text(text)
        total = sum(len(r) for _, r in outlines)
        print(f"wrote {args.out}: {len(outlines)} outlines, {total} vertices",
              file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Exercise the CLI and confirm the header is unchanged in substance**

```bash
cd tools/boxradar-site
SEL=boxradar_site/geo/selection.example.json
python3 -m boxradar_site.geo suggest --selection $SEL | head -40
python3 -m boxradar_site.geo list --selection $SEL --kind CTR | head -20
python3 -m boxradar_site.geo build --selection $SEL --out /tmp/airspace_new.h
cd ../..
diff <(grep -c 'f,' src/ui/airspace_data.h) <(grep -c 'f,' /tmp/airspace_new.h) \
  && echo "IDENTICAL VERTEX COUNT" || echo "vertex count differs (check the regression test verdict)"
```

Expected: `suggest` lists the local CTRs/CTAs plus the TMZ and rejects
`DAVENTRY CTA` for width; `build` reports 13 outlines.

- [ ] **Step 7: Replace the generated header, verify the firmware builds**

```bash
cp /tmp/airspace_new.h src/ui/airspace_data.h
pio run -e usb
```

Expected: SUCCESS. The header's only substantive change should be the
`GENERATED by` line; confirm with `git diff --stat src/ui/airspace_data.h`.

- [ ] **Step 8: Retire the old generator and update the docs**

```bash
git rm tools/build_airspace.py
```

In `README.md`, the Relocating table row for `tools/build_airspace.py` reads
"`CURATED_AIRPORTS` — which volumes". Replace it with:

```markdown
| `tools/boxradar-site/boxradar_site/geo/selection.example.json` | which airspace to draw — copy and edit, or start from `geo suggest` | yes |
```

And after the table's following paragraph, add:

```markdown
You no longer need to know your local airspace by its YAIXM name.
`python3 -m boxradar_site.geo list --selection <file>` prints everything
within reach, with its on-screen size, distance and vertex count; `suggest`
ticks a sane starting set and explains what it rejected and why.
```

- [ ] **Step 9: Full verification and commit**

```bash
python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site
pio run -e usb
git add -A
git commit -m "feat: generate airspace from a selection config, not a hardcoded list

Retires tools/build_airspace.py and CURATED_AIRPORTS. Selection is now a JSON
config, discovery is a catalog query, and the four measured rules survive only
as a suggestion.

Equivalence with the committed header is asserted by Hausdorff distance rather
than equality, because this devShell has shapely 2.x while the receiver Pi has
1.8 from apt — different GEOS, so the same pipeline can sample the same shape
differently. An equality test would pass on one machine and fail on the other."
```

---

## Notes for whoever executes this

**The gate is Task 7's regression test.** If the generated geometry does not
match the committed header, stop and report the offending outline. Do not raise
`HAUSDORFF_TOLERANCE_DEG` and do not adjust `selection.example.json` to make
the shapes agree — the committed header is the known-good artefact a human
curated, and a mismatch means the pipeline lost something.

**Do not let `geo/` leak into the service.** Task 1's test enforces it, but the
reason matters: the METAR proxy has to keep running on a Debian Pi where
`pip install` is refused by PEP 668, and the moment `server.py` imports
anything from `geo/`, the service needs shapely to start.

**Coastline is deliberately out of scope.** `tools/build_coastline.py` already
selects purely by bounding box — there is no curation to remove — so moving it
is mechanical and belongs with the blob writer in phase 2b, where it can be
done once against the binary format rather than twice.

**Point references (airfields, runways, fixes, towns) are also out of scope**
for 2a. They need the OurAirports and GeoNames datasets and their own pickers;
airspace is the piece where the hardcoded names hurt most, and it is enough to
prove the pattern.
