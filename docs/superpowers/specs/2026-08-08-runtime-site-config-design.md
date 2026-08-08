# Runtime site configuration design

**Status: design. Nothing implemented.**

Moves site configuration out of compile-time headers and into a Raspberry Pi
application, so a second BOXRADAR can be deployed at a different location
without the PlatformIO toolchain, without editing four files, and without
regenerating geography by hand.

## Goal, and the one it is not

The driver is **reproducibility for a second unit at a different site.** Every
decision below is weighed against that, not against tidiness.

Today, relocating means editing `include/config.h`, editing
`include/location.h`, widening `BOUNDS_LAT`/`BOUNDS_LON` in
`tools/build_airspace.py`, naming the local CTRs and CTAs *exactly* as they
appear in the YAIXM source, re-running two generators, and rebuilding. The
README needs a whole "Relocating" section to describe it. The hardest step is
the one that needs local aviation knowledge: knowing which controlled airspace
matters near you and what the dataset calls it.

This is **not** a general configurability project. Anything that does not serve
a second unit at a second site is out of scope.

## What cannot move, and why

`platformio.ini` carries `-DILI9341_2_DRIVER=1`. TFT_eSPI selects its panel
driver with a preprocessor `#ifdef` and compiles exactly one; there is no
runtime switch. SPEC.md calls the CYD panel variance "a batch lottery", so
**"one binary" is really "one binary per panel variant"** and always will be.
Ship both images and have the recipient try them, or read the batch off the
board first.

Colour inversion is the luckier half — `tft.invertDisplay(bool)` exists — so
`TFT_INVERSION_ON` *can* become a config key. `SPI_FREQUENCY` and the
`LOAD_FONT*` set stay compile-time and are not site-dependent anyway.

Accepting this residual is what makes the rest tractable. The target is "all
*site* configuration is data", not "all configuration is data".

## Architecture

Three tiers, each owning exactly what it is best placed to own.

```
  datasets (shipped/downloaded, immutable)
    airspace.yaml (YAIXM)      airports.csv, runways.csv (OurAirports)
    GB.txt (GeoNames)          enroute fixes (eAIP extract, curated once)
        |
        v
  Raspberry Pi — tools/boxradar-site/
    owns:  home position, selection config, tunables, station list
    does:  METAR proxy (caching)
           geography build on config save -> static blob in the docroot
           web UI: pick references, tune filters, preview
        |
        v  HTTP (plain, LAN)
  ESP32 board
    owns:  WiFi credentials, site URL   (NVS, set by first-run portal)
    holds: last-known-good config + geography blob   (LittleFS cache)
    does:  render
```

**The Pi owns the config; the board's NVS holds only enough to find the Pi.**
This is the central decision and everything else follows from it:

- A rich browser UI costs nothing on the board — no HTTP server competing with
  the renderer for RAM or core time.
- Geography is **precomputed on config save** into a static file. lighttpd
  serves bytes; no slicing in the request path, no shapely in the hot path.
- A Pi outage degrades to "yesterday's config", not "no config", because of the
  LittleFS cache.
- Home position lives with the datasets it selects against, so the board never
  computes a bounding box.

### Storage map — no partition change required

`min_spiffs.csv`, already applied:

```
nvs,      data, nvs,     0x9000,  0x5000,     <- 20 KB   bootstrap config
otadata,  data, ota,     0xe000,  0x2000,
app0,     app,  ota_0,   0x10000, 0x1E0000,
app1,     app,  ota_1,   0x1F0000,0x1E0000,
spiffs,   data, spiffs,  0x3D0000,0x20000,    <- 128 KB  last-known-good cache
coredump, data, coredump,0x3F0000,0x10000,
```

`min_spiffs` **shrank** the data partition; it did not remove it, and it never
touched `nvs`. Nothing about this design needs a partition change, therefore
nothing needs a USB flash — it can all ship over OTA. NVS survives OTA
updates, which is the whole point; it does not survive `erase_flash`, which
must be documented so a recovery flash does not silently lose a site's setup.

Budget check: the current geography set is ~22KB (coastline ~18KB, airspace
~2.1KB, locations ~1KB plus strings) against 128KB of LittleFS — about 5x
headroom. Flash is at 55.5% (1,090,357 of 1,966,080 bytes), leaving ~855KB for
the config, portal and HTTP client code.

## Airspace: automatic selection

This replaces `CURATED_AIRPORTS` — the hardest manual step — with rules.

### Measured, at home 51.8850, 0.2350, 65nm reach

250 of 703 UK features intersect the box; 9,047 vertices.

