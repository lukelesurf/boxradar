# BOXRADAR v2 Build (Milestones 2–4, 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the working hello-screen + OTA firmware to the full spec: polled ADS-B data, radar scope with traffic list, touch interaction, and polish (trails, dimming, LDR backlight, RGB status LED).

**Architecture:** Pure logic (projection, aircraft store, JSON parsing) lives in `lib/radarcore/` with no Arduino dependencies, unit-tested on the host via PlatformIO's `native` env. Device code splits across two FreeRTOS tasks: net task (core 0: WiFi, HTTP poll, parse, OTA) and UI task (core 1: sprite render, touch), sharing an `AircraftStore` snapshot behind a mutex. Milestone 1 + OTA already work; every device task is verified by OTA-flashing the real board.

**Tech Stack:** PlatformIO (esp32dev, Arduino framework), TFT_eSPI sprites, XPT2046_Touchscreen, ArduinoJson v7 (filtered), Unity (native tests).

## Global Constraints

- Aircraft cap: **32**, nearest-first when feed exceeds it (spec).
- Poll `RECEIVER_URL` every **2s**; parse with ArduinoJson **filter** keeping only `hex`, `flight`, `t`, `lat`, `lon`, `alt_baro`, `gs`, `track`, `seen`, `rssi` (spec).
- Age out at `seen > 60s`; draw dimmed at `seen > 30s` (spec).
- Scope sprite: single 240x240 16-bit sprite (115KB). Log `esp_get_free_heap_size()` before/after creation; if allocation fails, fall back to 8-bit colour depth — do **not** silently degrade (spec RAM budget).
- No LVGL. Plain TFT_eSPI + sprites (spec).
- Partitions stay `default.csv`; OTA must keep working after every task — it is the flash path.
- No parsing into live render state: net task publishes a complete store under mutex (spec).
- Trails: ring buffer of last **10** positions per aircraft (spec).
- Conventional commits; one focused commit per task; spawn the `reviewer` agent on the task diff before each task's commit (user CLAUDE.md; test-only steps are committed with the task).
- Files 200–400 lines typical, 800 max (user CLAUDE.md).
- Known deviation from spec noted up front: `seen` is stored as `float` (feed provides 0.1s precision and we compare against 30/60s thresholds); spec suggested `u8`. 3 bytes × 32 aircraft is noise.
- `include/config.h` is git-ignored; anything configurable per-install goes there, layout/tuning constants go in `src/ui/layout.h` or `lib/radarcore/aircraft.h`.

**Device verify loop used by Tasks 4–9:** `direnv exec . pio run -e ota -t upload`, then for serial: `stty -F /dev/ttyUSB0 115200 raw -echo && timeout 15 cat /dev/ttyUSB0`. Screen checks are confirmed by Luke (he can see the board; you cannot).

## File Structure

```
lib/radarcore/            # pure logic, no Arduino headers, native-testable
  projection.h/.cpp       # equirectangular projection, range, bearing
  aircraft.h/.cpp         # Aircraft struct, AircraftStore (cap, sort, trails)
  parse.h/.cpp            # ArduinoJson filter + loadStore()
src/
  main.cpp                # setup: TFT, touch, WiFi, OTA, mutex, task spawn
  shared_state.h/.cpp     # mutex-guarded store snapshot + OTA-active flag
  net_task.h/.cpp         # core 0: poll loop, HTTP, parse, publish, OTA handle
  ui_task.h/.cpp          # core 1: sprite lifecycle, render loop, LDR backlight
  status_led.h/.cpp       # RGB LED status (polish)
  ui/
    layout.h              # geometry + range table + UiState
    scope.h/.cpp          # rings, blips, vectors, labels, trails, detail panel
    side_panel.h/.cpp     # traffic list + status strip (direct TFT draw)
    touch_input.h/.cpp    # raw→screen calibration, tap dispatch
test/
  test_projection/test_main.cpp
  test_store/test_main.cpp
  test_parse/test_main.cpp
```

---

### Task 1: Native test env + projection

**Files:**
- Modify: `platformio.ini` (restructure envs, add native)
- Create: `lib/radarcore/projection.h`, `lib/radarcore/projection.cpp`
- Test: `test/test_projection/test_main.cpp`

**Interfaces:**
- Consumes: nothing.
- Produces: `radar::Vec2 {float x, y}` (NM east/north of home); `Vec2 radar::project(float homeLat, float homeLon, float lat, float lon)`; `float radar::rangeNm(const Vec2&)`; `float radar::bearingDeg(const Vec2&)` (0=N, clockwise, [0,360)).

