# BOXRADAR v2

A desk-toy ADS-B radar scope on a £15 ESP32 touchscreen. Pulls decoded
aircraft from a readsb/tar1090 receiver on the LAN and renders a north-up
radar display in the style of an ATC scope: range rings, altitude-coloured
blips with heading vectors, two-line datablocks, fading trails, local
controlled airspace and extended runway centrelines. Successor to the
ESP8266/Nokia 5110 original.

![BOXRADAR at 10nm: traffic inside the Stansted CTA, airspace outlines,
runway centrelines and airfield markers, with two-line datablocks on the
scope](docs/scope-10nm.png)

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

- Full-screen radar scope with rings at 5/10/25/50nm (tap background to
  cycle), speed-scaled heading vectors and fading position trails
- **Datablocks** in ATC style: callsign on line 1, then level in hundreds
  of feet, a climb/descent arrow and the ICAO type on line 2. Two lines at
  5/10nm, callsign only at 25/50nm
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
- Stansted/Luton CTR outlines and CTA envelopes drawn under the traffic,
  plus airfield markers and extended runway centrelines — airspace is
  generated offline from the
  [ahsparrow/airspace](https://github.com/ahsparrow/airspace) UK dataset
- Tap a blip for a detail panel: callsign, hex, type, alt, GS, track,
  vertical rate, range/bearing, RSSI, squawk
- Full-width status strip: WiFi tick/cross, aircraft **on screen** with
  the MLAT subset in brackets, range, and — with the optional METAR feed
  below — active runway, wind, cloud and restricted visibility. A stale
  feed replaces the count with a warning rather than adding a line
- Aircraft dim after 30s without a message and drop at 60s
- LDR-driven backlight dimming, RGB LED status (red no-WiFi / amber
  no-data), OTA updates with on-screen progress

## Architecture

Core 0 polls `aircraft.json` every 2s and parses it through an
ArduinoJson filter into a fixed 32-slot store (nearest-first). Core 1
renders the scope into a single 320×240 8-bit sprite and handles touch.
The two share a mutex-guarded double buffer — no JSON ever touches live
render state. Positions project through a home-centred equirectangular
approximation; `lib/radarcore` holds the portable parse/projection/
format/classification logic and is unit-tested natively.

Rendering runs in two passes with deliberately opposite orderings. Blips
draw far→near so close traffic wins overlapping pixels; datablocks place
near→far so close traffic wins the contested *space*. Blocks are placed
against an 8px occupancy grid and remember their slot per aircraft
between frames — without that memory, one blip crossing a cell boundary
cascades into every other block moving. Placement priority is: selected,
then alert squawks, then rare airframes and MLAT targets, then nearest
first.

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
colours distinct on-screen if and only if their arguments differ.

## Building

Toolchain is PlatformIO via the Nix devShell (`direnv allow` or
`nix develop`). Then:

```bash
cp include/config.example.h include/config.h   # fill in WiFi, receiver URL, home lat/lon
pio run -e usb -t upload                       # first flash over serial
pio run -e ota -t upload                       # thereafter; needs BOXRADAR_OTA_PASS in env
pio test -e native                             # unit tests, no hardware needed
```

If the display shows wrong/inverted colours, it's the CYD panel-batch
lottery — see Known Quirks in SPEC.md.

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

Edit `CURATED_AIRPORTS` in the script to change the selection. The
generator refuses to emit self-intersecting or out-of-bounds rings.

Runway centrelines are separate: a short hardcoded table of threshold
coordinates near the top of `src/ui/scope.cpp`. The axis is derived from
the two thresholds rather than a published runway heading, so the drawn
line is guaranteed to pass through both runway ends.

### METAR feed (optional, receiver-side)

`tools/metar-feed/` installs on the **receiver Pi**, not the display and
not a separate server. It polls aviationweather.gov every 5 minutes and
publishes a ~300 byte `metar.json` into the lighttpd document root, so
the display can fetch `http://<receiver>/metar.json` over plain HTTP
alongside the `aircraft.json` it already polls.

```bash
# on the receiver Pi
sudo ./install.sh          # edit STATIONS in metar_feed.py first
```

Keeping it on the receiver means the whole system stays two devices —
receiver for data, ESP32 for display — which is what makes it portable to
another location. It also avoids TLS on the ESP32: a handshake wants
~40KB of heap against a board whose floor is ~43KB with the render sprite
live.

The Pi normalises the upstream API's loose types (`visib` can be the
string `"6+"`, `wdir` can be `"VRB"`, `wgst` can be null) into fixed
always-present integers, and derives the likely active runway from the
wind. `conf` is 0 below `CALM_KT` (7) — at that point wind isn't choosing
the runway and the value is a guess, which the display marks with a `?`.

