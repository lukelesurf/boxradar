# Board Blob Loading Implementation Plan (phase 3b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status: tasks 1-3 complete, verified on hardware 2026-08-08. Task 4 (deleting the compiled tables) not done and probably unnecessary.** The board fetches, validates and caches the blob, and loads it from LittleFS on boot — free heap after the 18KB allocation is 196,432 bytes. It does NOT yet draw from it; scope.cpp still reads the compiled tables.

> Task 3 is done: Luke compared the rendered panel against the compiled build and confirmed it. MAP_FROM_BLOB is now the default in config.h. The generated headers stay in the repo as regenerable output and remain one build flag away, so task 4's deletion buys little and costs the fallback.

> **Portal form verified end-to-end 2026-08-08**, after this plan was written: compiled SSID pointed at a nonexistent network, real trigger fired, form submitted from a phone, `portal: saved 8 setting(s)`, and the board rejoined the LAN reporting `cfg: NVS overlay` rather than compiled defaults.

**Goal:** The board draws its map from a blob fetched over HTTP and cached to LittleFS, instead of from tables compiled into flash.

**Architecture:** Three layers, deliberately separated so only the last one can break the display. `radarcore/geomap` is a portable facade over `GeoBlob` that adds the coastline bounding boxes the blob does not store — pure, natively tested. `src/geo_store` owns the device side: LittleFS cache, HTTP fetch with `If-None-Match`, and one heap buffer the `GeoBlob` points into. Only then does `scope.cpp` switch its six loops over, behind a build flag so the compiled tables remain a fallback until the blob path is proven on hardware.

**Tech Stack:** LittleFS and HTTPClient from the ESP32 Arduino core; portable C++ for the facade.

## Global Constraints

- **3a is NOT in scope.** WiFi credentials, the portal and NVS config stay untouched. The blob URL is a compile-time `#define GEO_URL` in `config.h`, exactly like `METAR_URL`. Runtime config is a separate phase and must be done with Luke present, because it touches the OTA path.
- **Nothing may make the board unflashable.** Serial is usually unavailable on this unit, so OTA is the only practical recovery. This phase must not touch WiFi bring-up, `setupOta()`, or the net task's OTA polling.
- **The compiled tables stay until the blob path is proven on hardware.** `MAP_FROM_BLOB` selects the source; the headers remain the default until a device test says otherwise. Deleting them is the last task and is gated on evidence, not on the code compiling.
- **One heap allocation for the map.** ~18KB for this site. The `GeoBlob` points into it, so it must live as long as the map is drawn — a static owner, never a stack buffer or a `String`.
- **`lib/radarcore` stays portable and must compile under `gnu++11` (device) and `gnu++17` (native).**
- **Blobs are not byte-reproducible across machines.** Measured: generating on the Pi (shapely 1.8) and on the home server (2.1.2) gives the same 18,192 bytes and identical record counts but different bytes, because GEOS rounds arcs differently. So the ETag identifies *a* build, not *the* content — a regenerate on another machine invalidates the cache even when nothing changed. Harmless; do not try to make it reproducible.
- Tests: `pio test -e native`, `python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site`, `pio run -e usb`.
- The Pi already serves it: `http://192.0.2.10/site.bin`, 18,192 bytes, with a lighttpd ETag.

---

### Task 1: The portable map facade

`GeoBlob` gives raw sections. `scope.cpp` needs what the old headers gave it,
including the coastline bounding boxes the blob deliberately does not store.
This is where that gap is closed, and it is pure enough to test natively.

**Files:**
- Create: `lib/radarcore/geomap.h`, `lib/radarcore/geomap.cpp`
- Test: `test/test_geomap/test_main.cpp`

**Interfaces:**
- `struct GeoBox { float minLat, maxLat, minLon, maxLon; };`
- `class GeoMap`:
  - `GeoStatus open(const uint8_t *data, size_t len, float homeLat, float homeLon)` — delegates to `GeoBlob`, then precomputes coastline boxes
  - `uint16_t airspaceCount() const`, `bool airspace(uint16_t, GeoPolyline &) const`
  - `uint16_t coastCount() const`, `bool coast(uint16_t, GeoPolyline &, GeoBox &) const`
  - `uint16_t airfieldCount() const`, `const GeoNamedPoint *airfields() const`
  - `uint16_t runwayCount() const`, `const GeoRunway *runways() const`
  - `uint16_t waypointCount() const`, `const GeoNamedPoint *waypoints() const`
  - `uint16_t townCount() const`, `const GeoNamedPoint *towns() const`
  - `uint16_t coastDropped() const` — segments beyond `MAX_COAST_SEGMENTS`
- `static const uint16_t MAX_COAST_SEGMENTS = 192;`

