#pragma once
#include <stdint.h>
#include "projection.h"

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
  char squawk[5];     // "7700"; empty when the feed omits it. String, not an
                      // int — leading zeros are significant ("0100" != 100).
  float lat, lon;
  int32_t altFt;      // 0 when feed reports "ground"
  bool onGround;
  uint16_t gsKt;
  uint16_t trackDeg;
  int16_t vertRateFpm; // + climb, - descent; 0 when the feed omits both rates
  bool isMlat;         // position multilaterated, not transmitted by the
                       // aircraft: lower confidence, and by definition an
                       // airframe that isn't sending ADS-B at all
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
