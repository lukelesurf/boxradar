# Airspace Overlay: Design

Date: 2026-08-04  
Status: Approved (design), implementation pending

## Purpose

Draw the local controlled airspace on the radar scope for situational
awareness: Stansted CTR + CTA and Luton CTR + CTA as dim outlines under
the existing rings/trails/blips. Minimal chart fidelity by choice. The
operator knows the airspace; the outlines just anchor traffic behaviour
to the zones.

## Scope of content

Per airport (Stansted, Luton), two closed outlines:

1. CTR ring: the surface zone boundary as published.
2. CTA envelope: the exterior ring of the union of all CTA step
   polygons plus the CTR. Internal step boundaries are deliberately not
   drawn.

No labels, no altitude annotations, no other airspace types (TMZ, TMA,
ATZ etc. excluded).

## Data pipeline

`tools/build_airspace.py` is a one-shot maintainer script, adapted from the
existing `build-airspace.py` (which moves to `tools/` and loses its
webui/GeoJSON output stage):

- Source: clone/pull `github.com/ahsparrow/airspace` into
  `~/.cache/` (existing fetch behaviour), read `airspace.yaml` (YAIXM).
- Reused unchanged: DMS coordinate parsing, arc→polyline
  interpolation (10° steps, from-point radius taking precedence over
  the stated radius), boundary→ring assembly.
- Selection: curated name list: `LONDON STANSTED CTR`,
  `LONDON STANSTED CTA`, `LONDON LUTON CTR`, `LONDON LUTON CTA`.
- Union: shapely `unary_union` of each airport's CTA steps + CTR;
  take the exterior ring as the envelope. Keep the CTR ring separately.
- Output: `src/ui/airspace_data.h`, committed. `const` flash arrays
  of `{float lat, lon}` vertices plus an index of outlines
  (`{const Vertex *pts; uint16_t count;}`). Estimated ~200 vertices
  total ≈ 1.6KB flash, zero heap.

The script is run manually when airspace changes (AIRAC-cycle rare); it
is not wired into the PlatformIO build.

devShell: add `(python3.withPackages (ps: [ ps.pyyaml ps.shapely ]))`
to `flake.nix`. Nix-provided Python rather than a venv: this is a
maintainer script in a C++ repo, not a Python project.

## Rendering

New `drawAirspace(TFT_eSprite&, float pxPerNm)` in `src/ui/scope.cpp`,
called from `drawScope()` between `fillSprite()` and `drawRings()` so
airspace sits under everything else.

- Each vertex: `radar::project(HOME_LAT, HOME_LON, lat, lon)` →
  screen px at the current `pxPerNm`; `drawLine` between consecutive
  vertices, closing last→first.
- Re-projected every frame (~200 projections is microseconds); no
  caching, so range cycling needs no invalidation logic.
- One colour for all outlines: dim blue-grey, RGB565 `0x2124`, defined
  as a named constant; expect to tune on the physical panel.
- Sprite `drawLine` clips per-pixel; off-scope vertices at close range
  are safe (worst-case coords ~±1500px, well inside int16).

## Error handling

- Generator fails loudly on unparseable coordinates or a curated name
  missing from the source (name list drift is the realistic failure).
- Firmware has no failure modes: data is compile-time const; an empty
  outline table simply draws nothing.

## Testing

- Generator: run it, sanity-check the emitted header (vertex counts,
  lat/lon bounds within ~52°N/0°E neighbourhood).
- Visual: compare scope at 25nm against tar1090's map overlay.
- No new firmware unit tests: projection is already covered by
  `test_projection`; drawing is visual.

## Out of scope (explicitly considered, rejected)

- Per-step CTA polygons / altitude-layered styling (option b/c):
  rejected for scope clutter; operator knows the vertical structure.
- Runtime YAML/GeoJSON parsing on the ESP32; static codegen instead.
- Labels on outlines; London TMA; Stansted TMZ.