- [ ] **Step 1: Commit the bootstrap state** (everything currently staged plus `platformio.ini` OTA fixes — this is the repo's initial commit)

```bash
git add -A && git commit -m "feat: bootstrap CYD hello screen with verified OTA flashing"
```

- [ ] **Step 2: Restructure platformio.ini so native tests don't drag in Arduino libs**

Replace the whole file with:

```ini
; BOXRADAR v2 — ESP32-2432S028R "Cheap Yellow Display"

[env]
; shared by all envs (incl. native tests): portable libs only
lib_deps =
    bblanchon/ArduinoJson @ ^7.1.0

[esp32_base]
platform = espressif32 @ ^6.4.0
board = esp32dev
framework = arduino
board_build.partitions = default.csv
monitor_speed = 115200
monitor_filters = esp32_exception_decoder
lib_deps =
    ${env.lib_deps}
    bodmer/TFT_eSPI @ ^2.5.43
    ; registry only has an untagged alpha of this lib — pin the git tag instead
    https://github.com/PaulStoffregen/XPT2046_Touchscreen.git#v1.4

; TFT_eSPI configured here, not User_Setup.h (clobbered by lib updates).
; This board's batch: ILI9341_2_DRIVER + inversion (verified on hardware).
build_flags =
    -DUSER_SETUP_LOADED=1
    -DILI9341_2_DRIVER=1
    -DTFT_INVERSION_ON=1
    -DTFT_WIDTH=240
    -DTFT_HEIGHT=320
    -DUSE_HSPI_PORT=1
    -DTFT_MISO=12
    -DTFT_MOSI=13
    -DTFT_SCLK=14
    -DTFT_CS=15
    -DTFT_DC=2
    -DTFT_RST=-1
    -DTFT_BL=21
    -DTFT_BACKLIGHT_ON=HIGH
    -DSPI_FREQUENCY=55000000
    -DSPI_READ_FREQUENCY=20000000
    -DLOAD_GLCD=1
    -DLOAD_FONT2=1
    -DLOAD_FONT4=1
    -DLOAD_FONT6=1
    -DLOAD_FONT7=1
    -DLOAD_FONT8=1
    -DLOAD_GFXFF=1
    -DSMOOTH_FONT=1

[env:usb]
extends = esp32_base
; first flash / recovery over serial

[env:ota]
extends = esp32_base
upload_protocol = espota
; DHCP-reserved address — host has no mDNS resolver for boxradar.local
upload_port = 192.0.2.20
; espota makes the BOARD connect back to the host to pull the image —
; pinned port is open in the home server's firewall (TCP 3232)
upload_flags =
    --auth=${sysenv.BOXRADAR_OTA_PASS}
    --host_port=3232

[env:native]
platform = native
build_flags = -std=gnu++17
test_build_src = no
```

- [ ] **Step 3: Write the failing projection tests**

`test/test_projection/test_main.cpp`:

```cpp
#include <unity.h>
#include "projection.h"

using namespace radar;

static void test_north_offset_is_pure_y() {
  Vec2 v = project(51.5f, -0.1f, 52.5f, -0.1f); // 1 deg north
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, v.x);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 60.0f, v.y); // 60 NM per deg lat
}

static void test_east_offset_scaled_by_cos_lat() {
  Vec2 v = project(60.0f, 0.0f, 60.0f, 1.0f); // 1 deg east at 60N
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 30.0f, v.x); // cos(60) = 0.5
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, v.y);
}

static void test_range_is_euclidean() {
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 5.0f, rangeNm({3.0f, 4.0f}));
}

static void test_bearing_quadrants() {
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, bearingDeg({0.0f, 1.0f}));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 45.0f, bearingDeg({1.0f, 1.0f}));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 90.0f, bearingDeg({1.0f, 0.0f}));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 270.0f, bearingDeg({-1.0f, 0.0f}));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_north_offset_is_pure_y);
  RUN_TEST(test_east_offset_scaled_by_cos_lat);
  RUN_TEST(test_range_is_euclidean);
  RUN_TEST(test_bearing_quadrants);
  return UNITY_END();
}
```

- [ ] **Step 4: Run tests, verify they fail**

Run: `direnv exec . pio test -e native -f test_projection`
Expected: build FAILURE — `projection.h: No such file or directory`

- [ ] **Step 5: Implement projection**

`lib/radarcore/projection.h`:

```cpp
#pragma once

namespace radar {

constexpr float NM_PER_DEG_LAT = 60.0f;

struct Vec2 {
  float x; // NM east of home
  float y; // NM north of home
};

// Equirectangular projection centred on home — fine at scope ranges.
Vec2 project(float homeLat, float homeLon, float lat, float lon);
float rangeNm(const Vec2 &v);
float bearingDeg(const Vec2 &v); // 0 = north, clockwise, [0, 360)

} // namespace radar
```

`lib/radarcore/projection.cpp`:

```cpp
#include "projection.h"
#include <math.h>

namespace radar {

Vec2 project(float homeLat, float homeLon, float lat, float lon) {
  float cosLat = cosf(homeLat * (float)M_PI / 180.0f);
  return {(lon - homeLon) * NM_PER_DEG_LAT * cosLat,
          (lat - homeLat) * NM_PER_DEG_LAT};
}

float rangeNm(const Vec2 &v) { return sqrtf(v.x * v.x + v.y * v.y); }

float bearingDeg(const Vec2 &v) {
  float b = atan2f(v.x, v.y) * 180.0f / (float)M_PI;
  return b < 0 ? b + 360.0f : b;
}

} // namespace radar
```

- [ ] **Step 6: Run tests, verify they pass**

Run: `direnv exec . pio test -e native -f test_projection`
Expected: 4 test cases: 4 succeeded

- [ ] **Step 7: Verify the esp32 build still compiles** (env restructure is the risk)

Run: `direnv exec . pio run -e ota`
Expected: SUCCESS

- [ ] **Step 8: Reviewer gate, then commit**

Spawn `reviewer` agent on `git diff` + untracked files. Fix criticals, then:

```bash
git add platformio.ini lib/radarcore test/test_projection
git commit -m "feat: radarcore projection with native test env"
```

---

### Task 2: Aircraft store — cap, nearest-first, trails

**Files:**
- Create: `lib/radarcore/aircraft.h`, `lib/radarcore/aircraft.cpp`
- Test: `test/test_store/test_main.cpp`

**Interfaces:**
- Consumes: `radar::Vec2`, `radar::project`, `radar::rangeNm` from Task 1.
- Produces (used by parse in Task 3, tasks/UI in Tasks 4–8):

```cpp
namespace radar {
constexpr int MAX_AIRCRAFT = 32;
constexpr int TRAIL_LEN = 10;
constexpr float SEEN_DIM_S = 30.0f;
constexpr float SEEN_DROP_S = 60.0f;

struct TrailPoint { float lat, lon; };

struct Aircraft {
  uint32_t hex;
  char callsign[9];   // trimmed, NUL-terminated
  char type[5];
  float lat, lon;
  int32_t altFt;      // 0 when feed reports "ground"
  bool onGround;
  uint16_t gsKt;
  uint16_t trackDeg;
  float seenS;
  float rssi;
  Vec2 pos;           // NM east/north of home
  float range;        // NM
  int16_t sx, sy;     // screen coords, filled by UI at render time
  TrailPoint trail[TRAIL_LEN];
  uint8_t trailLen;
  uint8_t trailHead;  // next write slot
};

struct AircraftStore {
  Aircraft list[MAX_AIRCRAFT];
  int count = 0;
  uint32_t lastFetchMs = 0; // millis() of last successful poll
  bool fetchOk = false;
  void clear();
  void insertByRange(const Aircraft &a); // sorted asc by range, cap 32
  const Aircraft *findByHex(uint32_t hex) const;
  Aircraft *findByHex(uint32_t hex);
  void inheritTrails(const AircraftStore &prev); // carry + push current pos
};
}
```

- [ ] **Step 1: Write the failing store tests**

`test/test_store/test_main.cpp`:

```cpp
#include <unity.h>
#include <string.h>
#include "aircraft.h"

using namespace radar;

static Aircraft mk(uint32_t hex, float range, float lat = 51.0f, float lon = 0.0f) {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = hex;
  a.range = range;
  a.lat = lat;
  a.lon = lon;
  return a;
}

static void test_insert_keeps_sorted_by_range() {
  AircraftStore s;
  s.clear();
  s.insertByRange(mk(1, 30.0f));
  s.insertByRange(mk(2, 10.0f));
  s.insertByRange(mk(3, 20.0f));
  TEST_ASSERT_EQUAL(3, s.count);
  TEST_ASSERT_EQUAL_UINT32(2, s.list[0].hex);
  TEST_ASSERT_EQUAL_UINT32(3, s.list[1].hex);
  TEST_ASSERT_EQUAL_UINT32(1, s.list[2].hex);
}

static void test_cap_drops_farthest() {
  AircraftStore s;
  s.clear();
  for (int i = 0; i < MAX_AIRCRAFT; i++) s.insertByRange(mk(100 + i, 50.0f + i));
  TEST_ASSERT_EQUAL(MAX_AIRCRAFT, s.count);
  s.insertByRange(mk(999, 1.0f)); // nearer than all: displaces the farthest
  TEST_ASSERT_EQUAL(MAX_AIRCRAFT, s.count);
  TEST_ASSERT_EQUAL_UINT32(999, s.list[0].hex);
  TEST_ASSERT_NULL(s.findByHex(100 + MAX_AIRCRAFT - 1));
  s.insertByRange(mk(888, 500.0f)); // farther than all: rejected
  TEST_ASSERT_NULL(s.findByHex(888));
}

static void test_trails_carried_and_appended() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 51.10f, 0.10f);
  a.trail[0] = {51.08f, 0.08f};
  a.trail[1] = {51.09f, 0.09f};
  a.trailLen = 2;
  a.trailHead = 2;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.1f, 51.11f, 0.11f)); // moved
  next.insertByRange(mk(7, 2.0f, 51.01f, 0.01f));  // new aircraft
  next.inheritTrails(prev);

  const Aircraft *c = next.findByHex(42);
  TEST_ASSERT_NOT_NULL(c);
  TEST_ASSERT_EQUAL_UINT8(3, c->trailLen); // 2 inherited + current pos
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 51.11f, c->trail[2].lat);
  const Aircraft *n = next.findByHex(7);
  TEST_ASSERT_EQUAL_UINT8(1, n->trailLen); // first sighting seeds trail
}

static void test_trail_not_duplicated_when_stationary() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 51.10f, 0.10f);
  a.trail[0] = {51.10f, 0.10f};
  a.trailLen = 1;
  a.trailHead = 1;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 51.10f, 0.10f)); // same position
  next.inheritTrails(prev);
  TEST_ASSERT_EQUAL_UINT8(1, next.findByHex(42)->trailLen);
}

static void test_trail_ring_wraps_at_capacity() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 51.0f, 0.0f);
  for (int i = 0; i < TRAIL_LEN; i++) a.trail[i] = {50.0f + i, 0.0f};
  a.trailLen = TRAIL_LEN;
  a.trailHead = 0;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 51.99f, 0.5f));
  next.inheritTrails(prev);
  const Aircraft *c = next.findByHex(42);
  TEST_ASSERT_EQUAL_UINT8(TRAIL_LEN, c->trailLen); // still capped
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 51.99f, c->trail[0].lat); // overwrote oldest
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_insert_keeps_sorted_by_range);
  RUN_TEST(test_cap_drops_farthest);
  RUN_TEST(test_trails_carried_and_appended);
  RUN_TEST(test_trail_not_duplicated_when_stationary);
  RUN_TEST(test_trail_ring_wraps_at_capacity);
  return UNITY_END();
}
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `direnv exec . pio test -e native -f test_store`
Expected: build FAILURE — `aircraft.h: No such file or directory`

- [ ] **Step 3: Implement the store**

`lib/radarcore/aircraft.h`: exactly the interface block from **Produces** above, with `#pragma once`, `#include <stdint.h>` and `#include "projection.h"` at the top.

`lib/radarcore/aircraft.cpp`:

```cpp
#include "aircraft.h"
#include <math.h>
#include <string.h>

namespace radar {

void AircraftStore::clear() {
  count = 0;
}

void AircraftStore::insertByRange(const Aircraft &a) {
  int i = 0;
  while (i < count && list[i].range <= a.range) i++;
  if (i >= MAX_AIRCRAFT) return; // farther than everything in a full list
  int moveEnd = (count < MAX_AIRCRAFT) ? count : MAX_AIRCRAFT - 1;
  memmove(&list[i + 1], &list[i], (moveEnd - i) * sizeof(Aircraft));
  list[i] = a;
  if (count < MAX_AIRCRAFT) count++;
}

const Aircraft *AircraftStore::findByHex(uint32_t hex) const {
  for (int i = 0; i < count; i++)
    if (list[i].hex == hex) return &list[i];
  return nullptr;
}

Aircraft *AircraftStore::findByHex(uint32_t hex) {
  return const_cast<Aircraft *>(
      static_cast<const AircraftStore *>(this)->findByHex(hex));
}

static void pushTrailPoint(Aircraft &a) {
  if (a.trailLen > 0) {
    const TrailPoint &last = a.trail[(a.trailHead + TRAIL_LEN - 1) % TRAIL_LEN];
    // ~1e-4 deg =~ 10m: skip stationary aircraft so trails show movement
    if (fabsf(last.lat - a.lat) < 1e-4f && fabsf(last.lon - a.lon) < 1e-4f)
      return;
  }
  a.trail[a.trailHead] = {a.lat, a.lon};
  a.trailHead = (a.trailHead + 1) % TRAIL_LEN;
  if (a.trailLen < TRAIL_LEN) a.trailLen++;
}

void AircraftStore::inheritTrails(const AircraftStore &prev) {
  for (int i = 0; i < count; i++) {
    Aircraft &a = list[i];
    const Aircraft *p = prev.findByHex(a.hex);
    if (p) {
      memcpy(a.trail, p->trail, sizeof(a.trail));
      a.trailLen = p->trailLen;
      a.trailHead = p->trailHead;
    }
    pushTrailPoint(a);
  }
}

} // namespace radar
```

Note for the ring-wrap test: with `trailLen == TRAIL_LEN` and `trailHead == 0`, the "last written" slot is index `TRAIL_LEN - 1` and the new point lands at index 0 — that is what the test asserts.

- [ ] **Step 4: Run tests, verify they pass**

Run: `direnv exec . pio test -e native -f test_store`
Expected: 5 test cases: 5 succeeded

- [ ] **Step 5: Reviewer gate, then commit**

```bash
git add lib/radarcore/aircraft.h lib/radarcore/aircraft.cpp test/test_store
git commit -m "feat: aircraft store with range-sorted cap and position trails"
```

---

### Task 3: JSON parsing with filter

**Files:**
- Create: `lib/radarcore/parse.h`, `lib/radarcore/parse.cpp`
- Test: `test/test_parse/test_main.cpp`

**Interfaces:**
- Consumes: `AircraftStore`, `Aircraft`, `SEEN_DROP_S` (Task 2); `project`, `rangeNm` (Task 1).
- Produces:

```cpp
namespace radar {
// Filter doc for deserializeJson: keeps only the 10 spec fields.
void buildAircraftFilter(JsonDocument &filter);
// Load a (filtered-)deserialized aircraft.json root into dst, nearest-first,
// carrying trails from prev. Skips entries without lat/lon or seen > 60s.
// Returns dst.count.
int loadStore(JsonVariantConst root, AircraftStore &dst,
              const AircraftStore &prev, float homeLat, float homeLon);
}
```

- [ ] **Step 1: Write the failing parse tests**

`test/test_parse/test_main.cpp`:

```cpp
#include <unity.h>
#include <ArduinoJson.h>
#include "parse.h"

using namespace radar;

// Home for tests: 51.5, -0.1
// 4ca1d2: ~9.6 NM out. 406b9e: ~30 NM out, on ground.
// aabbcc: no position -> skipped. badcaf: seen 70s -> skipped.
static const char SAMPLE[] = R"({
  "now": 1722787200.0,
  "messages": 1234567,
  "aircraft": [
    {"hex":"4ca1d2","flight":"RYR12QD ","t":"B738","lat":51.6,"lon":-0.3,
     "alt_baro":12000,"gs":320.5,"track":270.3,"seen":0.2,"rssi":-12.3,
     "category":"A3","nav_qnh":1013.6,"version":2},
    {"hex":"406b9e","lat":51.9,"lon":0.4,"alt_baro":"ground","seen":1.0,"rssi":-30.1},
    {"hex":"aabbcc","flight":"NOPOS","seen":5.0},
    {"hex":"badcaf","lat":50.0,"lon":-3.0,"alt_baro":35000,"seen":70.0}
  ]})";

static void parseSample(JsonDocument &doc, bool filtered) {
  if (filtered) {
    JsonDocument filter;
    buildAircraftFilter(filter);
    TEST_ASSERT_FALSE(
        deserializeJson(doc, SAMPLE, DeserializationOption::Filter(filter)));
  } else {
    TEST_ASSERT_FALSE(deserializeJson(doc, SAMPLE));
  }
}

static void test_loads_positioned_recent_aircraft_nearest_first() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore dst, prev;
  prev.clear();
  int n = loadStore(doc, dst, prev, 51.5f, -0.1f);
  TEST_ASSERT_EQUAL(2, n);
  TEST_ASSERT_EQUAL_UINT32(0x4ca1d2, dst.list[0].hex); // nearer
  TEST_ASSERT_EQUAL_UINT32(0x406b9e, dst.list[1].hex);
}

static void test_field_extraction() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore dst, prev;
  prev.clear();
  loadStore(doc, dst, prev, 51.5f, -0.1f);
  const Aircraft &a = dst.list[0];
  TEST_ASSERT_EQUAL_STRING("RYR12QD", a.callsign); // trailing space trimmed
  TEST_ASSERT_EQUAL_STRING("B738", a.type);
  TEST_ASSERT_EQUAL_INT32(12000, a.altFt);
  TEST_ASSERT_FALSE(a.onGround);
  TEST_ASSERT_EQUAL_UINT16(320, a.gsKt);
  TEST_ASSERT_EQUAL_UINT16(270, a.trackDeg);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, -12.3f, a.rssi);
  TEST_ASSERT_FLOAT_WITHIN(0.5f, 9.6f, a.range);
}

static void test_ground_altitude_and_missing_fields() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore dst, prev;
  prev.clear();
  loadStore(doc, dst, prev, 51.5f, -0.1f);
  const Aircraft *g = dst.findByHex(0x406b9e);
  TEST_ASSERT_NOT_NULL(g);
  TEST_ASSERT_TRUE(g->onGround);
  TEST_ASSERT_EQUAL_INT32(0, g->altFt);
  TEST_ASSERT_EQUAL_STRING("", g->callsign); // missing flight -> empty
  TEST_ASSERT_EQUAL_UINT16(0, g->gsKt);
}

static void test_filter_strips_unwanted_fields() {
  JsonDocument doc;
  parseSample(doc, true);
  JsonObjectConst first = doc["aircraft"][0];
  TEST_ASSERT_FALSE(first["category"].is<const char *>());
  TEST_ASSERT_FALSE(first["nav_qnh"].is<float>());
  TEST_ASSERT_TRUE(first["hex"].is<const char *>());
}

static void test_trails_flow_through_loadStore() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore prev;
  prev.clear();
  {
    AircraftStore tmp;
    loadStore(doc, tmp, prev, 51.5f, -0.1f); // trailLen becomes 1 each
    prev = tmp;
  }
  AircraftStore dst;
  int n = loadStore(doc, dst, prev, 51.5f, -0.1f); // same positions again
  TEST_ASSERT_EQUAL(2, n);
  TEST_ASSERT_EQUAL_UINT8(1, dst.list[0].trailLen); // stationary: no dup
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_loads_positioned_recent_aircraft_nearest_first);
  RUN_TEST(test_field_extraction);
  RUN_TEST(test_ground_altitude_and_missing_fields);
  RUN_TEST(test_filter_strips_unwanted_fields);
  RUN_TEST(test_trails_flow_through_loadStore);
  return UNITY_END();
}
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `direnv exec . pio test -e native -f test_parse`
Expected: build FAILURE — `parse.h: No such file or directory`

- [ ] **Step 3: Implement parsing**

`lib/radarcore/parse.h`:

```cpp
#pragma once
#include <ArduinoJson.h>
#include "aircraft.h"

namespace radar {

void buildAircraftFilter(JsonDocument &filter);
int loadStore(JsonVariantConst root, AircraftStore &dst,
              const AircraftStore &prev, float homeLat, float homeLon);

} // namespace radar
```

`lib/radarcore/parse.cpp`:

```cpp
#include "parse.h"
#include <stdlib.h>
#include <string.h>
#include "projection.h"

namespace radar {

static const char *const KEPT_FIELDS[] = {"hex", "flight", "t",    "lat",
                                          "lon", "alt_baro", "gs", "track",
                                          "seen", "rssi"};

void buildAircraftFilter(JsonDocument &filter) {
  JsonObject entry = filter["aircraft"].add<JsonObject>();
  for (const char *f : KEPT_FIELDS) entry[f] = true;
}

// Copy into a fixed buffer, trimming trailing spaces (feed pads callsigns).
static void copyTrimmed(char *dst, size_t cap, const char *src) {
  if (!src) { dst[0] = '\0'; return; }
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  while (n > 0 && src[n - 1] == ' ') n--;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

int loadStore(JsonVariantConst root, AircraftStore &dst,
              const AircraftStore &prev, float homeLat, float homeLon) {
  dst.clear();
  for (JsonObjectConst o : root["aircraft"].as<JsonArrayConst>()) {
    if (!o["lat"].is<float>() || !o["lon"].is<float>()) continue;
    float seen = o["seen"] | 0.0f;
    if (seen > SEEN_DROP_S) continue;

    Aircraft a;
    memset(&a, 0, sizeof(a));
    const char *hexs = o["hex"] | "";
    a.hex = strtoul(hexs[0] == '~' ? hexs + 1 : hexs, nullptr, 16);
    copyTrimmed(a.callsign, sizeof(a.callsign), o["flight"] | (const char *)nullptr);
    copyTrimmed(a.type, sizeof(a.type), o["t"] | (const char *)nullptr);
    a.lat = o["lat"];
    a.lon = o["lon"];
    JsonVariantConst alt = o["alt_baro"];
    a.onGround = alt.is<const char *>(); // "ground"
    a.altFt = a.onGround ? 0 : (alt | 0);
    a.gsKt = (uint16_t)(o["gs"] | 0.0f);
    a.trackDeg = (uint16_t)(o["track"] | 0.0f);
    a.seenS = seen;
    a.rssi = o["rssi"] | 0.0f;
    a.pos = project(homeLat, homeLon, a.lat, a.lon);
    a.range = rangeNm(a.pos);
    dst.insertByRange(a);
  }
  dst.inheritTrails(prev);
  return dst.count;
}

} // namespace radar
```

- [ ] **Step 4: Run all native tests, verify they pass**

Run: `direnv exec . pio test -e native`
Expected: 14 test cases: 14 succeeded (4 projection + 5 store + 5 parse)

- [ ] **Step 5: Reviewer gate, then commit**

```bash
git add lib/radarcore/parse.h lib/radarcore/parse.cpp test/test_parse
git commit -m "feat: filtered aircraft.json parsing into range-capped store"
```

---

### Task 4: Net task on device — poll + serial table (Milestone 2)

**Files:**
- Create: `src/shared_state.h`, `src/shared_state.cpp`, `src/net_task.h`, `src/net_task.cpp`
- Modify: `src/main.cpp` (replace loop-based OTA with tasks; keep hello screen for now)
- Modify: `include/config.example.h` (add `POLL_INTERVAL_MS`)

**Interfaces:**
- Consumes: `loadStore`, `buildAircraftFilter` (Task 3); `AircraftStore` (Task 2); existing `setupWifi`/`setupOta` from main.cpp.
- Produces:

```cpp
// shared_state.h
extern volatile bool g_otaActive;          // set by OTA callbacks
void sharedStateInit();                    // creates the mutex
void publishStore(const radar::AircraftStore &s); // net task -> shared
void snapshotStore(radar::AircraftStore &out);    // UI task <- shared
// net_task.h
void startNetTask(); // spawns FreeRTOS task pinned to core 0
```

- [ ] **Step 1: Add poll interval to config template**

Append to `include/config.example.h` and mirror manually into your live `include/config.h`:

```cpp
#define POLL_INTERVAL_MS 2000
```

- [ ] **Step 2: Implement shared state**

`src/shared_state.h`:

```cpp
#pragma once
#include "aircraft.h"

extern volatile bool g_otaActive;

void sharedStateInit();
void publishStore(const radar::AircraftStore &s);
void snapshotStore(radar::AircraftStore &out);
```

`src/shared_state.cpp`:

```cpp
#include "shared_state.h"
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

volatile bool g_otaActive = false;

static SemaphoreHandle_t s_mutex;
static radar::AircraftStore s_store;

void sharedStateInit() {
  s_mutex = xSemaphoreCreateMutex();
  s_store.clear();
}

void publishStore(const radar::AircraftStore &s) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  s_store = s;
  xSemaphoreGive(s_mutex);
}

void snapshotStore(radar::AircraftStore &out) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  out = s_store;
  xSemaphoreGive(s_mutex);
}
```

- [ ] **Step 3: Implement the net task**

`src/net_task.h`:

```cpp
#pragma once
void startNetTask();
```

`src/net_task.cpp`:

```cpp
#include "net_task.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include "config.h"
#include "parse.h"
#include "shared_state.h"

