# Airspace Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw Stansted and Luton CTR outlines plus their CTA outer envelopes as dim polylines under the radar scope's existing rings/blips.

**Architecture:** A one-shot Python maintainer script (`tools/build_airspace.py`) converts the ahsparrow/airspace YAIXM source into a committed C header of lat/lon vertex arrays. The firmware projects those vertices through the existing `radar::project()` each frame and draws closed polylines first, so all other scope elements render on top. No runtime parsing, no heap, ~2KB flash.

**Tech Stack:** Python 3 + PyYAML + shapely (codegen only, via nix devShell); PlatformIO/Arduino, TFT_eSPI sprites (firmware).

**Spec:** `docs/superpowers/specs/2026-08-04-airspace-overlay-design.md`

## Global Constraints

- All build/test/codegen commands run through the devShell: prefix with `nix develop -c` (direnv is not active in non-interactive shells).
- The generated header `src/ui/airspace_data.h` is committed source. Never hand-edit it; rerun the generator.
- Rings in the generator are GeoJSON-convention `[lon, lat]` and closed (first point repeated at the end). The emitted header is `{lat, lon}` structs, still closed.
- One colour for all outlines: RGB565 `0x2124`, named constant `AIRSPACE_COLOR`.
- Conventional commits (`feat:`, `chore:`). No new documentation files.
- Working branch: `airspace-overlay`.

---

### Task 1: Python toolchain in devShell

**Files:**
- Modify: `flake.nix` (packages list, currently only `platformio`)

**Interfaces:**
- Consumes: nothing
- Produces: `nix develop -c python3` with importable `yaml` and `shapely` — required by Task 2

- [ ] **Step 1: Add Python to the devShell**

In `flake.nix`, change the `packages` list:

```nix
          packages = with pkgs; [
            # FHS-wrapped variant: PlatformIO downloads prebuilt xtensa
            # toolchains that need a normal /lib to run on NixOS
            platformio
            # airspace codegen (tools/build_airspace.py)
            (python3.withPackages (ps: [ ps.pyyaml ps.shapely ]))
          ];
```

- [ ] **Step 2: Verify the shell provides both libraries**

Run (from repo root):
```bash
git add flake.nix
nix develop -c python3 -c "import yaml, shapely; print('ok')"
```
Expected: `ok` (first run may take a minute to fetch derivations). The `git add` matters — flakes only see tracked/staged files.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: add python with pyyaml+shapely to devShell for airspace codegen" flake.nix
```

---

### Task 2: Port generator and emit airspace_data.h

**Files:**
- Move: `build-airspace.py` → `tools/build_airspace.py` (file is currently untracked at repo root)
- Create (generated): `src/ui/airspace_data.h`

**Interfaces:**
- Consumes: devShell Python from Task 1
- Produces: header defining `namespace airspace` with
  `struct Vertex { float lat, lon; };`,
  `struct Outline { const Vertex *pts; uint16_t count; };`,
  and `static const Outline OUTLINES[4]` (STANSTED_CTR, STANSTED_ENV, LUTON_CTR, LUTON_ENV; rings closed — last vertex repeats the first). Task 3 relies on these exact names.

- [ ] **Step 1: Move the script**

```bash
mkdir -p tools
mv build-airspace.py tools/build_airspace.py
```

- [ ] **Step 2: Rework the script's selection/output stages**

Keep unchanged: `_DMS_RE`, `parse_latlon`, `_parse_deg`, `_nm_to_deg`, `_deg_to_rad`, `_rad_to_deg`, `_geojson_coord`, `_interpolate_arc`, `_interpolate_circle`, `_boundary_to_ring`, `fetch_source`, `ARC_RESOLUTION`, and the cache/clone constants.

Delete: `KEEP_CLASSES`, `normalise_class`, `yaixm_to_features`, `OUTPUT_PATH` (old value), the GeoJSON imports/emission in `main()`, and the `Iterator` import.

Update the module docstring to say it generates `src/ui/airspace_data.h` for the BOXRADAR firmware (drop the webui/README references), and change `OUTPUT_PATH`:

```python
OUTPUT_PATH = REPO_ROOT / "src" / "ui" / "airspace_data.h"
```

(`REPO_ROOT = SCRIPT_DIR.parent` is already correct once the script lives in `tools/`.)

Add after the imports:

```python
from shapely.geometry import Polygon
from shapely.ops import unary_union