| type | count | vertices | median diagonal @ 2.2px/nm |
|---|---|---|---|
| OTHER | 107 | 3,811 | 6px |
| ATZ | 47 | 1,716 | 12px |
| D_OTHER | 39 | 1,385 | 3px |
| D | 21 | 267 | 14px |
| CTA | 16 | 1,169 | 123px |
| CTR | 13 | 248 | 45px |
| R | 6 | 224 | 12px |
| TMA | 1 | 227 | 313px |

Largest by on-screen extent at the 50nm overview: `DAVENTRY CTA` 334px,
`LONDON TMA` 313, `COTSWOLD CTA` 278, `CLACTON CTA` 278, `PORTSMOUTH CTA` 243,
`WORTHING CTA` 235, `NORTH SEA CTA` 213.

### Three conclusions that shape the rules

1. **`CURATED_AIRPORTS` was doing editorial work, not just geographic
   selection.** `build_airspace.py` documents excluding the London TMA because
   at 50nm it is "827px of outline on its own ... it reads as an arbitrary line
   across the panel rather than as information." Six enroute CTAs are *larger
   still*. A naive `type in (CTR, CTA)` filter would therefore be **worse than
   what ships today**.

2. **`type` alone cannot express the current output.** The Stansted TMZ is
   `type: OTHER, localtype: TMZ, rules: [TMZ]`, and `OTHER` also contains 12
   MATZs, ILS feathers and gliding sites. The allowlist must key on the triple.

3. **ATZs are visual noise by construction** — 47 features, 37 vertices each
   because they are circles, all 13–16px on the overview panel.

### The rules

Applied in order, on the Pi, at config save:

1. **Bounding box** — feature bbox intersects home ± 65nm, being the overview
   range plus margin (`MAX_RANGE_NM` 50 + `MARGIN_NM` 15, the same reach
   `tools/build_coastline.py` already uses; both become config keys).
   Replaces `BOUNDS_LAT`/`BOUNDS_LON`, whose only stated purpose was guarding
   against a mistyped feature name. There are no names to mistype now, and the
   box *is* the selection criterion.
2. **Kind allowlist** on `(type, localtype, rules)`. Default `CTR`, `CTA`, and
   `TMZ` — reproducing today's editorial choice as a rule.
3. **Size ceiling** on the outline's diagonal extent. Default ~50nm (about
   110px, half the 109nm overview panel). This is the TMA exclusion promoted
   from a hardcoded omission to a measurable criterion: an outline larger than
   the panel cannot read as an enclosure, which was the original argument.
4. **Centroid distance ceiling** from home. Default 50nm. Needed because size
   alone does not catch far-but-small: `BOURNEMOUTH CTR` is 43px and ~110nm
   away, and clips the box.

All four are config, because the right thresholds are site-dependent — a
ceiling tuned against the London TMA would discard exactly the sparse
large-area airspace that *is* the picture somewhere rural.

### Open decision: CTR/CTA envelope pairing

Today each CTR is unioned with its *named* CTA into one envelope. Without
names, pairing needs a geometric rule (a CTA that contains or abuts a CTR
belongs to it), and `build_airspace.py` already documents the case that breaks
any name-prefix heuristic: Heathrow has no `HEATHROW` feature — its zone is
`LONDON CTR` and its CTA *is* the TMA.

Two candidates, to be decided by rendering both:

- **Geometric pairing with graceful degradation** — union where a containment
  or abutment test succeeds, emit the CTR alone where it does not.
- **Drop the union** — emit every volume outline separately and accept
  near-concentric lines where a CTR nests inside its CTA.

Not resolved here. `merge_rings()` already handles the genuinely-disjoint case
(the two Stansted TMZ lobes) and must keep doing so under either choice.

## Point references: curated, not filtered

Airspace and coastline are bulk background wash — nobody picks a coastline
segment. Airfields, runway centrelines, navigation fixes and towns are
different in kind, and `include/location.h` already says why:

> Markers and centrelines are deliberately separate lists: a marker is cheap
> orientation, whereas an extended centreline is a strong visual claim about
> where traffic is going. Mark plenty; draw centrelines only for the fields
> whose approach paths you actually care about.

The viewport note depends on the curated set being small and meaningful — "ten
labelled airfields, four fixes and seven towns mean something on screen names
the area wherever you zoom to." Labels cost 6px per character against
datablocks, so density is a hard constraint. **Bbox is a search scope, not a
selection.**

### What is actually being automated

The two traps the README documents are **transcription** errors, not selection
errors:

