#include "shared_state.h"
#include "operator_name.h"
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

struct OperatorSlot {
  char code[4];
  char name[radar::OPERATOR_NAME_LEN];
  char radio[radar::OPERATOR_RADIO_LEN];
  bool answered;
  uint8_t attempts;
  uint32_t lastAttemptMs;
};

OperatorSlot s_operator;

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
  s_operator = OperatorSlot{};
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

// The operator half. Deliberately a copy of the type-name state machine rather
// than a generalisation of it: the two differ in what they carry (one string
// against two) and the shared version would be a template or a pair of
// callbacks over about fifteen lines of logic. A third lookup is the point to
// reconsider that — this file is Arduino/FreeRTOS code the native tests do not
// link, so a refactor here buys less than it costs.

void requestOperator(const char *code) {
  if (!code || !code[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (strcmp(s_operator.code, code) != 0) {
    s_operator = OperatorSlot{};
    copyInto(s_operator.code, sizeof(s_operator.code), code);
  }
  xSemaphoreGive(s_mutex);
}

bool pendingOperator(char *out, size_t cap) {
  if (!out || cap == 0) return false;
  out[0] = '\0';
  bool due = false;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (s_operator.code[0] && !s_operator.answered &&
      s_operator.attempts < TYPE_MAX_ATTEMPTS &&
      (s_operator.lastAttemptMs == 0 ||
       millis() - s_operator.lastAttemptMs >= TYPE_RETRY_MS)) {
    copyInto(out, cap, s_operator.code);
    due = true;
  }
  xSemaphoreGive(s_mutex);
  return due;
}

void publishOperator(const char *code, const char *name, const char *radio) {
  if (!code || !code[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  // Matched on the code for the same reason the type name is matched on the
  // designator: the fetch started before the reply landed, and by now the
  // selection may have moved on.
  if (strcmp(s_operator.code, code) == 0) {
    copyInto(s_operator.name, sizeof(s_operator.name), name);
    copyInto(s_operator.radio, sizeof(s_operator.radio), radio);
    s_operator.answered = true;
  }
  xSemaphoreGive(s_mutex);
}

void failOperator(const char *code) {
  if (!code || !code[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (strcmp(s_operator.code, code) == 0) {
    s_operator.attempts++;
    s_operator.lastAttemptMs = millis();
    if (s_operator.lastAttemptMs == 0) s_operator.lastAttemptMs = 1;
  }
  xSemaphoreGive(s_mutex);
}

void operatorFor(const char *code, char *name, size_t nameCap, char *radio,
                 size_t radioCap) {
  if (!name || nameCap == 0 || !radio || radioCap == 0) return;
  name[0] = '\0';
  radio[0] = '\0';
  if (!code || !code[0]) return;
  xSemaphoreTake(s_mutex, portMAX_DELAY);
  if (s_operator.answered && strcmp(s_operator.code, code) == 0) {
    copyInto(name, nameCap, s_operator.name);
    copyInto(radio, radioCap, s_operator.radio);
  }
  xSemaphoreGive(s_mutex);
}
