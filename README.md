# BOXRADAR v2

A desk-toy ADS-B radar scope on a £15 ESP32 touchscreen. Pulls decoded
aircraft from a readsb/tar1090 receiver on the LAN and renders a north-up
display in the style of an ATC scope: altitude-coloured blips with two-line
datablocks over a map of coastline, controlled airspace, runway centrelines,
airfields, navigation fixes and towns. Successor to the ESP8266/Nokia 5110
original.

![BOXRADAR in its printed wedge case, showing the 10nm range: traffic
inside the Stansted CTA, airspace outlines, runway centrelines and
airfield markers, with two-line datablocks on the
scope](docs/boxradar-case.jpg)

## Hardware

- **ESP32-2432S028R** — the "Cheap Yellow Display": ESP32 (dual-core
  240MHz, 520KB SRAM, no PSRAM), 2.8" ILI9341 240×320 TFT, XPT2046
  resistive touch, LDR, RGB LED
- A LAN receiver running readsb/tar1090 (or anything serving
  dump1090-style `aircraft.json`)

No wiring — everything used is on the board. Pin map and board quirks are
in [SPEC.md](SPEC.md).

### Case

`case.scad` is a parametric 30° wedge console enclosure in OpenSCAD: a
wedge body with standoff bosses for the board, plus a screwed-on rear
panel carrying a cable exit notch and vents. It includes a light path
drilled through the bezel for the LDR.

Set `part` at the top of the file to choose what to render —
`body_print`, `panel`, `assembly` or `fit_test`. **Print `fit_test`
first**: it's the bezel face and bosses only, so it checks board fit and
the dimensions tagged `VERIFY` in the source without committing to a full
print. Fixings are 4× M3×6 self-tap (board to bezel bosses) and 4× M3×8
(panel to corner bosses).

## Features

### Traffic

- **Datablocks** in ATC style: callsign on line 1, then level in hundreds
  of feet, a climb/descent arrow and the ICAO type on line 2. Two lines at
  5/10nm, callsign only at 25/50nm. Placed against an occupancy grid with
  per-aircraft memory so labels don't hop about
- **Blip colour encodes altitude** — red below 2000ft through orange,
  yellow, green and cyan to violet above FL300; grey on the ground
- **Rare airframes stand out**: the type field turns amber for anything
  outside the everyday short-haul fleet (A320/737 families, E-jets,
  ATR/Dash 8), so widebodies, bizjets, props, helicopters and military
  are obvious at a glance
- **MLAT positions drawn as hollow rings** — multilaterated by the feed
  network rather than transmitted by the aircraft, so a few hundred metres
  less certain than ADS-B; and in saturated airspace an aircraft not
  sending ADS-B at all is unusual in its own right
- **Squawk watch**: 7500/7600/7700 flash the blip red and raise a banner
- **Trails** are distance-gated, so the dots are evenly spaced whether
  the aircraft is a 90kt Cessna or a 450kt jet, at every range
- **Next-overhead readout** (experimental, `OVERHEAD_PREDICTION`): the
  aircraft predicted to pass closest to overhead soonest, amber when it's
  an MLAT target or a rare type. Manoeuvring aircraft are excluded rather
  than guessed at — see below
- **Tap to zoom.** Two view states rather than a cycle of ranges: a 50nm
  overview you choose from, and a 10nm (or 5nm) detail view centred on
  wherever you tapped. One gesture per state — the overview only
  navigates, the detail view only inspects — so nothing is ambiguous on a
  resistive panel. Tapping the home cross in the overview snaps back to a
  true home-centred view. See [viewport-design.md](docs/viewport-design.md)
- Tap a blip in the detail view for a panel: callsign, hex, type, alt, GS,
  track, vertical rate, range/bearing, RSSI, squawk, MLAT. Tapping the
  range readout in the status strip toggles 10nm/5nm
- Aircraft dim after 30s without a message and drop at 60s

### Map

Three marker shapes, so categories are tellable apart at 5px without
reading the label: **solid square** = airfield, **hollow square** = town,
**triangle** = navigation fix. All drawn under the traffic — a datablock
always wins where they collide.

- **OSM coastline** as the bottom layer (optional, `DRAW_COASTLINE`),
  generated offline and filtered to features ≥2km
