#pragma once
#include <ArduinoJson.h>
#include <stdint.h>

namespace radar {

// One airfield's conditions, as published by tools/metar-feed on the
// receiver Pi. Every field is fixed-type and always present — the Pi has
// already absorbed the upstream API's loose typing (visibility as "6+",
// wind direction as "VRB", null gusts), precisely so nothing here has to
// guess what a missing or surprising value meant.
struct Metar {
  char station[5];  // "EGSS"
  char cover[5];    // "NCD" / "FEW" / "SCT" / "BKN" / "OVC"
  char runway[4];   // "04", or empty when wind direction is unusable
  int16_t windDir;  // degrees true; -1 = variable or absent
  uint16_t windKt;
  uint16_t gustKt;  // 0 = no gust reported
  uint16_t visM;    // metres; 9999 = 10km or more, per METAR convention
  uint16_t ceilFt;  // lowest BKN/OVC base; 0 = no ceiling (NOT "no cloud")
  bool runwayConfident; // false when wind is too light to be deciding it
  bool valid;
  uint32_t lastFetchMs;
};

// Pulls one station out of the feed's "stations" array. Returns false and
// leaves `out` untouched if the station isn't present, so a temporarily
// incomplete publish can't blank a good previous reading.
bool loadMetar(JsonVariantConst root, const char *station, Metar &out);

} // namespace radar