using radar::AircraftStore;

static AircraftStore s_staging;
static AircraftStore s_prev;

static void printTable(const AircraftStore &s) {
  Serial.printf("---- %d aircraft, heap %u ----\n", s.count,
                esp_get_free_heap_size());
  Serial.println("hex    callsign type   lat      lon     alt   gs trk seen  rssi  rng");
  for (int i = 0; i < s.count; i++) {
    const radar::Aircraft &a = s.list[i];
    Serial.printf("%06lx %-8s %-4s %8.4f %8.4f %5ld %3u %3u %4.1f %5.1f %5.1f\n",
                  (unsigned long)a.hex, a.callsign, a.type, a.lat, a.lon,
                  (long)a.altFt, a.gsKt, a.trackDeg, a.seenS, a.rssi, a.range);
  }
}

static void poll() {
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(3000);
  // HTTP/1.0 disables chunked transfer so ArduinoJson can stream-parse
  http.useHTTP10(true);
  http.begin(RECEIVER_URL);
  int code = http.GET();
  if (code == HTTP_CODE_OK) {
    JsonDocument filter;
    radar::buildAircraftFilter(filter);
    JsonDocument doc;
    DeserializationError err = deserializeJson(
        doc, http.getStream(), DeserializationOption::Filter(filter));
    if (!err) {
      radar::loadStore(doc, s_staging, s_prev, HOME_LAT, HOME_LON);
      s_staging.lastFetchMs = millis();
      s_staging.fetchOk = true;
      s_prev = s_staging;
      publishStore(s_staging);
      printTable(s_staging);
    } else {
      Serial.printf("parse error: %s\n", err.c_str());
      s_prev.fetchOk = false;
      publishStore(s_prev);
    }
  } else {
    Serial.printf("http error: %d\n", code);
    s_prev.fetchOk = false;
    publishStore(s_prev);
  }
  http.end();
}

