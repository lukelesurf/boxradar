# BOXRADAR v2

A desk-toy ADS-B radar scope on a £15 ESP32 touchscreen. Pulls decoded
aircraft from a readsb/tar1090 receiver on the LAN and renders a north-up
radar display: range rings, blips with heading vectors, fading trails,
local controlled airspace, and a range-sorted traffic list. Successor to
the ESP8266/Nokia 5110 original.

## Hardware

- **ESP32-2432S028R** — the "Cheap Yellow Display": ESP32 (dual-core
  240MHz, 520KB SRAM, no PSRAM), 2.8" ILI9341 240×320 TFT, XPT2046
  resistive touch, LDR, RGB LED
- A LAN receiver running readsb/tar1090 (or anything serving
  dump1090-style `aircraft.json`)

No wiring — everything used is on the board. Pin map and board quirks are
in [SPEC.md](SPEC.md).

## Features

- Radar scope with rings at 5/10/25/50nm (tap background to cycle),
  aircraft blips with speed-scaled heading vectors, callsign labels,
  fading position trails
- Stansted/Luton CTR outlines and CTA envelopes drawn under the traffic,
  plus unlabelled airfield markers — generated offline from the
  [ahsparrow/airspace](https://github.com/ahsparrow/airspace) UK dataset
- Tap a blip or list row for a detail panel: callsign, hex, type, alt,
  GS, track, range/bearing, RSSI
- Traffic list (callsign / altitude / type) sorted by range; status strip
  with WiFi state, aircraft count, fetch age
- Aircraft dim after 30s without a message and drop at 60s
- LDR-driven backlight dimming, RGB LED status (red no-WiFi / amber
  no-data), OTA updates with on-screen progress

## Architecture

Core 0 polls `aircraft.json` every 2s and parses it through an
ArduinoJson filter into a fixed 32-slot store (nearest-first). Core 1
renders the scope into a 240×240 sprite and handles touch. The two share
a mutex-guarded double buffer — no JSON ever touches live render state.
Positions project through a home-centred equirectangular approximation;
`lib/radarcore` holds the portable parse/projection/format logic and is
unit-tested natively.

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

The type column relies on the receiver embedding types in
`aircraft.json`: point readsb at a database with
`--db-file=/usr/local/share/tar1090/aircraft.csv.gz` (file from the
[tar1090-db](https://github.com/wiedehopf/tar1090-db) `csv` branch).
Without it the type shows as `-`.

### Regenerating airspace

`src/ui/airspace_data.h` is committed, generated output. To change which
volumes are drawn or pick up a new AIRAC cycle:

```bash
python3 tools/build_airspace.py   # inside the devShell
```

Edit `CURATED_AIRPORTS` in the script to change the selection. The
generator refuses to emit self-intersecting or out-of-bounds rings.

## Layout

```
src/            net task (core 0), UI task (core 1), shared store, status LED
src/ui/         scope, side panel, touch, layout, generated airspace data
lib/radarcore/  portable domain logic: parse, projection, formatting
test/           native Unity tests for radarcore
tools/          airspace codegen (YAIXM → C header)
```
