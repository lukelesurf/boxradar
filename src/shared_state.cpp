#include "shared_state.h"
#include <Arduino.h>
#include <string.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

volatile bool g_otaActive = false;
volatile uint8_t g_otaProgress = 0;
volatile float g_trailSpacingNm = radar::TRAIL_SPACING_DEFAULT_NM;

static SemaphoreHandle_t s_mutex;
static radar::AircraftStore s_store;
static radar::Metar s_metar;

namespace {

// A failed lookup waits this long before being tried again, and is given up on
// after this many attempts. Both exist because the net task's loop runs every
// 50ms: without spacing, an unreachable Pi would be asked twenty times a
// second, and without a ceiling it would be asked forever.
//
// Giving up is not permanent in practice. The slot is keyed by designator, so
// selecting a different aircraft and coming back re-requests it — which is
// also the only gesture a person makes when a name did not appear.
constexpr uint32_t TYPE_RETRY_MS = 3000;
constexpr uint8_t TYPE_MAX_ATTEMPTS = 3;

struct TypeSlot {
  char designator[8];
  char name[radar::TYPE_NAME_LEN];
  bool answered;
  uint8_t attempts;
  uint32_t lastAttemptMs;
};

TypeSlot s_type;

void copyInto(char *dst, size_t cap, const char *src) {
  if (!src) { dst[0] = '\0'; return; }
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

} // namespace

void sharedStateInit() {
  s_mutex = xSemaphoreCreateMutex();
  s_store.clear();
  s_metar = radar::Metar{}; // valid=false until the first successful fetch
  s_type = TypeSlot{};
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

void publishMetar(const radar::Metar &m) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  s_metar = m;
  xSemaphoreGive(s_mutex);
}

void snapshotMetar(radar::Metar &out) {
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  out = s_metar;
  xSemaphoreGive(s_mutex);
}

void requestTypeName(const char *designator) {
  if (!designator || !designator[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  // Unchanged is a no-op, which is what makes this safe to call every frame:
  // resetting here would discard a resolved name 10 times a second and keep
  // the net task fetching the same designator forever.
  if (strcmp(s_type.designator, designator) != 0) {
    s_type = TypeSlot{};
    copyInto(s_type.designator, sizeof(s_type.designator), designator);
  }
  xSemaphoreGive(s_mutex);
}

bool pendingTypeName(char *out, size_t cap) {
  if (!out || cap == 0) return false;
  out[0] = '\0';
  bool due = false;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (s_type.designator[0] && !s_type.answered &&
      s_type.attempts < TYPE_MAX_ATTEMPTS &&
      (s_type.lastAttemptMs == 0 ||
       millis() - s_type.lastAttemptMs >= TYPE_RETRY_MS)) {
    copyInto(out, cap, s_type.designator);
    due = true;
  }
  xSemaphoreGive(s_mutex);
  return due;
}

void publishTypeName(const char *designator, const char *name) {
  if (!designator || !designator[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  // Matched on the designator, not stored blindly: the fetch was started
  // before the reply arrived, and by now the selection may have moved on. An
  // answer for something nobody is looking at is dropped rather than shown.
  if (strcmp(s_type.designator, designator) == 0) {
    copyInto(s_type.name, sizeof(s_type.name), name);
    s_type.answered = true;
  }
  xSemaphoreGive(s_mutex);
}

void failTypeName(const char *designator) {
  if (!designator || !designator[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (strcmp(s_type.designator, designator) == 0) {
    s_type.attempts++;
    s_type.lastAttemptMs = millis();
    // millis() is 0 for the first 1ms after boot, and lastAttemptMs == 0 is
    // how pendingTypeName() spells "never tried". One tick avoids a first
    // failure reading as no attempt at all.
    if (s_type.lastAttemptMs == 0) s_type.lastAttemptMs = 1;
  }
  xSemaphoreGive(s_mutex);
}

void typeNameFor(const char *designator, char *out, size_t cap) {
  if (!out || cap == 0) return;
  out[0] = '\0';
  if (!designator || !designator[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (s_type.answered && strcmp(s_type.designator, designator) == 0)
    copyInto(out, cap, s_type.name);
  xSemaphoreGive(s_mutex);
}
