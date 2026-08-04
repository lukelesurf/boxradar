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