`MAX_COAST_SEGMENTS` is a fixed cap because the box array is statically
allocated: 192 × 16 bytes = 3KB, against 124 segments today. `coastDropped()`
exists so truncation is **reportable**. The README already documents
`MAX_AIRCRAFT`'s silent cliff, where "the count pins at 32 and distant contacts
vanish with no other indication" — a half-drawn coastline looks exactly like
correct data, so this one must be able to say so.

- [ ] **Step 1: Write the failing test**

Create `test/test_geomap/test_main.cpp`. Include `"../test_geoblob/fixture_blob.h"`
so there is one fixture, not two that can drift:

```cpp
#include <unity.h>
#include <string.h>
#include "geomap.h"
#include "../test_geoblob/fixture_blob.h"

using namespace radar;

static const float HOME_LAT = 51.8850f;
static const float HOME_LON = 0.2350f;

static void test_opens() {
  GeoMap m;
  TEST_ASSERT_EQUAL(GEO_OK, m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON));
}

static void test_rejects_wrong_home() {
  GeoMap m;
  TEST_ASSERT_EQUAL(GEO_WRONG_HOME,
                    m.open(FIXTURE, FIXTURE_LEN, 55.0f, -3.0f));
}

static void test_counts_match_the_fixture() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL_UINT16(2, m.airspaceCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.coastCount());
  TEST_ASSERT_EQUAL_UINT16(2, m.airfieldCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.runwayCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.waypointCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.townCount());
  TEST_ASSERT_EQUAL_UINT16(0, m.coastDropped());
}

static void test_airspace_vertices() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  TEST_ASSERT_TRUE(m.airspace(0, line));
  TEST_ASSERT_EQUAL_UINT16(4, line.count);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.86523f, line.pts[0].lat);
}

static void test_coast_box_is_computed_from_the_points() {
  // The blob does not store bboxes: a stored one could disagree with its own
  // points, and the symptom is a coastline that silently fails to draw.
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  GeoBox box;
  TEST_ASSERT_TRUE(m.coast(0, line, box));
  TEST_ASSERT_EQUAL_UINT16(3, line.count);
  float minLat = line.pts[0].lat, maxLat = line.pts[0].lat;
  float minLon = line.pts[0].lon, maxLon = line.pts[0].lon;
  for (uint16_t i = 1; i < line.count; i++) {
    if (line.pts[i].lat < minLat) minLat = line.pts[i].lat;
    if (line.pts[i].lat > maxLat) maxLat = line.pts[i].lat;
    if (line.pts[i].lon < minLon) minLon = line.pts[i].lon;
    if (line.pts[i].lon > maxLon) maxLon = line.pts[i].lon;
  }
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, minLat, box.minLat);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, maxLat, box.maxLat);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, minLon, box.minLon);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, maxLon, box.maxLon);
}

static void test_named_points() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL_STRING("EGSS", m.airfields()[0].name);
  TEST_ASSERT_EQUAL_STRING("LOREL", m.waypoints()[0].name);
  TEST_ASSERT_EQUAL_STRING("STVG", m.towns()[0].name);
}

static void test_runways() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.8795f, m.runways()[0].lat0);
}

static void test_unopened_map_is_empty_not_crashy() {
  GeoMap m;
  GeoPolyline line;
  GeoBox box;
  TEST_ASSERT_EQUAL_UINT16(0, m.airspaceCount());
  TEST_ASSERT_EQUAL_UINT16(0, m.coastCount());
  TEST_ASSERT_FALSE(m.airspace(0, line));
  TEST_ASSERT_FALSE(m.coast(0, line, box));
  TEST_ASSERT_NULL(m.airfields());
}

static void test_reopening_resets_state() {
  // A refetch must not leave stale boxes behind.
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL(GEO_BAD_MAGIC, m.open((const uint8_t *)"XXXXXXXXXXXXXXXX",
                                          16, HOME_LAT, HOME_LON));
  TEST_ASSERT_EQUAL_UINT16(0, m.coastCount());
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_opens);
  RUN_TEST(test_rejects_wrong_home);
  RUN_TEST(test_counts_match_the_fixture);
  RUN_TEST(test_airspace_vertices);
  RUN_TEST(test_coast_box_is_computed_from_the_points);
  RUN_TEST(test_named_points);
  RUN_TEST(test_runways);
  RUN_TEST(test_unopened_map_is_empty_not_crashy);
  RUN_TEST(test_reopening_resets_state);
  return UNITY_END();
}
```

- [ ] **Step 2: Run to verify failure**

Run: `pio test -e native -f test_geomap`
Expected: `geomap.h: No such file or directory`

- [ ] **Step 3: Write `geomap.h` and `geomap.cpp`**

The facade wraps a `GeoBlob` and adds a static `GeoBox` array filled at open.
Reset both on every `open()` so a failed refetch cannot leave stale boxes.
Compute each box in one pass over the segment's vertices.