- Nominatim returning the Bedford *county centroid*, 4nm from the town.
- Runway designators being magnetic and rounded while thresholds are true — "do
  not derive `05` into `50`".

Automating selection would never have fixed either. Automating *lookup* does.
So: the human keeps choosing; the machine supplies the coordinate.

### Interface per dataset

The way you know what you want differs, so the UI does too:

| dataset | source | interface |
|---|---|---|
| Airfields | OurAirports `airports.csv` | search by ICAO or name, bbox-scoped |
| Runway axes | OurAirports `runways.csv` | per-airfield expander, tick individual runways — a field may have several and you rarely want them all |
| Fixes | eAIP ENR 4.4 extract, shipped | search by ident; you know you want LOREL and ABBOT, you just don't want to hand-convert `DDMMSS.ssN` |
| Towns | GeoNames `GB.txt` | click a map — "which towns do I know instinctively" is a spatial question, so a search box is the wrong tool |

GeoNames replaces Nominatim for towns because it is a single local file with
population per place, which removes the county-centroid trap and gives the UI a
sensible ranking. **Population ranks candidates; it never gates them** — a
smaller town you know the position of instinctively is exactly the point, and
there will be larger ones nearby that are not.

### Two details worth fixing now

**Store resolved coordinates, not just identifiers.** Ticking LOREL records the
lat/lon as resolved at pick time, plus source and ident for provenance.
Otherwise a dataset refresh can silently move a reference point between
regenerations — miserable to notice on a 240x320 panel.

**Seed the initial config from the existing `include/location.h`.** The current
ten airfields, four fixes and seven towns are already correct for this site.
Migration must produce a config that renders identically, so the first thing
verified is "nothing changed" rather than "did I remember everything".

## The preview is the feature

Today, "are these labels too crowded at 50nm?" is answered by regenerating,
uploading over OTA, and squinting at the shelf. In a browser it is answered
before committing: a 240x320 canvas drawing the selected markers, labels and
airspace outlines at both the overview and detail scales.

**Deliberately rough.** Markers, labels and outlines only; no traffic, and
explicitly *not* a reimplementation of the occupancy-grid datablock placement
in `datablock.cpp`. It only has to answer "is this too many labels in this
area", which a crude version does. Making it faithful means maintaining two
renderers that will drift.

## METAR: proxy instead of publisher

`tools/metar-feed/metar_feed.py` currently holds a hardcoded `STATIONS` dict,
runs on a 5-minute systemd timer, and writes `/var/www/html/metar.json`. It
becomes `GET /metar/<icao>`, fetching from
`https://aviationweather.gov/api/data/metar` on demand.

Its real job is **terminating TLS off the device**, and that is an
architectural constraint rather than a convenience: a TLS handshake costs tens
of KB of transient heap on an ESP32 with no PSRAM that is already holding a
76.8KB sprite, plus a CA bundle in flash.

The obligation this inherits: the timer currently guarantees at most one
upstream call per 5 minutes no matter what the board does. An on-demand proxy
can be hammered by a board bug, and METARs are issued half-hourly so there is
nothing to gain from polling harder. Therefore: **per-station server-side cache
with a short TTL, and serve stale on upstream error** rather than failing —
the same instinct as the existing `write_atomic`, applied to a cache.

The station list stops being config on either side: the board asks for what the
site config named, the proxy serves whatever is asked for.

## Geography blob format

One file per site, regenerated on config save, served static. Little-endian
throughout — the ESP32 is little-endian, so `float32` pairs are read directly
with no parsing.

```
header
  magic     "BXRG"      4 bytes
  version   u16
  reserved  u16         zero; no flags defined yet
  crc32     u32         over the payload
  homeLat   f32
  homeLon   f32
  nSections u16
section table (per section)
  kind      u16         AIRSPACE | COASTLINE | AIRFIELDS | RUNWAYS | FIXES | TOWNS
  count     u16
  offset    u32
  bytes     u32
payload
  per record: count u16, then count * (f32 lat, f32 lon)
  coastline records also carry the precomputed minLat/maxLat/minLon/maxLon
    that src/ui/coastline_data.h already uses to reject a whole segment with
    four comparisons
  named records hold a u16 offset into the string arena
string arena
  NUL-separated, at the end, loaded once into a fixed char buffer
```

Two things this buys deliberately:

**The string arena answers the RAM-lifetime question.** `location.h` names are
`const char *` into flash literals today. Loaded from a blob they must live
somewhere owned; one arena plus `u16` offsets keeps that a single allocation
and no `String`.

