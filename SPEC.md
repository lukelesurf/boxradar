# BOXRADAR v2 — Spec

ADS-B radar display on a Cheap Yellow Display. Successor to the ESP8266/Nokia 5110 original. Pulls decoded aircraft data from a local receiver over WiFi and renders a radar scope plus traffic list on a 2.8" colour touchscreen.

## Hardware

- **Board:** ESP32-2432S028R "Cheap Yellow Display" (dual-USB variant: USB-C + micro)
- **MCU:** Original ESP32 (dual core, 240MHz), 520KB SRAM, **no PSRAM**, 4MB flash
- **Display:** 2.8" ILI9341, 240x320, SPI
- **Touch:** XPT2046 resistive, on its own SPI bus
- **Also on board (optional use):** microSD slot, RGB LED, LDR (GPIO34), speaker amp (GPIO26)

### Pin map (CYD standard — verify against board on first flash)

| Function | Pins |
|---|---|
| TFT (HSPI) | MISO 12, MOSI 13, SCLK 14, CS 15, DC 2, RST -1, Backlight 21 |
| Touch XPT2046 | CLK 25, CS 33, MOSI 32, MISO 39, IRQ 36 |
| microSD (VSPI) | CS 5, MOSI 23, SCK 18, MISO 19 |
| RGB LED | R 4, G 16, B 17 (active low) |
| LDR | 34 (input only) |
| Speaker | 26 |

## Toolchain

- **PlatformIO**, Arduino framework, `board = esp32dev`
- **Libraries:**
  - `TFT_eSPI` — configure via `build_flags` in `platformio.ini` (not User_Setup.h, which gets clobbered by lib updates). Use the well-known CYD flag set (ILI9341_2_DRIVER on some batches — see Known Quirks).
  - `XPT2046_Touchscreen` on a second SPIClass instance
  - `ArduinoJson` v7
- Plain TFT_eSPI + sprites, **not LVGL**, for v2.0. LVGL is a fine later refactor if the UI grows; it's overhead we don't need for a scope and a list.

## Data source

- Receiver on LAN running readsb/tar1090 (dump1090-fa compatible)
- Poll `http://<RECEIVER_HOST>/tar1090/data/aircraft.json` (fallback: `:8080/data/aircraft.json`) every **2s**
- Parse with ArduinoJson **filter** — keep only: `hex`, `flight`, `t` (type), `lat`, `lon`, `alt_baro`, `gs`, `track`, `seen`, `rssi`
- Config (WiFi SSID/pass, receiver URL, home lat/lon) in `include/config.h`, git-ignored, with a committed `config.example.h`

*Superseded 2026-08-09: the board no longer parses JSON traffic at all. It
polls `/contacts` on the Pi's display service and decodes fixed-size binary
records the Pi has already filtered, range-sorted and capped, so the board's
traffic allocation is a constant rather than a function of how busy the sky
is — the filtered JSON document was the largest thing on the heap and grew
with traffic. ArduinoJson survives for the METAR and type-name replies.*

*Superseded 2026-08-12: `config.h` now holds `DEFAULT_` values, not the live
configuration. `siteConfigBegin()` loads those and then overlays whatever NVS
holds, so twenty-six of them are editable from the Pi's Device page without a
reflash. NVS is an overlay and never a replacement — an empty one behaves
exactly like these defaults, which is what keeps a board on WiFi and
reachable over OTA no matter what the config layer does. WiFi, the receiver
URL and the OTA credentials are deliberately not among the twenty-six.*

## Architecture

- **Core 0 — net task:** WiFi manage, HTTP poll, JSON parse into an aircraft array
- **Core 1 — UI task:** render loop, touch handling
- Shared state: fixed-size array of `Aircraft` structs (cap **32**, nearest-first if the feed exceeds it), double-buffered or mutex-guarded — no parsing into live render state
- `Aircraft` struct: hex (u32), callsign[9], type[5], lat/lon (float), alt (i32), gs/track (u16), seen (u8), plus derived screen x/y and range
- Aircraft aged out after `seen > 60s`; drawn dimmed after 30s *(both are
  settings now — `sdrop` and `sdim`; 60/30 is what they still default to)*