static void netTaskLoop(void *) {
  uint32_t lastPoll = 0;
  for (;;) {
    ArduinoOTA.handle();
    if (!g_otaActive && WiFi.status() == WL_CONNECTED &&
        millis() - lastPoll >= POLL_INTERVAL_MS) {
      lastPoll = millis();
      poll();
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

void startNetTask() {
  xTaskCreatePinnedToCore(netTaskLoop, "net", 12288, nullptr, 2, nullptr, 0);
}
```

- [ ] **Step 4: Rewire main.cpp**

Modify `src/main.cpp`: keep `drawTestPattern`, `drawStatus`, `setupWifi`, `setupOta` and the touch init exactly as they are. In `setupOta`, set `g_otaActive = true;` in `onStart` and `g_otaActive = false;` in `onError` (replacing the old file-local `otaActive` — delete that variable and its `loop()` usage). Add includes `"shared_state.h"`, `"net_task.h"`. New `setup()` tail and `loop()`:

```cpp
  // end of setup(), after setupWifi()/setupOta():
  sharedStateInit();
  startNetTask();
  Serial.printf("free heap after net start: %u\n", esp_get_free_heap_size());
}

void loop() {
  // Everything runs in FreeRTOS tasks; Arduino loop idles on core 1
  // until the UI task takes over in Task 5.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
```

- [ ] **Step 5: Build, flash OTA, verify serial table**

Run: `direnv exec . pio run -e ota -t upload`
Then: `stty -F /dev/ttyUSB0 115200 raw -echo && timeout 15 cat /dev/ttyUSB0`
Expected: a `---- N aircraft ----` table every ~2s with plausible rows (real callsigns, ranges ascending), heap stable across tables (compare two tables ~10s apart; no downward trend).
**Milestone 2 acceptance.** If `http error: -1`, check `RECEIVER_URL` in `config.h` resolves from the board (use the receiver's IP if `.lan` names don't resolve via your AdGuard DNS).

- [ ] **Step 6: Reviewer gate, then commit**

```bash
git add src include/config.example.h
git commit -m "feat: core-0 net task polling receiver into shared store"
```

---

### Task 5: UI task skeleton — sprite, layout, status (start of Milestone 3)

**Files:**
- Create: `src/ui/layout.h`, `src/ui/side_panel.h`, `src/ui/side_panel.cpp`, `src/ui_task.h`, `src/ui_task.cpp`
- Modify: `src/main.cpp` (hand TFT over to UI task, drop hello screen)

**Interfaces:**
- Consumes: `snapshotStore`, `g_otaActive` (Task 4).
- Produces:

```cpp
// ui/layout.h
constexpr int SCOPE_W = 240, SCOPE_H = 240, SCOPE_CX = 120, SCOPE_CY = 120;
constexpr int LIST_X = 240, LIST_W = 80;
constexpr int LIST_ROW_H = 20, LIST_ROWS = 9;   // rows area: y 0..179
constexpr int STATUS_Y = 196;                    // status strip: y 196..239
constexpr float RANGES_NM[] = {10, 25, 50, 100};
constexpr int N_RANGES = 4;
constexpr int32_t TRANSITION_ALT_FT = 6000;      // UK-ish; FL above, feet below
struct UiState {
  int rangeIdx = 1;          // default 25 NM
  uint32_t selectedHex = 0;  // 0 = none
  bool detailOpen = false;
};
// ui/side_panel.h
void drawSidePanel(TFT_eSPI &tft, const radar::AircraftStore &s, const UiState &ui);
void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround);
// ui_task.h
extern TFT_eSPI tft;         // moves from main.cpp to ui_task.cpp
void startUiTask();
```

- [ ] **Step 1: Write layout.h** (contents exactly as in Produces, plus `#pragma once` and `#include <stdint.h>`)

- [ ] **Step 2: Implement the side panel**

`src/ui/side_panel.h`:

```cpp
#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

void drawSidePanel(TFT_eSPI &tft, const radar::AircraftStore &s, const UiState &ui);
// "FL350" at/above transition, "4500" below, "GND" on ground
void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround);
```

`src/ui/side_panel.cpp`:

```cpp
#include "side_panel.h"
#include <Arduino.h>
#include <WiFi.h>
#include <stdio.h>

void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround) {
  if (onGround)
    snprintf(out, cap, "GND");
  else if (altFt >= TRANSITION_ALT_FT)
    snprintf(out, cap, "FL%03ld", (long)((altFt + 50) / 100));
  else
    snprintf(out, cap, "%ld", (long)altFt);
}

void drawSidePanel(TFT_eSPI &tft, const radar::AircraftStore &s,
                   const UiState &ui) {
  // Traffic list: two text lines per aircraft, nearest first
  for (int row = 0; row < LIST_ROWS; row++) {
    int y = row * LIST_ROW_H;
    bool has = row < s.count;
    const radar::Aircraft *a = has ? &s.list[row] : nullptr;
    bool sel = has && ui.selectedHex != 0 && a->hex == ui.selectedHex;
    uint16_t bg = sel ? TFT_NAVY : TFT_BLACK;
    tft.fillRect(LIST_X, y, LIST_W, LIST_ROW_H, bg);
    if (!has) continue;
    bool dim = a->seenS > radar::SEEN_DIM_S;
    tft.setTextColor(dim ? TFT_DARKGREY : TFT_WHITE, bg);
    char cs[9];
    snprintf(cs, sizeof(cs), "%s", a->callsign[0] ? a->callsign : "-");
    tft.drawString(cs, LIST_X + 2, y + 1, 1);
    char alt[8];
    formatAltitude(alt, sizeof(alt), a->altFt, a->onGround);
    char line2[14];
    snprintf(line2, sizeof(line2), "%-6s%s", alt, a->type);
    tft.setTextColor(dim ? TFT_DARKGREY : TFT_SILVER, bg);
    tft.drawString(line2, LIST_X + 2, y + 10, 1);
  }
  // Status strip
  tft.fillRect(LIST_X, STATUS_Y, LIST_W, 240 - STATUS_Y, TFT_BLACK);
  bool wifiOk = WiFi.status() == WL_CONNECTED;
  tft.setTextColor(wifiOk ? TFT_GREEN : TFT_RED, TFT_BLACK);
  tft.drawString(wifiOk ? "WIFI OK" : "NO WIFI", LIST_X + 2, STATUS_Y + 2, 1);
  char buf[12];
  snprintf(buf, sizeof(buf), "AC %d", s.count);
  tft.setTextColor(s.fetchOk ? TFT_WHITE : TFT_ORANGE, TFT_BLACK);
  tft.drawString(buf, LIST_X + 2, STATUS_Y + 14, 1);
  uint32_t ageS = s.lastFetchMs ? (millis() - s.lastFetchMs) / 1000 : 999;
  snprintf(buf, sizeof(buf), "AGE %lus", (unsigned long)(ageS > 999 ? 999 : ageS));
  tft.setTextColor(ageS > 10 ? TFT_ORANGE : TFT_SILVER, TFT_BLACK);
  tft.drawString(buf, LIST_X + 2, STATUS_Y + 26, 1);
}
```

- [ ] **Step 3: Implement the UI task with sprite lifecycle**

`src/ui_task.h`:

```cpp
#pragma once
#include <TFT_eSPI.h>
extern TFT_eSPI tft;
void startUiTask();
```

`src/ui_task.cpp`:

```cpp
#include "ui_task.h"
#include <Arduino.h>
#include "shared_state.h"
#include "ui/layout.h"
#include "ui/side_panel.h"

TFT_eSPI tft;
static TFT_eSprite s_scope(&tft);
static radar::AircraftStore s_snap;
static UiState s_ui;

static void createScopeSprite() {
  uint32_t before = esp_get_free_heap_size();
  s_scope.setColorDepth(16);
  if (s_scope.createSprite(SCOPE_W, SCOPE_H) == nullptr) {
    // RAM budget fallback per spec: 8-bit palette sprite (57KB vs 115KB)
    Serial.println("16-bit scope sprite failed, falling back to 8-bit");
    s_scope.setColorDepth(8);
    if (s_scope.createSprite(SCOPE_W, SCOPE_H) == nullptr) {
      Serial.println("FATAL: no scope sprite");
      for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
  }
  Serial.printf("scope sprite: heap %u -> %u\n", before,
                esp_get_free_heap_size());
}

static void uiTaskLoop(void *) {
  createScopeSprite();
  tft.fillScreen(TFT_BLACK);
  for (;;) {
    if (g_otaActive) { // OTA owns flash + screen; go quiet
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    snapshotStore(s_snap);
    s_scope.fillSprite(TFT_BLACK);
    // Placeholder centre marker until Task 6 draws the real scope
    s_scope.drawLine(SCOPE_CX - 4, SCOPE_CY, SCOPE_CX + 4, SCOPE_CY, TFT_GREEN);
    s_scope.drawLine(SCOPE_CX, SCOPE_CY - 4, SCOPE_CX, SCOPE_CY + 4, TFT_GREEN);
    s_scope.pushSprite(0, 0);
    drawSidePanel(tft, s_snap, s_ui);
    vTaskDelay(pdMS_TO_TICKS(100)); // ~10 fps
  }
}

void startUiTask() {
  xTaskCreatePinnedToCore(uiTaskLoop, "ui", 8192, nullptr, 2, nullptr, 1);
}
```

- [ ] **Step 4: Rewire main.cpp**

- Delete `TFT_eSPI tft;` from `main.cpp` and add `#include "ui_task.h"` (tft now lives in ui_task.cpp; the OTA progress callbacks keep working via the extern).
- Delete `drawTestPattern()` and the touch-echo body of `loop()` (touch handling moves to Task 7; keep the touch init lines in `setup()`).
- Keep `drawStatus` calls during boot (they draw before the UI task starts, which is fine), then at the end of `setup()`: `startUiTask();` after `startNetTask();`.

- [ ] **Step 5: Build, flash OTA, verify**

Run: `direnv exec . pio run -e ota -t upload`, then serial capture as in Task 4.
Expected on serial: `scope sprite: heap X -> Y` with X−Y ≈ 118000 (16-bit path taken, not the fallback), tables still flowing, heap stable.
Expected on screen (Luke confirms): black scope with green centre cross, traffic list on the right updating every ~2s, status strip showing WIFI OK / AC n / AGE 0-2s.

- [ ] **Step 6: Reviewer gate, then commit**

```bash
git add src
git commit -m "feat: core-1 UI task with scope sprite, traffic list and status strip"
```

---

### Task 6: Scope rendering — rings, blips, vectors, labels (Milestone 3)

**Files:**
- Create: `src/ui/scope.h`, `src/ui/scope.cpp`
- Modify: `src/ui_task.cpp` (replace placeholder with `drawScope`)

**Interfaces:**
- Consumes: `AircraftStore` (mutable snapshot — fills `sx`/`sy` per aircraft), `UiState`, layout constants; `HOME_LAT`/`HOME_LON` from config.
- Produces: `void drawScope(TFT_eSprite &spr, radar::AircraftStore &s, const UiState &ui);` — draws everything scope-side including (from Task 8) trails and (from Task 7) the detail panel. Fills `a.sx`/`a.sy` (or `-1000` when off-scope) for touch hit-testing.

- [ ] **Step 1: Implement the scope**

`src/ui/scope.h`:

```cpp
#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

void drawScope(TFT_eSprite &spr, radar::AircraftStore &s, const UiState &ui);
```

`src/ui/scope.cpp`:

```cpp
#include "scope.h"
#include <math.h>
#include <stdio.h>

static constexpr int SCOPE_MARGIN = 6; // outer ring inset from sprite edge

static void drawRings(TFT_eSprite &spr, float rangeNmOuter, float pxPerNm) {
  for (int i = 1; i <= 2; i++) { // rings at 1/2 and full range
    int r = (int)(pxPerNm * rangeNmOuter * i / 2.0f);
    spr.drawCircle(SCOPE_CX, SCOPE_CY, r, TFT_DARKGREEN);
  }
  // Range legend, bottom-left of scope
  char buf[10];
  snprintf(buf, sizeof(buf), "%.0fnm", rangeNmOuter);
  spr.setTextColor(TFT_GREEN, TFT_BLACK);
  spr.drawString(buf, 4, SCOPE_H - 12, 1);
  // Home marker
  spr.drawLine(SCOPE_CX - 4, SCOPE_CY, SCOPE_CX + 4, SCOPE_CY, TFT_GREEN);
  spr.drawLine(SCOPE_CX, SCOPE_CY - 4, SCOPE_CX, SCOPE_CY + 4, TFT_GREEN);
}

static void drawBlip(TFT_eSprite &spr, const radar::Aircraft &a, bool selected) {
  bool dim = a.seenS > radar::SEEN_DIM_S;
  uint16_t col = selected ? TFT_YELLOW : (dim ? TFT_DARKGREY : TFT_CYAN);
  spr.fillCircle(a.sx, a.sy, 2, col);
  // Heading vector: 6px + 1px per 30kt, in track direction (north-up scope)
  float rad = a.trackDeg * (float)M_PI / 180.0f;
  int len = 6 + a.gsKt / 30;
  spr.drawLine(a.sx, a.sy, a.sx + (int)(sinf(rad) * len),
               a.sy - (int)(cosf(rad) * len), col);
  if (selected) spr.drawCircle(a.sx, a.sy, 6, TFT_YELLOW);
  // Label: callsign, else last 4 of hex
  char label[9];
  if (a.callsign[0])
    snprintf(label, sizeof(label), "%s", a.callsign);
  else
    snprintf(label, sizeof(label), "%04lx", (unsigned long)(a.hex & 0xFFFF));
  spr.setTextColor(dim ? TFT_DARKGREY : TFT_SILVER, TFT_BLACK);
  spr.drawString(label, a.sx + 5, a.sy + 3, 1);
}

void drawScope(TFT_eSprite &spr, radar::AircraftStore &s, const UiState &ui) {
  spr.fillSprite(TFT_BLACK);
  float rangeOuter = RANGES_NM[ui.rangeIdx];
  float pxPerNm = (float)(SCOPE_CX - SCOPE_MARGIN) / rangeOuter;
  drawRings(spr, rangeOuter, pxPerNm);
  for (int i = s.count - 1; i >= 0; i--) { // draw far->near so near wins overlap
    radar::Aircraft &a = s.list[i];
    int sx = SCOPE_CX + (int)(a.pos.x * pxPerNm);
    int sy = SCOPE_CY - (int)(a.pos.y * pxPerNm);
    if (sx < 0 || sx >= SCOPE_W || sy < 0 || sy >= SCOPE_H) {
      a.sx = a.sy = -1000; // off-scope: not tappable
      continue;
    }
    a.sx = (int16_t)sx;
    a.sy = (int16_t)sy;
    drawBlip(spr, a, ui.selectedHex != 0 && a.hex == ui.selectedHex);
  }
}
```

- [ ] **Step 2: Wire into the UI task**

In `src/ui_task.cpp`: add `#include "ui/scope.h"`, replace the placeholder cross block (fillSprite + two drawLine calls) with `drawScope(s_scope, s_snap, s_ui);`.

- [ ] **Step 3: Build, flash OTA, verify (Milestone 3)**

Run: `direnv exec . pio run -e ota -t upload`
Expected on screen (Luke confirms): two green rings + centre cross + range legend "25nm"; cyan blips with heading vectors and labels in sane positions (compare against the tar1090 web map — same traffic picture, rotated correctly, north up); list and scope agree.

- [ ] **Step 4: Reviewer gate, then commit**

```bash
git add src
git commit -m "feat: radar scope with range rings, blips, vectors and labels"
```

---

### Task 7: Touch — select, detail panel, range cycling (Milestone 4)

**Files:**
- Create: `src/ui/touch_input.h`, `src/ui/touch_input.cpp`
- Modify: `src/ui/scope.h`, `src/ui/scope.cpp` (detail panel overlay), `src/ui_task.cpp` (poll touch), `src/main.cpp` (move touch objects out)

**Interfaces:**
- Consumes: `XPT2046_Touchscreen` instance (moves from main.cpp), `UiState`, aircraft `sx`/`sy` filled by Task 6.
- Produces:

```cpp
// ui/touch_input.h
void touchInputInit();      // owns SPIClass + XPT2046 begin (moves from main.cpp)
// Applies one tap (if any) to ui: select blip/list row, dismiss detail,
// or cycle range. Needs the current store snapshot for hit-testing.
void touchInputPoll(UiState &ui, const radar::AircraftStore &s);
```

- [ ] **Step 1: Implement touch input**

`src/ui/touch_input.h`:

```cpp
#pragma once
#include "aircraft.h"
#include "layout.h"

void touchInputInit();
void touchInputPoll(UiState &ui, const radar::AircraftStore &s);
```

`src/ui/touch_input.cpp`:

```cpp
#include "touch_input.h"
#include <Arduino.h>
#include <SPI.h>
#include <XPT2046_Touchscreen.h>

// XPT2046 on its own SPI bus (shares no pins with the TFT)
static constexpr int TOUCH_CLK = 25, TOUCH_CS = 33, TOUCH_MOSI = 32,
                     TOUCH_MISO = 39, TOUCH_IRQ = 36;
// Raw ADC window -> screen px, landscape rotation 1. Verified on this
// board via milestone-1 raw dumps; tweak here if taps land offset.
static constexpr int RAW_X_MIN = 200, RAW_X_MAX = 3700;
static constexpr int RAW_Y_MIN = 240, RAW_Y_MAX = 3800;
static constexpr int TAP_RADIUS_PX = 20;

static SPIClass s_touchSpi(VSPI);
static XPT2046_Touchscreen s_touch(TOUCH_CS, TOUCH_IRQ);
static bool s_wasDown = false;

void touchInputInit() {
  s_touchSpi.begin(TOUCH_CLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
  s_touch.begin(s_touchSpi);
  s_touch.setRotation(1);
}

static const radar::Aircraft *nearestBlip(const radar::AircraftStore &s,
                                          int x, int y) {
  const radar::Aircraft *best = nullptr;
  int bestD2 = TAP_RADIUS_PX * TAP_RADIUS_PX;
  for (int i = 0; i < s.count; i++) {
    const radar::Aircraft &a = s.list[i];
    int dx = a.sx - x, dy = a.sy - y;
    int d2 = dx * dx + dy * dy;
    if (d2 <= bestD2) { bestD2 = d2; best = &a; }
  }
  return best;
}

void touchInputPoll(UiState &ui, const radar::AircraftStore &s) {
  bool down = s_touch.touched();
  if (!down) { s_wasDown = false; return; }
  if (s_wasDown) return; // act on press edge only
  s_wasDown = true;

  TS_Point p = s_touch.getPoint();
  int x = map(constrain((int)p.x, RAW_X_MIN, RAW_X_MAX), RAW_X_MIN, RAW_X_MAX, 0, 319);
  int y = map(constrain((int)p.y, RAW_Y_MIN, RAW_Y_MAX), RAW_Y_MIN, RAW_Y_MAX, 0, 239);

  if (ui.detailOpen) { // any tap dismisses the detail panel
    ui.detailOpen = false;
    return;
  }
  if (x >= LIST_X) { // traffic list: tap row selects
    int row = y / LIST_ROW_H;
    if (y < STATUS_Y && row < s.count) {
      ui.selectedHex = s.list[row].hex;
      ui.detailOpen = true;
    }
    return;
  }
  const radar::Aircraft *hit = nearestBlip(s, x, y);
  if (hit) {
    ui.selectedHex = hit->hex;
    ui.detailOpen = true;
  } else {
    ui.rangeIdx = (ui.rangeIdx + 1) % N_RANGES; // background tap: cycle range
  }
}
```

- [ ] **Step 2: Add the detail panel to the scope**

Append to `src/ui/scope.cpp` (and declare `void drawDetailPanel(TFT_eSprite &spr, const radar::AircraftStore &s, const UiState &ui);` in `scope.h`):

```cpp
void drawDetailPanel(TFT_eSprite &spr, const radar::AircraftStore &s,
                     const UiState &ui) {
  if (!ui.detailOpen || ui.selectedHex == 0) return;
  const radar::Aircraft *a = s.findByHex(ui.selectedHex);
  if (!a) return;
  constexpr int W = 150, H = 92, X = 4, Y = SCOPE_H - H - 16;
  spr.fillRect(X, Y, W, H, TFT_BLACK);
  spr.drawRect(X, Y, W, H, TFT_YELLOW);
  spr.setTextColor(TFT_YELLOW, TFT_BLACK);
  char l1[24];
  snprintf(l1, sizeof(l1), "%s  %06lx",
           a->callsign[0] ? a->callsign : "(no cs)", (unsigned long)a->hex);
  spr.drawString(l1, X + 4, Y + 4, 2);
  spr.setTextColor(TFT_WHITE, TFT_BLACK);
  char alt[8], line[26];
  formatAltitude(alt, sizeof(alt), a->altFt, a->onGround);
  snprintf(line, sizeof(line), "%-4s  %s  %ukt", a->type[0] ? a->type : "-",
           alt, a->gsKt);
  spr.drawString(line, X + 4, Y + 26, 1);
  snprintf(line, sizeof(line), "trk %u", a->trackDeg);
  spr.drawString(line, X + 4, Y + 40, 1);
  snprintf(line, sizeof(line), "%.1fnm brg %.0f", (double)a->range,
           (double)radar::bearingDeg(a->pos));
  spr.drawString(line, X + 4, Y + 54, 1);
  snprintf(line, sizeof(line), "rssi %.1f  seen %.0fs", (double)a->rssi,
           (double)a->seenS);
  spr.drawString(line, X + 4, Y + 68, 1);
}
```

`scope.h` gains `#include "side_panel.h"` (for `formatAltitude`) and `#include "projection.h"` (for `bearingDeg`) via scope.cpp includes — add `#include "../side_panel.h"`-style includes as the build dictates (`side_panel.h` and `scope.h` are siblings in `src/ui/`, so `#include "side_panel.h"` works).

- [ ] **Step 3: Wire into UI task and main**

- `src/main.cpp`: delete the `SPIClass touchSpi` / `XPT2046_Touchscreen touch` globals and the three touch-init lines in `setup()` (touch now fully owned by touch_input.cpp).
- `src/ui_task.cpp`: add `#include "ui/touch_input.h"`; call `touchInputInit();` at the top of `uiTaskLoop` (before the loop; keeps all touch-SPI traffic on core 1); in the loop after `snapshotStore(s_snap);` add `touchInputPoll(s_ui, s_snap);`; after `drawScope(...)` add `drawDetailPanel(s_scope, s_snap, s_ui);`. If the selected hex vanishes from the snapshot (aged out), clear it: `if (s_ui.selectedHex && !s_snap.findByHex(s_ui.selectedHex)) { s_ui.selectedHex = 0; s_ui.detailOpen = false; }`.

- [ ] **Step 4: Build, flash OTA, verify (Milestone 4)**

Run: `direnv exec . pio run -e ota -t upload`
Expected (Luke confirms on hardware): tapping a blip highlights it yellow + opens the detail panel with matching data; tapping a list row does the same; tapping the panel dismisses it; tapping empty scope cycles 10→25→50→100→10nm with rings and blip positions rescaling; selection survives a range change. If taps land offset from blips, adjust `RAW_*` constants in touch_input.cpp and re-flash (one OTA iteration per tweak).

- [ ] **Step 5: Reviewer gate, then commit**

```bash
git add src
git commit -m "feat: touch selection, detail panel and range cycling"
```

---

### Task 8: Trails + aging polish

**Files:**
- Modify: `src/ui/scope.cpp` (trail rendering inside `drawScope`)

**Interfaces:**
- Consumes: `Aircraft.trail`/`trailLen`/`trailHead` (populated since Task 3); `project` from Task 1.
- Produces: nothing new — visual only. (Dimming already exists: blips, labels and list rows go dark grey past `SEEN_DIM_S` since Tasks 5–6.)

- [ ] **Step 1: Draw trails**

In `src/ui/scope.cpp`, inside the aircraft loop of `drawScope`, before `drawBlip`:

```cpp
    // Trails: oldest->newest as dimming dots behind the blip
    for (int t = 0; t < a.trailLen; t++) {
      int idx = (a.trailHead - a.trailLen + t + 2 * radar::TRAIL_LEN) %
                radar::TRAIL_LEN;
      radar::Vec2 tp = radar::project(HOME_LAT, HOME_LON, a.trail[idx].lat,
                                      a.trail[idx].lon);
      int tx = SCOPE_CX + (int)(tp.x * pxPerNm);
      int ty = SCOPE_CY - (int)(tp.y * pxPerNm);
      if (tx < 0 || tx >= SCOPE_W || ty < 0 || ty >= SCOPE_H) continue;
      // 3 brightness steps oldest->newest
      uint16_t col = t < a.trailLen / 3       ? 0x18E3   // very dark grey
                     : t < (2 * a.trailLen) / 3 ? TFT_DARKGREY
                                                : 0x8410; // mid grey
      spr.drawPixel(tx, ty, col);
      if (t >= (2 * a.trailLen) / 3) spr.drawPixel(tx + 1, ty, col);
    }
```

Add `#include "projection.h"` and `#include "config.h"` to scope.cpp.

- [ ] **Step 2: Build, flash OTA, verify**

Expected (Luke confirms): moving aircraft grow a fading dotted tail (up to 10 dots ≈ 20s of track); stationary/ground targets don't accumulate dots; trails survive range changes (they re-project).

- [ ] **Step 3: Reviewer gate, then commit**

```bash
git add src
git commit -m "feat: fading position trails on scope"
```

---

### Task 9: LDR backlight + RGB status LED (Milestone 6 complete)

**Files:**
- Create: `src/status_led.h`, `src/status_led.cpp`
- Modify: `src/ui_task.cpp` (backlight dimming), `src/net_task.cpp` (LED status calls)

**Interfaces:**
- Consumes: WiFi status, fetch age (net task locals).
- Produces:

```cpp
// status_led.h
enum class LedStatus { NoWifi, NoData, Ok };
void statusLedInit();
void statusLedSet(LedStatus s);
```

- [ ] **Step 1: Implement the status LED**

`src/status_led.h`:

```cpp
#pragma once
enum class LedStatus { NoWifi, NoData, Ok };
void statusLedInit();
void statusLedSet(LedStatus s);
```

`src/status_led.cpp`:

```cpp
#include "status_led.h"
#include <Arduino.h>

// CYD RGB LED, active low
static constexpr int LED_R = 4, LED_G = 16, LED_B = 17;

void statusLedInit() {
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  statusLedSet(LedStatus::NoWifi);
}

void statusLedSet(LedStatus s) {
  bool r = s == LedStatus::NoWifi || s == LedStatus::NoData; // amber = r+g
  bool g = s == LedStatus::NoData;
  digitalWrite(LED_R, r ? LOW : HIGH);
  digitalWrite(LED_G, g ? LOW : HIGH);
  digitalWrite(LED_B, HIGH);
}
```

- [ ] **Step 2: Drive it from the net task**

In `src/net_task.cpp` (`#include "status_led.h"`), at the end of each `netTaskLoop` iteration (after the poll block, before `vTaskDelay`):

```cpp
    if (WiFi.status() != WL_CONNECTED)
      statusLedSet(LedStatus::NoWifi);
    else if (!s_prev.fetchOk || millis() - s_prev.lastFetchMs > 10000)
      statusLedSet(LedStatus::NoData);
    else
      statusLedSet(LedStatus::Ok);
```

In `src/main.cpp` `setup()`, call `statusLedInit();` before `setupWifi()` (`#include "status_led.h"`).

- [ ] **Step 3: LDR-driven backlight**

In `src/ui_task.cpp`:

```cpp
static constexpr int LDR_PIN = 34;
static constexpr int BL_PIN = 21;
static constexpr int BL_CHANNEL = 0;
static constexpr int BL_MIN_DUTY = 40; // never fully dark

static void backlightInit() {
  ledcSetup(BL_CHANNEL, 5000, 8);
  ledcAttachPin(BL_PIN, BL_CHANNEL); // takes over from TFT_eSPI's digital HIGH
  ledcWrite(BL_CHANNEL, 255);
  analogSetPinAttenuation(LDR_PIN, ADC_11db);
}

static void backlightUpdate() {
  // CYD LDR: bright ambient -> low reading. Smooth + invert into duty.
  static float smoothed = 2000.0f;
  smoothed += 0.1f * ((float)analogRead(LDR_PIN) - smoothed);
  int duty = map((int)smoothed, 0, 4095, 255, BL_MIN_DUTY);
  ledcWrite(BL_CHANNEL, constrain(duty, BL_MIN_DUTY, 255));
}
```

Call `backlightInit()` after `createScopeSprite()` in `uiTaskLoop`, and `backlightUpdate()` once per loop iteration. If the panel brightens in the dark instead of dimming, flip the map: `map((int)smoothed, 0, 4095, BL_MIN_DUTY, 255)` — LDR orientation varies by batch; calibrate on hardware and adjust the comment to match reality.

- [ ] **Step 4: Build, flash OTA, verify**

Expected (Luke confirms): LED off in normal operation; cover the LDR → backlight dims smoothly, torch on it → brightens; unplug the receiver (or break `RECEIVER_URL` temporarily) → LED amber within ~12s; wrong WiFi → red. Serial shows heap stable over several minutes.

- [ ] **Step 5: Reviewer gate, then commit**

```bash
git add src
git commit -m "feat: RGB status LED and LDR-driven backlight dimming"
```

- [ ] **Step 6: Final full-suite verification**

Run: `direnv exec . pio test -e native` → 14/14 pass.
Run: `direnv exec . pio run -e ota -t upload` → SUCCESS, board returns with full UI.
Leave running 10 minutes; capture serial; heap floor stable (no leak trend).

---

## Self-Review (completed)

- **Spec coverage:** data source/poll/filter → T3/T4; architecture (cores, mutex, cap 32, aging) → T2/T4/T5; UI layout/scope/list/status → T5/T6; touch → T7; trails/dimming → T8; LDR/LED → T9; OTA → already done pre-plan; sweep line → explicitly out (stretch, non-MVP).
- **Placeholder scan:** all code steps carry full code; device-verify steps state observable acceptance.
- **Type consistency:** `Aircraft.range` (not `rangeNm`) everywhere; `formatAltitude(out, cap, altFt, onGround)` consistent T5/T7; `UiState{rangeIdx, selectedHex, detailOpen}` consistent T5–T7; `drawScope(spr, store&, ui)` mutable store for sx/sy consistent T6–T7.
- **Known open risk:** touch calibration constants are estimates from milestone-1 raw dumps; T7 step 4 explicitly budgets an adjust-and-reflash iteration.