Set `METAR_URL` and `METAR_STATION` in `config.h` to consume it. Both are
optional: comment out `METAR_URL` and the whole feature compiles out, and
the status strip simply omits the weather segments.

## Relocating

Four files carry location data. Nothing else needs touching.

| file | what | in git? |
|---|---|---|
| `include/config.h` | `HOME_LAT`/`HOME_LON`, `METAR_STATION`, receiver URL, timezone | **no** — gitignored |
| `include/location.h` | airfield markers and runway thresholds to draw | yes |
| `tools/build_airspace.py` | `CURATED_AIRPORTS` — which CTR/CTA volumes | yes |
| `tools/metar-feed/metar_feed.py` | `STATIONS` — METAR stations and runway **true** headings | yes |

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
    {51.57140f, 0.69560f},   // EGMC Southend
    {52.12750f, 0.96110f},   // EGUW Wattisham
};
static constexpr RunwayAxis RUNWAYS[] = {
    {51.567200f, 0.686268f, 51.575600f, 0.704996f}, // EGMC 05/23
    {52.120602f, 0.943800f, 52.134300f, 0.968531f}, // EGUW 05/23
};
```

```python
# tools/metar-feed/metar_feed.py   (headings are TRUE)
STATIONS = {"EGMC": [("05", 54), ("23", 234)]}
```

`CURATED_AIRPORTS` in `build_airspace.py` needs the CTR/CTA feature names
exactly as they appear in the source YAML; the generator fails loudly on a
name it can't find, so a wrong guess is obvious rather than silent.

### Gotchas

- **Runway headings are TRUE, designators are MAGNETIC.** Don't derive `05`
  into `50`. Pull both thresholds and the true heading from
  [OurAirports `runways.csv`](https://davidmegginson.github.io/ourairports-data/runways.csv).
- **`MAX_AIRCRAFT` is 32** (`lib/radarcore/aircraft.h`) and the store silently
  drops the farthest beyond that. Fine for a quiet area; under a busy TMA the
  count pins at 32 and distant contacts vanish with no other indication.
- **`RANGES_NM`** (`src/ui/layout.h`) is `{5,10,25,50}`, which suits a busy
  TMA. Somewhere rural may want to start higher.
- **`isCommonType()`** (`lib/radarcore/classify.cpp`) is tuned to a London
  short-haul mix. Somewhere with heavy GA or offshore helicopter traffic will
  want a different "ordinary" list, or the amber highlight loses meaning.
- **The airspace dataset is UK-only.** `ahsparrow/airspace` covers Britain;
  the generator will not work abroad.
- **Per-unit, not per-location:** `LDR_DARK` in `src/ui_task.cpp` is
  calibrated to one board's light sensor and will differ on another — and
  again once it's behind a case bezel. Panel driver flags in
  `platformio.ini` are a batch lottery; see Known Quirks in SPEC.md.

## Layout

```
include/        config.h (gitignored), location.h (airfields + runways)
src/            net task (core 0), UI task (core 1), shared store, status LED
src/ui/         scope, datablocks, palette, status, touch, layout,
                generated airspace data
lib/radarcore/  portable domain logic: parse, projection, formatting,
                type/squawk classification
test/           native Unity tests for radarcore
tools/          airspace codegen (YAIXM → C header)
case.scad       parametric OpenSCAD enclosure (see Case, above)
```