- [ ] **Step 4: Run to verify passing, and check the device build**

```bash
pio test -e native -f test_geomap
pio run -e usb
```
Expected: 9 tests pass; device build SUCCESS. The device check is not optional
— `lib/radarcore` compiles at `gnu++11` there and `gnu++17` natively.

- [ ] **Step 5: Commit**

---

### Task 2: The device-side store

**Files:**
- Create: `src/geo_store.h`, `src/geo_store.cpp`
- Modify: `include/config.example.h`, `include/config.h`, `src/net_task.cpp`

**Interfaces:**
- `bool geoStoreBegin()` — mounts LittleFS, loads any cached blob, opens it
- `bool geoStoreRefresh()` — conditional GET; on 200 validates, saves, reopens; on 304 does nothing
- `const radar::GeoMap &geoMap()`
- `const char *geoStoreStatus()` — one line for the serial log and, later, the status strip

Order matters and is the whole safety argument: **validate before saving.** A
blob that fails `open()` must never overwrite a good cache, or one bad deploy
costs the map until the next good fetch.

- [ ] **Step 1: Add the URL to config**

`#define GEO_URL "http://192.0.2.10/site.bin"` in `config.h`, and the
`receiver.lan` form in `config.example.h`, with a note that commenting it out
keeps the compiled tables.

- [ ] **Step 2: Write the store**

LittleFS mounted with `LittleFS.begin(true)` so a blank partition formats
itself rather than failing forever. Cache path `/site.bin`. The buffer is a
single `static uint8_t *` from `malloc`, sized from `Content-Length`, with a
sanity ceiling (`MAX_BLOB_BYTES`, 64KB) so a wrong URL serving something huge
cannot exhaust the heap.

Log free heap before and after allocation. That number is the one real unknown
in this phase.

- [ ] **Step 3: Call it from the net task, and report to serial**

`geoStoreBegin()` after WiFi is up; `geoStoreRefresh()` once, then on a slow
poll. It must run on core 0 with the other network work and must never block
the OTA path — same discipline as `pollMetar()`, which is deliberately a
separate cadence and a separate `if` so a slow fetch cannot delay anything.

- [ ] **Step 4: Verify on device over serial**

Flash over OTA, then watch `/dev/ttyUSB0`. Expected: mount, fetch, byte count,
`GEO_OK`, the six record counts matching the Pi's blob (13/124/10/2/4/7), and
free heap before and after. Then reboot and confirm it loads from cache with no
fetch, and that a second refresh gets a 304.

**This is the gate for the task.** The map is not drawn from the blob yet, so a
failure here costs nothing on screen.

- [ ] **Step 5: Commit**

---

### Task 3: Switch the renderer

**Files:** `src/ui/scope.cpp`, `platformio.ini`

`scope.cpp` has exactly six loops touching geography — lines 51 (`RUNWAYS`), 93
(`coastline::SEGMENTS`), 123 (`airspace::OUTLINES`), 152 (`AIRFIELDS`), 163
(`WAYPOINTS`), 172 (`TOWNS`) — plus the three includes at 10, 14 and 18.

- [ ] **Step 1: Put both sources behind `MAP_FROM_BLOB`**

Range-`for` over a flash array becomes an index loop over the facade. Keep the
compiled path as the default so a mistake cannot blank the map.

- [ ] **Step 2: Build both ways**

`pio run -e usb` and `PLATFORMIO_BUILD_FLAGS="-DMAP_FROM_BLOB" pio run -e usb`.
Both must succeed, and record the flash figures — the blob path should be
smaller once the tables are no longer compiled in.

- [ ] **Step 3: Verify the blob path on hardware**

Flash with `MAP_FROM_BLOB`, then compare the panel against the compiled build:
coastline, airspace outlines, centrelines, airfield squares, town squares, fix
triangles. **Read the panel — the tests cannot see this.**

- [ ] **Step 4: Commit, with the default still the compiled tables**

---

### Task 4: Retire the compiled tables — GATED

**Do not do this without Luke.** Deleting `airspace_data.h`, `coastline_data.h`
and `location.h` removes the fallback that makes every step above recoverable,
and it makes the board hard-dependent on the Pi for its map. The spec calls for
a LittleFS last-known-good cache to make that acceptable, and that cache should
have been observed surviving a Pi outage first.

---

## Notes for whoever executes this

**Validate before saving.** A fetched blob that fails `open()` must not
overwrite the cache. This is the single most important ordering in the phase.

**Do not touch WiFi bring-up or OTA.** `setupOta()` is deliberately called
lazily on first WiFi connection so a board that misses the boot-time wait still
becomes flashable. Nothing here may change that.

**Free heap is the one real unknown.** The sprite is 76.8KB and the blob is
18KB. Log it either side of the allocation and stop if the margin looks thin.