# (output name prefix, CTR feature name, CTA feature name)
CURATED_AIRPORTS = [
    ("STANSTED", "LONDON STANSTED CTR", "LONDON STANSTED CTA"),
    ("LUTON", "LONDON LUTON CTR", "LONDON LUTON CTA"),
]

BUFFER_DEG = 0.001     # ~60m: merges near-coincident arc discretisations
SIMPLIFY_DEG = 0.0005  # ~35m: invisible at scope scale, trims point count
```

Add the new pipeline functions:

```python
def find_feature(airspace_data: list[dict], name: str) -> dict:
    for feature in airspace_data:
        if feature.get("name") == name:
            return feature
    raise SystemExit(f"feature {name!r} not found in airspace.yaml")


def feature_rings(feature: dict) -> list[list[list[float]]]:
    """All volume boundaries of a feature as closed [lon,lat] rings."""
    rings = []
    for volume in feature.get("geometry", []):
        ring = _boundary_to_ring(volume["boundary"])
        if ring is None:
            raise SystemExit(f"unparseable boundary in {feature.get('name')!r}")
        rings.append(ring)
    return rings


def envelope_ring(rings: list[list[list[float]]]) -> list[list[float]]:
    """Exterior ring of the union of all rings, as a closed [lon,lat] ring.

    Adjacent volumes discretise shared arcs from different endpoints, so
    their edges are near- but not exactly coincident; the buffer in/out
    absorbs those slivers before taking the exterior.
    """
    polys = [Polygon(r).buffer(BUFFER_DEG) for r in rings]
    merged = unary_union(polys).buffer(-BUFFER_DEG).simplify(SIMPLIFY_DEG)
    if merged.geom_type != "Polygon":
        raise SystemExit(f"union produced {merged.geom_type}, expected Polygon")
    return [[round(lon, 6), round(lat, 6)] for lon, lat in merged.exterior.coords]


def check_ring(name: str, ring: list[list[float]]) -> None:
    if len(ring) < 4:
        raise SystemExit(f"{name}: only {len(ring)} points")
    for lon, lat in ring:
        if not (51.0 <= lat <= 53.0 and -1.2 <= lon <= 1.2):
            raise SystemExit(f"{name}: ({lat}, {lon}) outside local bounds")


def emit_header(outlines: list[tuple[str, list[list[float]]]], path: Path) -> None:
    out = [
        "// GENERATED by tools/build_airspace.py — do not edit by hand.",
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
    path.write_text("\n".join(out) + "\n")
```

Replace `main()` with:

```python
def main() -> int:
    fetch_source()
    if not YAML_PATH.exists():
        print(f"expected {YAML_PATH} after clone, not found", file=sys.stderr)
        return 1

    with YAML_PATH.open() as f:
        airspace_data = yaml.safe_load(f).get("airspace", [])
    print(f"loaded {len(airspace_data)} YAIXM entries", file=sys.stderr)

    outlines = []
    for prefix, ctr_name, cta_name in CURATED_AIRPORTS:
        ctr_rings = feature_rings(find_feature(airspace_data, ctr_name))
        if len(ctr_rings) != 1:
            raise SystemExit(f"{ctr_name!r}: expected 1 volume, got {len(ctr_rings)}")
        cta_rings = feature_rings(find_feature(airspace_data, cta_name))
        outlines.append((f"{prefix}_CTR", ctr_rings[0]))
        outlines.append((f"{prefix}_ENV", envelope_ring(ctr_rings + cta_rings)))

    for name, ring in outlines:
        check_ring(name, ring)
        print(f"{name}: {len(ring)} points", file=sys.stderr)

    emit_header(outlines, OUTPUT_PATH)
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)
    return 0
