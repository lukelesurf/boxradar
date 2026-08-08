# Phase 4 scoping: the site configuration UI

**Status: decisions only, nothing built.** Written at the end of the session
that delivered phases 1–3b so the reasoning survives into the next one.

Phase 4 is the last piece of
`docs/superpowers/specs/2026-08-08-runtime-site-config-design.md`: a browser UI
on the receiver Pi for picking geography and tuning the site, replacing the
selection JSON as the thing a human edits.

## What phases 1–3b already provide

Nearly all the machinery exists and is tested:

- `boxradar_site.geo.catalog` — the candidate list with kind, on-screen size,
  distance and vertex count. **This is the airspace picker's data source**, and
  `geo list` already prints it.
- `boxradar_site.geo.rules` — the four measured rules with a reason string per
  rejection. **This is the Suggest button.**
- `boxradar_site.geo.selection` — load/validate, and `missing_features()` for
  reporting names an AIRAC cycle has renamed.
- `boxradar_site.geo.blob` + `emit` + `coastline` + `points` — regeneration.
- The board consumes the blob and reports `GEO_WRONG_HOME` on a mismatch.

So phase 4 is mostly **presentation plus two new datasets**, not new logic.

## Decision: Flask, from apt

The stdlib-only rule was always "no pip, no venv" — Debian's Python is
externally managed under PEP 668 — and `apt` is outside PEP 668's scope. That
is already why shapely and PyYAML are acceptable. `python3-flask` (2.2.2) and
`python3-jinja2` are both in bookworm, so a real UI needs no venv.

**This relaxes `tests/test_dependency_boundary.py` deliberately.** Update that
test rather than working around it: the constraint it should encode is "nothing
the service needs comes from pip", not "nothing but stdlib".

## Decision: two services, not one

- `boxradar-site` — the METAR proxy. **Stays stdlib-only.** It is the thing the
  display depends on every 60 seconds, and it should not gain shapely, Flask,
  or a reason to restart when the config UI is touched.
- `boxradar-config` — the UI and the generator. Needs Flask, shapely, yaml.
  Runs on its own port and its own systemd unit.

The split costs one extra unit file and buys a weather feed that cannot be
broken by config-UI work. Given the display polls the proxy continuously and
the UI is used once per site, that is the right way round.

## Decision: lighttpd keeps serving the blob

The UI writes `site.bin` into `/var/www/html` and lighttpd serves it, which is
what already happens. That keeps ETag generation free and means the board's
fetch path is unchanged and already proven. The UI never serves the blob
itself.

## The two new datasets

| dataset | for | source | note |
|---|---|---|---|
| OurAirports `airports.csv`, `runways.csv` | airfields, runway axes | download + cache, like the YAIXM repo | filter by type/size or every farm strip appears |
| GeoNames `GB.txt` | towns | download + cache | has population — **ranks** candidates, never gates them |
| eAIP ENR 4.4 fixes | navigation fixes | **no clean machine source** — extract once, ship with the app | the only curated table |

## Interfaces, per dataset

Settled during brainstorming and unchanged: the way you know what you want
differs, so the UI does too.

- **Airspace** — the catalog as a sortable table, default filtered to
  CTR/CTA/TMZ, plus Suggest. Tick boxes; explicit envelope grouping.
- **Airfields** — search by ICAO or name, bbox-scoped, each with a separate
  centrelines tick that expands to a per-runway list.
- **Fixes** — search by ident. You know you want LOREL; you just do not want to
  hand-convert `DDMMSS.ssN`.
- **Towns** — click a map. "Which towns do I know instinctively" is a spatial
  question, so a search box is the wrong tool.

## The preview is the feature

A 240x320 canvas drawing the selected markers, labels and outlines at both the
overview and detail scales, so "are these labels too crowded?" is answered
before committing instead of by regenerating, flashing and squinting at the
shelf.

**Deliberately rough**: markers, labels and outlines only. No traffic, and
explicitly *not* a reimplementation of `datablock.cpp`'s occupancy-grid
placement. It only has to answer "is this too many labels in this area", which
a crude version does. Making it faithful means maintaining two renderers that
will drift.

## Carried-over defect to fix here

**The portal form prefills current values, so submitting saves all eight fields
rather than only the changed ones.** That defeats the handler's "blank means
keep the compiled default" rule and leaves NVS authoritative for everything —
so a later edit to a compiled default silently does not take effect. Fix by
rendering current values as `placeholder` rather than `value`. Same trap
applies to any config form this phase adds.

## Not in scope

- **Authentication.** Nothing else on this Pi has any (the METAR proxy and
  tar1090 are both open on the LAN), and adding it here alone would be
  security theatre. Worth revisiting only if the Pi ever faces the internet.
- **Editing the board's WiFi credentials.** Those live in NVS on the device and
  are set by the first-run portal. The Pi has no way to reach them, and
  pretending otherwise would be a footgun.
- **`include/location.h`.** It becomes generated output when the pickers exist;
  until then `points.render_header()` writes the same shape but is not used to
  overwrite the committed file, which carries prose worth keeping.
