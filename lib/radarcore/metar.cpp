#include "metar.h"
#include <string.h>

namespace radar {

static void copyField(char *dst, size_t cap, const char *src) {
  if (!src) { dst[0] = '\0'; return; }
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

bool loadMetar(JsonVariantConst root, const char *station, Metar &out) {
  if (!station || !station[0]) return false;
  for (JsonObjectConst s : root["stations"].as<JsonArrayConst>()) {
    const char *id = s["id"] | "";
    if (strcmp(id, station) != 0) continue;

    Metar m;
    memset(&m, 0, sizeof(m));
    copyField(m.station, sizeof(m.station), id);
    copyField(m.cover, sizeof(m.cover), s["cov"] | (const char *)nullptr);
    copyField(m.runway, sizeof(m.runway), s["rwy"] | (const char *)nullptr);
    // -1 rather than 0 for variable: 0 would render as due north.
    m.windDir = (int16_t)(s["wdir"] | -1);
    m.windKt = (uint16_t)(s["wspd"] | 0);
    m.gustKt = (uint16_t)(s["gust"] | 0);
    m.visM = (uint16_t)(s["vis"] | 9999);
    m.ceilFt = (uint16_t)(s["ceil"] | 0);
    m.runwayConfident = (s["conf"] | 0) != 0;
    m.valid = true;
    out = m;
    return true;
  }
  return false;
}

} // namespace radar