- Position → screen: equirectangular projection centred on home lat/lon (fine at scope ranges)

## UI

**Layout (320x240 landscape):** *(superseded 2026-08-07: the scope went
full-screen and the traffic list was dropped. A 80px column of callsigns
repeated what the datablocks already said, and giving those 80px back to the
scope bought a third more east-west coverage — which is the thing the panel
was short of. One 320x240 8-bit sprite, 76.8KB, allocated once at boot.
Ranges are settings now, not a fixed cycle: `ovnm`/`d1nm`/`d2nm`.)*
- Left ~240x240: radar scope. Range rings at selectable range (10/25/50/100nm cycle via touch on the scope), home marker centre, north-up
- Right ~80x240: traffic list sorted by range — callsign, alt (FL above transition, feet below), type
- Status strip: WiFi state, aircraft count, last-fetch age

**Scope rendering:**
- Aircraft as blips with a short heading vector; label = callsign (fallback: last 4 of hex)
- Trails: ring buffer of last N positions per aircraft, drawn as fading dots (N=10 to start)
- Selected aircraft highlighted + detail panel overlay: callsign, hex, type, alt, GS, track, range/bearing, rssi
- Render via TFT_eSPI sprites for flicker-free updates. **RAM budget:** full-screen 16-bit sprite = 150KB — do NOT do this alongside JSON parsing headroom. Render the scope as a single 240x240 sprite (115KB) OR in horizontal bands if memory gets tight; measure `esp_get_free_heap_size()` and decide.
- Rotating sweep line is a stretch goal, not MVP — it forces full-scope redraws every frame

**Touch:** *(superseded 2026-08-08 by two view states — see
[docs/viewport-design.md](docs/viewport-design.md). Originally: tap blip or
list row to select, tap background to cycle range.)*
- Overview (50nm): tap anywhere → zoom to detail centred there. Blips are
  not hit-tested at all, so "select or zoom?" is never ambiguous
- Detail (10/5nm): tap blip → select; tap background → back to overview
- Tap the range readout in the status strip → toggle 10nm/5nm
- Tap detail panel → dismiss

## OTA updates

- **ArduinoOTA**, same model as BOXRADAR v1 on the 8266
- mDNS hostname `boxradar.local`; OTA password required (define in `config.h`)
  *(superseded: the build host has no mDNS resolver, so each env's
  `upload_port` is a DHCP-reserved IP. The OTA hostname is still set — it is
  what names the board on the network — but nothing resolves it here.)*
- Partition scheme: `default.csv` (two ~1.3MB OTA app slots on the 4MB flash) — plenty for this app; do not switch to `huge_app`, it removes the second OTA slot

### Flash headroom (min_spiffs applied 2026-08-08)

**This switch has been made** — `platformio.ini` uses `min_spiffs.csv`.
Applied over USB with a preceding erase; see the caveat at the end of this
section for why it cannot be done over OTA. The rest of this section is
kept as the reasoning.


Two app slots is what makes OTA safe: the board runs from `app0` while
espota writes `app1`, and the bootloader only switches over once the image
has fully landed and verified. A failed upload leaves `app0` intact and
bootable. `huge_app.csv` is a single ~3MB slot with no OTA at all — hence
the warning above.

But size and OTA are **not** a straight trade. `min_spiffs.csv` keeps both
OTA slots and still enlarges them, by taking the space out of a SPIFFS
partition this project did not then touch (no SPIFFS/LittleFS/FS.h/SD.h usage
anywhere in `src/`, `lib/` or `include/` as of 2026-08-07):

| | `default.csv` | `min_spiffs.csv` |
|---|---|---|
| app0 / app1 (each) | 1.25 MiB | **1.875 MiB** |
| spiffs | 1.375 MiB (unused) | 128 KiB |

