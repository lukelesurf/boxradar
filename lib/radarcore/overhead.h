#pragma once
#include "aircraft.h"

// Predicts which aircraft will next pass close to overhead.
//
// Compile-time optional, though not worth removing for space: commenting
// out OVERHEAD_PREDICTION in config.h drops the three #ifdef blocks in
// src/ui/scope.cpp and --gc-sections then collects this, which measures at
// 1424 bytes of flash. Deleting overhead.{h,cpp},
// src/ui/overhead_readout.{h,cpp} and test/test_overhead/ takes it out of
// the tree entirely.
//
// This is deliberately a readout, not an alert. Under a downwind leg
// something is almost always about to go overhead, so "is anything
// overhead?" carries near-zero information and an alarm on it would be
// ignored within a day. Reporting the state continuously is useful in a way
// that interrupting is not.
//
// The hard part is not the geometry, it is knowing when NOT to answer.
// Straight-line extrapolation is excellent for arrivals on a long stable
// leg and worthless for departures turning onto a SID, so anything
// manoeuvring is excluded rather than guessed at.

namespace radar {

// Lateral miss distance that counts as "overhead". Not a cone: altitude is
// ignored, because for a look-out-of-the-window readout a jet at FL350 and a
// light aircraft at 2000ft both pass over the same patch of sky.
constexpr float OVERHEAD_RADIUS_NM = 1.0f;

// Beyond this there is no point predicting: the aircraft has more time to
// change its mind than the prediction has validity.
constexpr float OVERHEAD_HORIZON_S = 150.0f;

// Curvature, degrees of track change per nautical mile travelled. A
// standard-rate turn is ~43 deg/nm at 250kt; straight flight with position
// noise sits near zero. Using curvature rather than degrees-per-second means
// one threshold works at every speed — and needs no timestamps, which trail
// points no longer carry now that they are distance-gated.
constexpr float OVERHEAD_MAX_TURN_DEG_PER_NM = 8.0f;

// Fewer points than this is not enough evidence of flying straight.
constexpr int OVERHEAD_MIN_TRAIL = 4;

// Below this, extrapolation is meaningless and the aircraft is probably on
// the ground or in a hold.
constexpr uint16_t OVERHEAD_MIN_GS_KT = 60;

struct OverheadPrediction {
  uint32_t hex;
  uint16_t secondsAway;
  float missNm;
  bool valid;
};

// True when the aircraft's recent track is straight enough for a
// straight-line extrapolation to mean anything.
bool isTrackSteady(const Aircraft &a);

// Soonest aircraft predicted to pass within OVERHEAD_RADIUS_NM of home.
// extraAgeS ages every position by the wall-clock time since the last poll,
// so the prediction is anchored to now rather than to the fetch.
OverheadPrediction predictOverhead(const AircraftStore &s, float extraAgeS);

} // namespace radar
