#pragma once
#include "aircraft.h"

// Predicts which aircraft will next pass close to overhead.
//
// Optional at RUNTIME: the `ohon` setting stops src/ui/scope.cpp calling any
// of this, so trying the panel without the readout no longer costs a flash.
// OVERHEAD_PREDICTION in config.h now only chooses what that setting defaults
// to — the code is compiled either way, which is the ~1424 bytes of flash the
// old #ifdef saved. Deleting overhead.{h,cpp}, src/ui/overhead_readout.{h,cpp}
// and test/test_overhead/ is what takes it out of the tree entirely.
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

// The three thresholds that decide what "overhead" means. Settable at runtime
// for the same reason the scope's ranges are: 1nm and 150s are a choice about
// how busy the sky overhead is, and the only way to find the right one is to
// try a few. They were compiled constants, so each attempt cost a flash.
//
// Held here rather than in siteConfig() because src/site_config.cpp is
// Arduino/NVS code the native tests do not link, while lib/radarcore is
// compiled straight into them — the same split that view_ranges.h and
// classifySetCommonTypes() exist for. The firmware pushes NVS in at boot; the
// tests push values in directly.
struct OverheadParams {
  // Lateral miss distance that counts as "overhead". Not a cone: altitude is
  // ignored, because for a look-out-of-the-window readout a jet at FL350 and a
  // light aircraft at 2000ft both pass over the same patch of sky.
  float radiusNm;

  // Beyond this there is no point predicting: the aircraft has more time to
  // change its mind than the prediction has validity.
  float horizonS;

  // Curvature, degrees of track change per nautical mile travelled. A
  // standard-rate turn is ~43 deg/nm at 250kt; straight flight with position
  // noise sits near zero. Using curvature rather than degrees-per-second means
  // one threshold works at every speed — and needs no timestamps, which trail
  // points no longer carry now that they are distance-gated.
  float maxTurnDegPerNm;
};

// The live thresholds. Returns the compiled defaults until overheadParamsSet()
// is called, so the native tests and a board with empty NVS behave alike.
const OverheadParams &overheadParams();

// The compiled defaults, so the configuration UI can say what it would fall
// back to and the tests have something to compare against.
const OverheadParams &overheadParamsDefaults();

// Replace the live thresholds. A non-positive value is IGNORED and the
// previous one kept: a zero radius or horizon would silence the readout
// permanently and look like a broken feature rather than a bad setting. The
// bounds in DEVICE_FIELDS should have refused it long before — this is a
// backstop, not the validation.
void overheadParamsSet(const OverheadParams &p);

// Fewer points than this is not enough evidence of flying straight. Left
// compiled: unlike the three above it is a statement about how much evidence
// the trail buffer can hold, not a preference about the sky.
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

// Soonest aircraft predicted to pass within overheadParams().radiusNm of home.
// extraAgeS ages every position by the wall-clock time since the last poll,
// so the prediction is anchored to now rather than to the fetch.
OverheadPrediction predictOverhead(const AircraftStore &s, float extraAgeS);

} // namespace radar