At ~1.06MB of firmware that moves usage from ~81% to ~54%, for no loss of
anything in use. One line when it's wanted:

```ini
board_build.partitions = min_spiffs.csv
```

**That "never touches" is no longer true, and the 128 KiB is now load-bearing.**
`src/geo_store.cpp` mounts LittleFS on that partition to cache the geography
blob, and the streaming loader needs three files at once during a swap —
`/site.bin`, `/site.new` and `/site.etag`. At ~15KB a blob that is ~30KB
against 128KiB, so the margin is wide, but it is a margin rather than a
whole unused partition. Anything that shrinks spiffs further has to be
measured against a swap, not against a single cached blob. Note the cost is
disk, not heap: streaming to a file is exactly what removed the requirement
to hold two blobs in RAM, which is what let the map reload without a reboot.

**Caveat: this cannot be applied over OTA.** espota writes an app image into
the inactive slot and never rewrites the partition table at 0x8000, and the
change moves `app1` from 0x150000 to 0x1F0000. It needs a USB flash, so it
has to wait until the board is next plugged into a host. Worth doing before
space is actually tight rather than as an emergency.

Note this is unrelated to the microSD slot — an SD-backed feature (track
history, logging) uses the card, not SPIFFS, so this change doesn't block
it.
- `ArduinoOTA.handle()` polled from the net task (core 0), not the UI loop
- During an OTA upload: pause JSON polling and rendering, show a progress bar on the TFT (onProgress callback)
- `platformio.ini` gets two envs: `[env:usb]` for first flash / recovery, `[env:ota]` with `upload_protocol = espota`, `upload_port = boxradar.local`, auth flag *(superseded 2026-08-15: one env **pair** per board — `<site>` and `<site>-usb` — each carrying its own `-DBOXRADAR_SITE_*` flag and upload address, so site data and OTA target cannot be mismatched. See Building in the README.)*

## Milestones

1. **Hello screen:** PlatformIO builds, TFT_eSPI configured, colours correct, touch reads sane coordinates
2. **Data in:** WiFi + poll + filtered parse; print aircraft table over serial
3. **Scope MVP:** rings, blips, heading vectors, labels, traffic list
4. **Interaction:** touch select, detail panel, range cycling
5. **OTA:** ArduinoOTA + mDNS + on-screen progress; verify a full update cycle over WiFi before building further
6. **Polish:** trails, aging/dimming, LDR-driven backlight dim, RGB LED as status (red no-WiFi / amber no-data / off ok)

## Known Quirks (CYD)

- Two display batch variants: some need `ILI9341_2_DRIVER` and/or inverted colours (`TFT_INVERSION_ON`). If colours look wrong, this is why — flip the flag, don't debug wiring. *Two boards bought a year apart both wanted the same pair, so the lottery is real but not a coin toss per unit.*
- Touch shares no pins with TFT but needs its own `SPIClass(VSPI)` at ~2.5MHz
- GPIO35/39/36/34 are input-only
- Micro-USB and USB-C are wired to the same serial — use either
- Backlight PWM on 21 conflicts with nothing; safe to `ledcAttach`

## Non-goals (v2.0)

- On-device Beast/raw decoding — the receiver already does CPR; we consume JSON
  *(still a non-goal, but the board consumes a binary feed the Pi renders from
  that JSON, not the JSON itself — see Data source.)*
- Web config portal — hardcoded config is fine for one unit on one shelf
  *(overtaken, and for a reason worth recording: "one unit on one shelf"
  stopped being true. A second board went to another site, at which point
  every setting that needed a reflash needed physical access to a board
  nobody there can power-cycle on request. There are now two config surfaces
  — the board's own captive portal, which only appears when WiFi association
  fails and covers the eight keys a typo could strand the board with, and the
  Pi's Device page, which covers the twenty-six that are safe to get wrong.
  The split is the whole design: nothing reachable from the LAN can cost the
  board the network that makes it reflashable.)*
- Sound, SD logging
## Geography blob