```

- [ ] **Step 3: Run the generator**

```bash
nix develop -c python3 tools/build_airspace.py
```
Expected stderr: `loaded N YAIXM entries` (N ≈ 800+), four `<NAME>: <n> points` lines (each n between 10 and ~120), `wrote .../src/ui/airspace_data.h`. Any curated-name drift or geometry problem exits non-zero with a message — that is deliberate; do not soften it.

- [ ] **Step 4: Sanity-check the emitted header**

```bash
grep -c "static const Vertex" src/ui/airspace_data.h   # expected: 4
grep -A6 "static const Outline OUTLINES" src/ui/airspace_data.h
```
Expected: `OUTLINES` has exactly 4 entries referencing `STANSTED_CTR_PTS`, `STANSTED_ENV_PTS`, `LUTON_CTR_PTS`, `LUTON_ENV_PTS`. Spot-check a Stansted CTR vertex is near `{51.9…f, 0.2…f}`.

- [ ] **Step 5: Commit**

```bash
git add tools/build_airspace.py src/ui/airspace_data.h
git commit -m "feat: airspace codegen — Stansted/Luton CTR + CTA envelopes"
```

---

### Task 3: Render airspace outlines on the scope

**Files:**
- Modify: `src/ui/scope.cpp` (includes at top; new function before `drawScope`; two-line change inside `drawScope`, currently lines 46–50)

**Interfaces:**
- Consumes: `airspace::OUTLINES` / `airspace::Vertex` / `airspace::Outline` from Task 2's header; existing `radar::project(homeLat, homeLon, lat, lon) -> radar::Vec2` (NM east/north), `HOME_LAT`/`HOME_LON` from `config.h`, `SCOPE_CX`/`SCOPE_CY` from `layout.h` — all already included by `scope.cpp`.
- Produces: nothing consumed later; visual feature.

- [ ] **Step 1: Add the include and draw function**

In `src/ui/scope.cpp`, after the existing includes (below `#include <stdio.h>`):

```cpp
#include "airspace_data.h"
```

After `SCOPE_MARGIN` (line 9), add:

```cpp
// Dim blue-grey; expect to tune on the physical panel (LCD gamma).
static constexpr uint16_t AIRSPACE_COLOR = 0x2124;

// Outlines are closed rings (last vertex repeats the first), reprojected
// every frame — ~200 projections, cheaper than caching per range change.
static void drawAirspace(TFT_eSprite &spr, float pxPerNm) {
  for (const airspace::Outline &o : airspace::OUTLINES) {
    int prevX = 0, prevY = 0;
    for (uint16_t i = 0; i < o.count; i++) {
      radar::Vec2 p =
          radar::project(HOME_LAT, HOME_LON, o.pts[i].lat, o.pts[i].lon);
      int x = SCOPE_CX + (int)(p.x * pxPerNm);
      int y = SCOPE_CY - (int)(p.y * pxPerNm);
      if (i > 0) spr.drawLine(prevX, prevY, x, y, AIRSPACE_COLOR);
      prevX = x;
      prevY = y;
    }
  }
}
```

- [ ] **Step 2: Call it under everything else**

In `drawScope()`, insert the call between the `pxPerNm` computation and `drawRings` so airspace renders beneath rings, trails and blips:

```cpp
  spr.fillSprite(TFT_BLACK);
  float rangeOuter = RANGES_NM[ui.rangeIdx];
  float pxPerNm = (float)(SCOPE_CX - SCOPE_MARGIN) / rangeOuter;
  drawAirspace(spr, pxPerNm);
  drawRings(spr, rangeOuter, pxPerNm);
```

(Sprite `drawLine` bounds-checks per pixel, so off-scope vertices at the 5nm range are safe; worst-case coords ~±1500px are well inside TFT_eSPI's int32 params.)

- [ ] **Step 3: Build firmware and run native tests**

```bash
nix develop -c pio run -e usb
nix develop -c pio test -e native
```
Expected: both succeed. Native tests don't compile `src/` (`test_build_src = no`), so this is a regression check, not new coverage — drawing is verified visually in Step 5.

- [ ] **Step 4: Commit**

```bash
git add src/ui/scope.cpp
git commit -m "feat: draw Stansted/Luton airspace outlines on scope"
```

- [ ] **Step 5: Flash and verify visually**

```bash
BOXRADAR_OTA_PASS=<from Vaultwarden> nix develop -c pio run -e ota -t upload
```
Then on the device, at 25nm range: Stansted CTR (rounded oblong ~8nm east of centre) with its larger CTA envelope around it; Luton CTR/envelope entering from the west edge. Cross-check shapes against tar1090's map. Confirm outlines sit *under* rings/blips/trails and don't distract at the 5nm range. If the colour is too bright/dark on the panel, adjust `AIRSPACE_COLOR` (candidates: `0x18E3` darker, `0x39C7` brighter) and re-flash.

---

## Verification checklist (post-plan)

- [ ] `git log --oneline` shows three commits (chore devShell, feat codegen, feat render)
- [ ] `src/ui/airspace_data.h` committed and regenerable (`nix develop -c python3 tools/build_airspace.py` is idempotent — rerun produces no diff)
- [ ] Firmware builds; native tests pass; overlay verified on hardware
