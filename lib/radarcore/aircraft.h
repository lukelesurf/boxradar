#pragma once
#include <stdint.h>
#include "projection.h"

namespace radar {
constexpr int MAX_AIRCRAFT = 32;
constexpr int TRAIL_LEN = 10;

// How long a contact survives on the scope after the feed stops mentioning it.
//
// Settable at runtime, unlike the two above, because these are a judgement
// about the receiver rather than an allocation: at 30/60 a contact that drops
// behind a hill dims for half a minute and then vanishes, which is right for a
// rooftop antenna with a clean horizon and wrong for one indoors, where the
// same aircraft flickers in and out and the scope loses it every few polls.
// MAX_AIRCRAFT and TRAIL_LEN size static .bss arrays and stay compiled.
struct SeenAgeing {
  // Past this, a blip is drawn dimmed and its datablock greys — still there,
  // but no longer to be trusted for position.
  float dimS;

  // Past this it is not drawn and not tappable. Nothing enforces
  // dropS > dimS; setting them the other way round just means contacts leave
  // without ever dimming first, which is odd rather than broken.
  float dropS;
};

// The live ageing. Returns the compiled defaults until seenAgeingSet() is
// called, so the native tests and a board with empty NVS behave alike.
const SeenAgeing &seenAgeing();

// The compiled defaults, for the configuration UI and the tests.
const SeenAgeing &seenAgeingDefaults();

// Replace the live ageing. A non-positive value is IGNORED and the previous
// one kept: a zero would drop every contact the moment it arrived, which
// reads as a dead feed rather than a bad setting.
void seenAgeingSet(const SeenAgeing &a);

// Fallback spacing until the UI publishes one, ~right for the default 10nm
// range. Only used for the first polls after boot.
constexpr float TRAIL_SPACING_DEFAULT_NM = 0.45f;

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
  // Stored in the same NM east/north frame as `pos`, not as lat/lon. Spacing
  // can then be compared directly in NM without projecting, and rendering no
  // longer reprojects every trail point on every frame.
  Vec2 trail[TRAIL_LEN];
  uint8_t trailLen;
  uint8_t trailHead;  // next write slot
};

struct AircraftStore {
  Aircraft list[MAX_AIRCRAFT];
  int count = 0;
  // Contacts the receiver had before the cap, so the display can say "32/58".
  // Can exceed count; equals it whenever the cap is not binding. The README
  // documents the cap as a silent cliff — this is what makes it visible.
  uint16_t feedTotal = 0;
  uint32_t lastFetchMs = 0; // millis() of last successful poll
  bool fetchOk = false;
  void clear();
  void insertByRange(const Aircraft &a); // sorted asc by range, cap 32
  const Aircraft *findByHex(uint32_t hex) const;
  Aircraft *findByHex(uint32_t hex);
  // Carry trails over from the previous poll and append the current position,
  // but only for aircraft that have moved at least minSpacingNm since their
  // last trail point. Distance-gated rather than time-gated so the dots are
  // evenly spaced regardless of groundspeed.
  void inheritTrails(const AircraftStore &prev, float minSpacingNm);
};
}