**`homeLat`/`homeLon` in the header let the board reject a mismatched blob.**
The README documents the current trap — "Regenerate with
tools/build_coastline.py after moving, or it will keep drawing the previous
area's coast." A header check turns that silent failure into a visible one.

Loading is into **fixed-capacity arenas with visible truncation.** The README
already documents `MAX_AIRCRAFT`'s silent cliff, where "the count pins at 32
and distant contacts vanish with no other indication". A quietly half-drawn
coastline looks exactly like correct data, so a truncated load must say so on
screen.

## Failure modes

| failure | behaviour | why |
|---|---|---|
| No config in NVS | First-run portal (AP + captive page) | The bootstrap path |
| WiFi fails to associate N times | Re-enter portal | Recoverable without tools |
| Site unreachable at boot | Render from LittleFS cache, warn in the status strip | A Pi reboot must not blank the map |
| Cache empty *and* site unreachable | Render bare scope: rings, blips, no map | Traffic still works; it is the receiver that matters |
| Blob `homeLat`/`homeLon` mismatch | Reject, keep cache, warn | Never silently draw the wrong area |
| Blob CRC fail | Reject, keep cache, warn | ditto |
| Arena truncation | Draw what fits, warn | No silent cliffs |

**OTA must never depend on the card, the Pi, or the portal.** Serial is
usually unavailable on this unit — it runs off USB power on a shelf, not
plugged into a host — so OTA is the only practical flash path. Keep a
compiled-in fallback SSID/PSK and OTA password that NVS *overrides* rather than
replaces. Anything that can leave the board unable to associate can also leave
it unable to be reflashed without opening the case.

`SPEC.md`'s non-goal "Web config portal — hardcoded config is fine for one unit
on one shelf" is **reopened**, on the grounds that the premise it rested on is
exactly what this changes.

## Testing

- `lib/radarcore` stays portable and natively tested. Blob parsing belongs
  there — it is pure byte-wrangling and the most valuable thing to test off
  device. Fixtures: a good blob, a truncated one, a bad CRC, a home mismatch.
- **Pi-side generator regression:** generate a blob for the current site and
  assert its geometry matches today's `airspace_data.h` and
  `coastline_data.h`. This is the single most valuable test in the project —
  it proves the rules reproduce the hand-curated output before anything
  relies on them.
- Airspace rule tests against the real YAIXM: the seven oversize CTAs are
  rejected, the Stansted TMZ (an `OTHER`/`TMZ`) is kept, ATZs are excluded.
- Note that `test_viewport` passing at `-std=gnu++17` while the device builds
  at `gnu++11` has already produced one break that native tests could not
  catch. Anything shared must compile under both.

## Phasing

Each phase is independently useful and gets its own plan. Order matters:
phase 2 must produce a blob before phase 3b can fetch one.

1. **METAR proxy.** Self-contained, no board risk beyond a URL. Kills the
   `STATIONS` dict.
2. **Site app skeleton + geography generator.** Dataset ingest, the four
   airspace rules, the blob writer. Gated on the regression test above:
   byte-for-byte equivalent geometry to today's headers for this site.
3. **Board runtime config.**
   - 3a. `#define` to a `Config` struct, NVS persistence, first-run portal.
     Side benefit: deletes the footgun the README warns about, where "a missing
     include makes an `#ifdef` compile to nothing" and a feature silently does
     not exist.
   - 3b. Blob fetch, LittleFS cache, arena loading, `If-None-Match` version
     poll (60s is ample next to the 2s aircraft poll).
4. **Web UI.** Pickers, filter thresholds, preview canvas.

Phases 1–3 deliver the goal if the recipient will run one generator script on
their Pi. Phase 4 removes even that, and is where the preview pays for itself.

## Non-goals

- On-device web server. The Pi has one; the renderer needs the RAM.
- SD card. The board's microSD is on VSPI at pins 5/23/18/19 while touch is on
  the same peripheral remapped to 25/33/32/39, so they contend; and
  `case.scad` has no aperture — `sd_dv` is declared at line 37 and never
  referenced. Config over HTTP needs neither.
- Runtime airspace re-filtering on the board. These are set-once-per-site
  decisions, not sofa adjustments. The Pi ships the survivors.
- Dynamic geography fetch while panning. `docs/viewport-design.md` establishes
  that detail view is always a subset of the 50nm overview — "the detail
  centre comes from a tap inside the overview, so it can never land outside
  the generated coastline/airspace extent." One fetch at boot is sufficient.
- Free panning across the UK. Would invalidate the point above and the
  `MAX_AIRCRAFT` reasoning with it.