- **Controlled airspace** — CTR outlines and CTR+CTA envelopes for
  Stansted, Luton, City, Gatwick and Southend, the Heathrow zone, and both
  Stansted TMZ lobes. Generated offline from the
  [ahsparrow/airspace](https://github.com/ahsparrow/airspace) UK dataset
- **Extended runway centrelines**, dashed, 6.5nm beyond each threshold —
  deliberately only for the fields whose approaches matter locally
- **Airfields, fixes and towns** from `include/location.h`

### Chrome and behaviour

- **Full-width status strip**: WiFi tick/cross, aircraft **on screen** with
  the MLAT subset in brackets, range, and — with the optional METAR feed —
  active runway, wind, cloud and restricted visibility. A stale feed
  replaces the count with a warning rather than adding a line
- **Night mode**: between `NIGHT_START_HOUR` and `NIGHT_END_HOUR` the panel
  fades to a dim red 7-segment clock (or to black, without `NIGHT_CLOCK`).
  A tap wakes the radar for 30s and then returns. Time comes from NTP —
  there is no RTC — and shows `--:--` rather than guessing before the first
  sync. DST is handled by a POSIX TZ rule, not a fixed offset
- LDR-driven backlight dimming, RGB LED status (red no-WiFi / amber
  no-data), OTA updates with on-screen progress

## Architecture

Core 0 polls `aircraft.json` every 2s and parses it through an
ArduinoJson filter into a fixed 32-slot store (nearest-first). Core 1
renders the scope into a single 320×240 8-bit sprite and handles touch.
The two share a mutex-guarded double buffer — no JSON ever touches live
render state. Positions project through a home-centred equirectangular
approximation; `lib/radarcore` holds the portable parse/projection/
format/classification/prediction logic and is unit-tested natively.

Rendering runs in two passes with deliberately opposite orderings. Blips
draw far→near so close traffic wins overlapping pixels; datablocks place
near→far so close traffic wins the contested *space*. Blocks are placed
against an 8px occupancy grid and remember their slot per aircraft
between frames — without that memory, one blip crossing a cell boundary
cascades into every other block moving. Placement priority is: selected,
then alert squawks, then rare airframes and MLAT targets, then nearest
first.

The coastline is an order of magnitude more geometry than everything else
on the map, so it carries per-segment bounding boxes and the panel is
converted to a lat/lon window once per frame. At 10nm inland that rejects
all of it without projecting a single point. `project()` also has a
hoisted form — the naive one recomputes `cos(homeLat)` per call, which was
costing ~19k `cosf` a second across every map layer.

Predicting an overhead pass is easy; knowing when *not* to answer is the
hard part. Straight-line extrapolation is good for arrivals on a stable
leg and worthless for departures turning onto a SID, so steadiness is
measured as **curvature** — degrees of track change per nautical mile —
which needs no timestamps and holds at any speed.

MLAT requires the receiver to be feeding a network that returns results —
here an `mlat-client` feeding ADSBExchange with
`--results beast,connect,127.0.0.1:30104`, which readsb ingests via
`--net-bi-port`. Without that the `type` field is `adsb_icao` throughout
and no blip is ever hollow. Note `type` (position source) and `t`
(airframe type designator) are unrelated fields that collide confusingly
in the dump1090 schema.

The sprite is 8-bit, so TFT_eSPI quantizes colours to RGB332 — 3 bits
red, 3 green, 2 blue. `src/ui/palette.h` builds its constants from those
surviving components rather than from 565 literals, which makes two
colours distinct on-screen if and only if their arguments differ. The
entire dark-grey range is three rungs, and the map layers use all of them.

Design notes live in [docs/](docs/) — see
[viewport-design.md](docs/viewport-design.md) for the reasoning behind the
tap-to-zoom model and the objections it sidesteps.

## Building

Toolchain is PlatformIO via the Nix devShell (`direnv allow` or
`nix develop`). Then:

```bash
cp include/config.example.h include/config.h   # fill in WiFi, receiver URL, home lat/lon
pio run -e usb -t upload                       # first flash over serial
pio run -e ota -t upload                       # thereafter; needs BOXRADAR_OTA_PASS in env
pio test -e native                             # unit tests, no hardware needed
```

Partitions are `min_spiffs.csv`: both OTA slots kept, 1.875 MiB each,
with the extra space taken from a SPIFFS partition this project never
uses. Changing the partition scheme **cannot be done over OTA** — see
SPEC.md.

If the display shows wrong/inverted colours, it's the CYD panel-batch
lottery — see Known Quirks in SPEC.md.

### Debug build flags

Compile out entirely unless requested:

```bash
PLATFORMIO_BUILD_FLAGS=-DBOXRADAR_FRAME_TIME pio run -e ota -t upload
```

- `BOXRADAR_FRAME_TIME` — frame cost in the top-right: `R` is building the
  sprite, `P` is the SPI push. Splits the two halves that get conflated
  when guessing about performance
- `BOXRADAR_FAKE_ALERT` — stamps 7700 on the nearest aircraft, so the
  emergency path can be exercised without waiting years for a real one
- `BOXRADAR_SERIAL_TABLES` — per-poll aircraft table over serial

### Aircraft type

The type field — shown in the datablock and used to decide whether an
airframe is worth highlighting — relies on the receiver embedding types
in `aircraft.json`: point readsb at a database with
`--db-file=/usr/local/share/tar1090/aircraft.csv.gz` (file from the
[tar1090-db](https://github.com/wiedehopf/tar1090-db) `csv` branch).
Without it the type shows as `-`, and an unknown type is deliberately
treated as ordinary rather than rare — flagging every database miss
would drown the signal the highlight exists to carry.

### Regenerating airspace

`src/ui/airspace_data.h` is committed, generated output. To change which
volumes are drawn or pick up a new AIRAC cycle:

```bash
python3 tools/build_airspace.py   # inside the devShell
```

Edit `CURATED_AIRPORTS` — entries are `(prefix, CTR name, CTA name or
None)`. The CTA is optional because not every field has one; Heathrow's
zone is `LONDON CTR` sitting directly under the TMA. Multi-volume
features are merged, and genuinely disjoint ones (the two Stansted TMZ
lobes) are emitted separately rather than unioned into airspace that
doesn't exist. The generator refuses self-intersecting or out-of-bounds
rings, and `BOUNDS_LAT`/`BOUNDS_LON` are themselves location-specific.

The London TMA is deliberately absent: at 50nm it is more outline than
everything else combined, and unlike a CTR it encloses nothing you can
see, so it reads as an arbitrary line across the panel.

### Regenerating the coastline

`src/ui/coastline_data.h` is committed, generated output, drawn as the
bottom layer when `DRAW_COASTLINE` is defined. Comment that out and the
table is dropped from the build entirely (~13KB of flash) — worth doing
for a landlocked site.

```bash
python3 tools/build_coastline.py   # inside the devShell
```

It reads `HOME_LAT`/`HOME_LON` from your `config.h`, queries OpenStreetMap
via Overpass once, and caches the response per bounding box — so **re-run
it after moving**, or the scope keeps drawing the previous area's coast.

Size is controlled by `MIN_FEATURE_KM`, not by `SIMPLIFY_M`. Simplification
cannot reduce a two-point line, and estuaries contain thousands of tiny
saltmarsh rings, so tightening the tolerance alone barely helps: filtering
to features ≥2km is what takes 143KB down to 12KB, and it discards exactly
the detail that is sub-pixel at every range.

### METAR proxy (optional, receiver-side)

`tools/boxradar-site/` installs on the **receiver Pi**, not the display and
not a separate server. It answers `GET /metar/<ICAO>` on port 8081, fetching
from aviationweather.gov on demand and caching each station for 5 minutes,
so the display polls `http://<receiver>:8081/metar/EGSS` over plain HTTP
alongside the `aircraft.json` it already gets from the same box.

```bash
# on the receiver Pi
sudo ./install.sh
```

Any ICAO can be asked for — there is no station list to configure. The one
thing the Pi still needs per airfield is runway **true** headings, in
`/etc/boxradar-site/config.json`, because that is published data the request
cannot carry. A station with no entry there still returns wind, cloud and
visibility; it just reports no active runway.

Keeping it on the receiver means the whole system stays two devices —
receiver for data, ESP32 for display — which is what makes it portable to
another location. It also avoids TLS on the ESP32: a handshake wants
~40KB of heap against a board whose floor is ~46KB with the render sprite
live.

The Pi normalises the upstream API's loose types (`visib` can be the
string `"6+"`, `wdir` can be `"VRB"`, `wgst` can be null) into fixed
always-present integers, and derives the likely active runway from the
wind. `conf` is 0 below `calm_kt` (7) — at that point wind isn't choosing
the runway and the value is a guess, which the display marks with a `?`.

Cloud shows as `CLEAR` when no layers are reported: upstream reports NCD,
NSC, SKC and CAVOK identically, so the broader word is the honest one.

The cache is what makes an on-demand endpoint safe. The timer this replaced
guaranteed at most one upstream call every 5 minutes; a 300s per-station TTL
reproduces that bound, so the board's 60s poll produces 12 upstream calls an
hour rather than 60. After an upstream failure the proxy backs off for 60s and
serves the last good observation flagged `"stale":1`, because a stale METAR is
far better than none.

Set `METAR_URL` and `METAR_STATION` in `config.h` to consume it. They must
agree — the URL's last path segment names the station the firmware then picks
out of the response. Both are optional: comment out `METAR_URL` and the whole
feature compiles out, and the status strip simply omits the weather segments.

## Relocating

Five files carry location data. Nothing else needs touching.

| file | what | in git? |
|---|---|---|
| `include/config.h` | `HOME_LAT`/`HOME_LON`, `METAR_STATION`, receiver URL, timezone | **no** — gitignored |
| `include/location.h` | airfields, runway thresholds, fixes, towns | yes |
| `tools/build_airspace.py` | `CURATED_AIRPORTS` — which volumes | yes |
| `tools/build_coastline.py` | re-run it; reads `HOME_*` from `config.h` | yes |
| `/etc/boxradar-site/config.json` (on the Pi) | `runways` — stations and runway **true** headings | no — lives on the receiver |

Home coordinates stay in the gitignored `config.h` on purpose: airfield data
is published AIP material, but your own position is not, and this repo may be
mirrored somewhere public.

### Worked example: Southend-on-Sea

```c
// include/config.h
#define HOME_LAT 51.7897
#define HOME_LON 1.1533
#define METAR_STATION "EGMC"       // on the field — civil, so the
                                   // inferred runway means something

// include/location.h
static constexpr AirfieldRef AIRFIELDS[] = {
    {51.57056f, 0.69363f, "EGMC"},   // Southend
    {52.12745f, 0.95619f, "EGUW"},   // Wattisham
};
static constexpr RunwayAxis RUNWAYS[] = {
    {51.567200f, 0.686268f, 51.575600f, 0.704996f}, // EGMC 05/23
    {52.120602f, 0.943800f, 52.134300f, 0.968531f}, // EGUW 05/23
};
```

```json
// /etc/boxradar-site/config.json on the receiver Pi (headings are TRUE)
{"runways": {"EGMC": [["05", 54], ["23", 234]]}}
```

Then re-run both generators. `CURATED_AIRPORTS` needs feature names exactly
as they appear in the source YAML; the generator fails loudly on a name it
can't find, so a wrong guess is obvious rather than silent.

### Where the coordinates come from

Three different datasets, and the gaps between them are the trap:

- **Airfield ARPs and runway thresholds** —
  [OurAirports](https://davidmegginson.github.io/ourairports-data/)
  `airports.csv` and `runways.csv`. The latter gives both threshold
  coordinates per runway, which is what the centrelines want
- **3-letter VOR/NDB idents** — OurAirports `navaids.csv`
- **5-letter enroute fixes** (ABBOT, LOREL) — *not in OurAirports at all.*
  They come from the NATS eAIP ENR 4.4 significant points table, published
  as `DDMMSS.ssN/DDDMMSS.ssE` and needing conversion
- **Towns** — OSM Nominatim. Take the `town` result, not the first hit:
  querying "Bedford" returns the county centroid, 4nm from the town

### Gotchas

- **Runway headings are TRUE, designators are MAGNETIC.** Don't derive `05`
  into `50`.
- **`MAX_AIRCRAFT` is 32** (`lib/radarcore/aircraft.h`) and the store silently
  drops the farthest beyond that. Fine for a quiet area; under a busy TMA the
  count pins at 32 and distant contacts vanish with no other indication.
- **`OVERVIEW_NM` / `DETAIL_RANGES_NM`** (`src/ui/layout.h`) are `50` and
  `{10,5}`, which suits a busy TMA. Somewhere rural may want both higher.
  The overview must stay above `TWO_LINE_MAX_NM` and every detail range at or
  below it, or the datablock degradation stops matching the two states.
- **`isCommonType()`** (`lib/radarcore/classify.cpp`) is tuned to a London
  short-haul mix. Somewhere with heavy GA or offshore helicopter traffic will
  want a different "ordinary" list, or the amber highlight loses meaning.
- **The airspace dataset is UK-only.** `ahsparrow/airspace` covers Britain;
  the generator will not work abroad.
- **Feature guards need `config.h` in scope.** A missing include makes an
  `#ifdef` compile to nothing — the build succeeds and the feature silently
  doesn't exist, which is worse than a link error.
- **Per-unit, not per-location:** `LDR_DARK` and `NIGHT_CLOCK_DUTY` are
  calibrated to one board and will differ on another — and again once it's
  behind a case bezel. Panel driver flags in `platformio.ini` are a batch
  lottery; see Known Quirks in SPEC.md.

## Layout

```
include/        config.h (gitignored), location.h (airfields, runways,
                fixes, towns)
src/            net task (core 0), UI task (core 1), shared store,
                night mode, status LED
src/ui/         scope, datablocks, palette, status strip, overhead
                readout, touch, layout, generated airspace + coastline
lib/radarcore/  portable domain logic: parse, projection, formatting,
                classification, METAR, overhead prediction
test/           native Unity tests for radarcore
tools/          airspace and coastline codegen, boxradar-site (receiver-side
                METAR proxy; grows into the site config app)
docs/           design notes for work not yet done
case.scad       parametric OpenSCAD enclosure (see Case, above)
```