One binary file per site, written by `boxradar_site.geo` and read by
`lib/radarcore/geoblob.{h,cpp}`. **The firmware does not read it yet** — the
generated C headers are still what `scope.cpp` uses. Switching over is phase
3b; see `docs/superpowers/specs/2026-08-08-runtime-site-config-design.md`.

Little-endian throughout, since both the ESP32 and the native test host are.

```
offset  size  field
------  ----  ---------------------------------------------------------------
   0     4    magic "BXRG"
   4     2    version (u16, currently 1)
   6     2    reserved (u16, zero)
   8     4    crc32 of everything from offset 16 to end (u32)
  12     4    payload length in bytes, from offset 16 (u32)
  16     4    homeLat (f32)
  20     4    homeLon (f32)
  24     2    section count (u16)
  26     2    reserved (u16, zero)
  28     ..   section table: count * 12 bytes
              u16 kind, u16 recordCount, u32 offset, u32 byteLength
   ..    ..   section payloads, each 4-byte aligned
```

| kind | value | record |
|---|---|---|
| `AIRSPACE` | 1 | `u16 count, u16 pad, then count * (f32 lat, f32 lon)` |
| `COASTLINE` | 2 | as AIRSPACE |
| `AIRFIELDS` | 3 | `char[8] name, f32 lat, f32 lon` |
| `RUNWAYS` | 4 | `f32 lat0, f32 lon0, f32 lat1, f32 lon1` |
| `WAYPOINTS` | 5 | `char[8] name, f32 lat, f32 lon` |
| `TOWNS` | 6 | `char[8] name, f32 lat, f32 lon` |

This site's complete geography is **18,192 bytes** — 13 airspace outlines, 124
coastline segments, 10 airfields, 2 runway axes, 4 fixes, 7 towns. That is 14%
of the 128KB data partition `min_spiffs` leaves available.

### Three decisions worth not undoing

**Every vertex array is 4-byte aligned, and the `u16 pad` after each polyline
count is what achieves it.** That is the format's whole reason for existing: it
lets the board cast into the received buffer and hand out `const Vertex*`
directly, so the map costs one heap allocation instead of one per record and
the render path is identical to the flash arrays it replaces. The pad is not
spare space for a future field. An unaligned 32-bit load can fault or silently
misread on the ESP32, so `test_geoblob` asserts the alignment of every pointer
the reader hands out.

**Names are fixed-width `char[8]`, not pooled in a string arena.** The longest
label in `include/location.h` is five characters (`LOREL`, `ABBOT`), because
every character is 6px competing with datablocks — the display constraint
already bounds the data. An arena would save tens of bytes across 23 records in
exchange for offsets, a second allocation and pointer fixup. The generator
**rejects** a name over seven characters rather than truncating it: a wrong
label costs more than the bytes.

**Nothing derived is stored.** Coastline bounding boxes in particular are
computed at load, even though the C header carries them and they save most of
the per-frame reject cost. A stored bbox can disagree with its own points, and
the result is a coastline that silently fails to draw — which the README
already flags as the worst failure mode here.

### Reading it

`GeoBlob::open()` validates magic, version, CRC and length, then checks
`homeLat`/`homeLon` against the caller's configured home and returns
`GEO_WRONG_HOME` on a mismatch. That turns the documented trap — "regenerate
after moving, or it will keep drawing the previous area's coast" — from a
silent wrong-area render into a visible refusal.

All multi-byte reads go through `memcpy` into a local rather than casting a
`const uint8_t*` to a `float*`. Casting is undefined behaviour and on Xtensa
occasionally wrong in practice; a 4-byte `memcpy` at an aligned address
compiles to a single load.

The CRC is CRC-32 IEEE 802.3 (reflected, init `0xFFFFFFFF`, final xor), to
match Python's `zlib.crc32`. It is computed bitwise rather than from a table:
this runs once per load, and 18KB costs well under a millisecond at 240MHz.
`test/test_geoblob/fixture_blob.h` is generated *by* the Python writer, so the
C++ reader accepting it is the cross-language check that the two agree.
