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

## Architecture

- **Core 0 — net task:** WiFi manage, HTTP poll, JSON parse into an aircraft array
- **Core 1 — UI task:** render loop, touch handling
- Shared state: fixed-size array of `Aircraft` structs (cap **32**, nearest-first if the feed exceeds it), double-buffered or mutex-guarded — no parsing into live render state
- `Aircraft` struct: hex (u32), callsign[9], type[5], lat/lon (float), alt (i32), gs/track (u16), seen (u8), plus derived screen x/y and range
- Aircraft aged out after `seen > 60s`; drawn dimmed after 30s
- Position → screen: equirectangular projection centred on home lat/lon (fine at scope ranges)

## UI

**Layout (320x240 landscape):**
- Left ~240x240: radar scope. Range rings at selectable range (10/25/50/100nm cycle via touch on the scope), home marker centre, north-up
- Right ~80x240: traffic list sorted by range — callsign, alt (FL above transition, feet below), type
- Status strip: WiFi state, aircraft count, last-fetch age

**Scope rendering:**
- Aircraft as blips with a short heading vector; label = callsign (fallback: last 4 of hex)
- Trails: ring buffer of last N positions per aircraft, drawn as fading dots (N=10 to start)
- Selected aircraft highlighted + detail panel overlay: callsign, hex, type, alt, GS, track, range/bearing, rssi
- Render via TFT_eSPI sprites for flicker-free updates. **RAM budget:** full-screen 16-bit sprite = 150KB — do NOT do this alongside JSON parsing headroom. Render the scope as a single 240x240 sprite (115KB) OR in horizontal bands if memory gets tight; measure `esp_get_free_heap_size()` and decide.
- Rotating sweep line is a stretch goal, not MVP — it forces full-scope redraws every frame

**Touch:**
- Tap blip or list row → select aircraft
- Tap scope background → cycle range
- Tap detail panel → dismiss

## OTA updates

- **ArduinoOTA**, same model as BOXRADAR v1 on the 8266
- mDNS hostname `boxradar.local`; OTA password required (define in `config.h`)
- Partition scheme: `default.csv` (two ~1.3MB OTA app slots on the 4MB flash) — plenty for this app; do not switch to `huge_app`, it removes the second OTA slot
- `ArduinoOTA.handle()` polled from the net task (core 0), not the UI loop
- During an OTA upload: pause JSON polling and rendering, show a progress bar on the TFT (onProgress callback)
- `platformio.ini` gets two envs: `[env:usb]` for first flash / recovery, `[env:ota]` with `upload_protocol = espota`, `upload_port = boxradar.local`, auth flag

## Milestones

1. **Hello screen:** PlatformIO builds, TFT_eSPI configured, colours correct, touch reads sane coordinates
2. **Data in:** WiFi + poll + filtered parse; print aircraft table over serial
3. **Scope MVP:** rings, blips, heading vectors, labels, traffic list
4. **Interaction:** touch select, detail panel, range cycling
5. **OTA:** ArduinoOTA + mDNS + on-screen progress; verify a full update cycle over WiFi before building further
6. **Polish:** trails, aging/dimming, LDR-driven backlight dim, RGB LED as status (red no-WiFi / amber no-data / off ok)

## Known Quirks (CYD)

- Two display batch variants: some need `ILI9341_2_DRIVER` and/or inverted colours (`TFT_INVERSION_ON`). If colours look wrong, this is why — flip the flag, don't debug wiring.
- Touch shares no pins with TFT but needs its own `SPIClass(VSPI)` at ~2.5MHz
- GPIO35/39/36/34 are input-only
- Micro-USB and USB-C are wired to the same serial — use either
- Backlight PWM on 21 conflicts with nothing; safe to `ledcAttach`

## Non-goals (v2.0)

- On-device Beast/raw decoding — the receiver already does CPR; we consume JSON
- Web config portal — hardcoded config is fine for one unit on one shelf
- Sound, SD logging