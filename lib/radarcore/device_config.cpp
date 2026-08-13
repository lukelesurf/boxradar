#include "device_config.h"
#include <string.h>
#include "site_config_data.h"

namespace radar {

// Bounds are refused, not clamped. Several of these exist because the value
// below them is silently useless rather than obviously broken:
//
//   poll   500ms   the board would spend its time on HTTP, against a Pi also
//                  running readsb and tar1090
//   mpoll  10s     the METAR proxy caches for 300s, so anything faster just
//                  re-serves the same observation
//   gpoll  60s     the map changes when you publish, not on its own
//
// nstart == nend is ALLOWED: night_mode.cpp reads it as "disabled", so it is
// the off switch rather than a 24-hour blank.
//
// String maxima are CFG_HOST_LEN and CFG_TZ_LEN less the terminator, so a
// value that passes here is one cfgSetStr() will also accept. Deriving them
// from the same constants rather than writing 32 and 47 is what keeps that
// true if a field is ever resized.
const DeviceField DEVICE_FIELDS[] = {
    {"nstart", DEV_U32, 0, 23},
    {"nend", DEV_U32, 0, 23},
    {"nwake", DEV_U32, 5, 3600},
    {"nfade", DEV_U32, 0, 10000},
    {"nduty", DEV_U32, 0, 255},
    {"poll", DEV_U32, 500, 60000},
    {"mpoll", DEV_U32, 10000, 3600000},
    {"gpoll", DEV_U32, 60000, 86400000},
    {"ntp", DEV_STR, 0, CFG_HOST_LEN - 1},
    {"tz", DEV_STR, 0, CFG_TZ_LEN - 1},
};

const size_t DEVICE_FIELD_COUNT =
    sizeof(DEVICE_FIELDS) / sizeof(DEVICE_FIELDS[0]);

const DeviceField *deviceFieldByKey(const char *key) {
  if (!key) return nullptr;
  for (size_t i = 0; i < DEVICE_FIELD_COUNT; i++)
    if (strcmp(DEVICE_FIELDS[i].key, key) == 0) return &DEVICE_FIELDS[i];
  return nullptr;
}

const char *deviceFieldProblem(const DeviceField &field, const char *value,
                               uint32_t *out) {
  if (!value) return "missing";

  if (field.kind == DEV_STR) {
    size_t n = strlen(value);
    if (n == 0) return "empty";
    if (n > field.high) return "too long for this field";
    return nullptr;
  }

  // Hand-parsed rather than strtoul, to reject what strtoul accepts. A
  // leading '-' would wrap to a huge unsigned; trailing text is silently
  // ignored, so "2000ms" would store 2000 and the next reader would wonder
  // where the units went.
  if (value[0] == '\0') return "empty";
  uint64_t n = 0;
  for (const char *p = value; *p; p++) {
    if (*p < '0' || *p > '9') return "expected a whole number";
    n = n * 10 + (uint64_t)(*p - '0');
    if (n > 0xFFFFFFFFull) return "out of range";
  }
  if (n < field.low || n > field.high) return "out of range";
  if (out) *out = (uint32_t)n;
  return nullptr;
}

} // namespace radar
