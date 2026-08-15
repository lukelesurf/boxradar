#include <unity.h>
#include <string.h>
#include <math.h>
#include "overhead.h"

using namespace radar;

// Lays a straight trail of `n` points ending at (x,y), running backwards
// along the reciprocal of `track` at `spacing` NM.
static Aircraft straightFlyer(uint32_t hex, float x, float y, uint16_t track,
                              uint16_t gs, int n = 6, float spacing = 0.45f) {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = hex;
  a.pos = {x, y};
  a.trackDeg = track;
  a.gsKt = gs;
  float rad = track * (float)M_PI / 180.0f;
  float ux = sinf(rad), uy = cosf(rad);
  for (int i = 0; i < n; i++) {
    float back = (float)(n - 1 - i) * spacing;
    a.trail[i] = {x - ux * back, y - uy * back};
  }
  a.trailLen = (uint8_t)n;
  a.trailHead = (uint8_t)(n % TRAIL_LEN);
  return a;
}

// ---------------------------------------------------------- steadiness

static void test_straight_trail_is_steady() {
  Aircraft a = straightFlyer(1, 0.0f, 10.0f, 180, 250);
  TEST_ASSERT_TRUE(isTrackSteady(a));
}

static void test_short_trail_is_not_trusted() {
  Aircraft a = straightFlyer(1, 0.0f, 10.0f, 180, 250, OVERHEAD_MIN_TRAIL - 1);
  TEST_ASSERT_FALSE(isTrackSteady(a));
}

// A SID departure turning steadily must be rejected — this is the case that
// would otherwise make the readout confidently wrong.
static void test_turning_trail_is_rejected() {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = 2;
  a.gsKt = 250;
  a.trackDeg = 90;
  const int n = 6;
  const float spacing = 0.45f;
  float x = 0.0f, y = 0.0f, hdg = 0.0f;
  for (int i = 0; i < n; i++) {
    a.trail[i] = {x, y};
    hdg += 20.0f; // 20 deg per 0.45nm = ~44 deg/nm, a standard-rate turn
    float r = hdg * (float)M_PI / 180.0f;
    x += sinf(r) * spacing;
    y += cosf(r) * spacing;
  }
  a.trailLen = n;
  a.trailHead = n % TRAIL_LEN;
  a.pos = {x, y};
  TEST_ASSERT_FALSE(isTrackSteady(a));
}

// Small corrections must not disqualify an otherwise straight aircraft.
static void test_gentle_wander_is_still_steady() {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = 3;
  a.gsKt = 250;
  a.trackDeg = 0;
  const int n = 6;
  const float spacing = 0.45f;
  float x = 0.0f, y = 0.0f;
  for (int i = 0; i < n; i++) {
    a.trail[i] = {x, y};
    float hdg = (i % 2 == 0) ? 1.0f : -1.0f; // ~2 deg/nm of jitter
    float r = hdg * (float)M_PI / 180.0f;
    x += sinf(r) * spacing;
    y += cosf(r) * spacing;
  }
  a.trailLen = n;
  a.trailHead = n % TRAIL_LEN;
  a.pos = {x, y};
  TEST_ASSERT_TRUE(isTrackSteady(a));
}

// ---------------------------------------------------------- prediction

static void test_inbound_overhead_is_predicted() {
  AircraftStore s;
  s.clear();
  // 10nm due north, tracking 180 (southbound) at 360kt = 0.1 nm/s -> 100s.
  s.insertByRange(straightFlyer(1, 0.0f, 10.0f, 180, 360));
  OverheadPrediction p = predictOverhead(s, 0.0f);
  TEST_ASSERT_TRUE(p.valid);
  TEST_ASSERT_EQUAL_UINT32(1, p.hex);
  TEST_ASSERT_UINT16_WITHIN(2, 100, p.secondsAway);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, p.missNm);
}

static void test_receding_aircraft_is_not_predicted() {
  AircraftStore s;
  s.clear();
  // 10nm north, tracking 000 (away). Closest approach is in the past.
  s.insertByRange(straightFlyer(1, 0.0f, 10.0f, 0, 360));
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);
}

static void test_passing_wide_is_not_overhead() {
  AircraftStore s;
  s.clear();
  // Tracking south but offset 5nm east: it will pass, but 5nm away.
  s.insertByRange(straightFlyer(1, 5.0f, 10.0f, 180, 360));
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);
}

static void test_beyond_horizon_is_not_predicted() {
  AircraftStore s;
  s.clear();
  // 40nm out at 360kt = 400s away, well past the horizon.
  s.insertByRange(straightFlyer(1, 0.0f, 40.0f, 180, 360));
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);
}

static void test_soonest_wins() {
  AircraftStore s;
  s.clear();
  s.insertByRange(straightFlyer(1, 0.0f, 10.0f, 180, 360));  // ~100s
  s.insertByRange(straightFlyer(2, 0.0f, -4.0f, 0, 360));    // ~40s
  OverheadPrediction p = predictOverhead(s, 0.0f);
  TEST_ASSERT_TRUE(p.valid);
  TEST_ASSERT_EQUAL_UINT32(2, p.hex);
}

static void test_turning_aircraft_excluded_from_prediction() {
  AircraftStore s;
  s.clear();
  Aircraft a = straightFlyer(1, 0.0f, 10.0f, 180, 360);
  a.trailLen = 2; // too little evidence of straight flight
  s.insertByRange(a);
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);
}

static void test_slow_and_ground_traffic_ignored() {
  AircraftStore s;
  s.clear();
  s.insertByRange(straightFlyer(1, 0.0f, 1.0f, 180, 20)); // 20kt
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);

  AircraftStore g;
  g.clear();
  Aircraft a = straightFlyer(2, 0.0f, 1.0f, 180, 360);
  a.onGround = true;
  g.insertByRange(a);
  TEST_ASSERT_FALSE(predictOverhead(g, 0.0f).valid);
}

// Positions are already stale when parsed; ageing them forward must bring
// the predicted time closer, not leave it anchored to the fetch.
static void test_age_advances_the_prediction() {
  AircraftStore s;
  s.clear();
  Aircraft a = straightFlyer(1, 0.0f, 10.0f, 180, 360);
  a.seenS = 5.0f;
  s.insertByRange(a);
  OverheadPrediction p = predictOverhead(s, 3.0f); // 8s of total age
  TEST_ASSERT_TRUE(p.valid);
  TEST_ASSERT_UINT16_WITHIN(2, 92, p.secondsAway); // 100 - 8
}

// ------------------------------------------------------ runtime thresholds
//
// Every test above runs against the compiled defaults, so these restore them
// afterwards. The state is a file-static in overhead.cpp and the tests share
// one process — a widened radius left behind here would make an unrelated
// test pass for the wrong reason, which is the failure this whole file exists
// to prevent.

static void test_a_widened_radius_admits_a_wide_pass() {
  AircraftStore s;
  s.clear();
  s.insertByRange(straightFlyer(1, 5.0f, 10.0f, 180, 360)); // 5nm miss
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);

  OverheadParams p = overheadParamsDefaults();
  p.radiusNm = 6.0f;
  overheadParamsSet(p);
  TEST_ASSERT_TRUE(predictOverhead(s, 0.0f).valid);

  overheadParamsSet(overheadParamsDefaults());
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);
}

static void test_a_longer_horizon_admits_a_distant_arrival() {
  AircraftStore s;
  s.clear();
  s.insertByRange(straightFlyer(1, 0.0f, 40.0f, 180, 360)); // 400s away
  TEST_ASSERT_FALSE(predictOverhead(s, 0.0f).valid);

  OverheadParams p = overheadParamsDefaults();
  p.horizonS = 500.0f;
  overheadParamsSet(p);
  TEST_ASSERT_TRUE(predictOverhead(s, 0.0f).valid);

  overheadParamsSet(overheadParamsDefaults());
}

static void test_a_slack_turn_threshold_admits_a_turning_aircraft() {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = 1;
  a.trackDeg = 180;
  a.gsKt = 250;
  // ~15 deg per 0.45nm leg: a third of a rate-one turn, well over the 8
  // deg/nm default and under the 45 the field's ceiling allows.
  float x = 0.0f, y = 10.0f, heading = 180.0f;
  for (int i = 0; i < 6; i++) {
    a.trail[i] = {x, y};
    float rad = heading * (float)M_PI / 180.0f;
    x += sinf(rad) * 0.45f;
    y += cosf(rad) * 0.45f;
    heading += 15.0f;
  }
  a.trailLen = 6;
  a.trailHead = 6;
  TEST_ASSERT_FALSE(isTrackSteady(a));

  OverheadParams p = overheadParamsDefaults();
  p.maxTurnDegPerNm = 45.0f;
  overheadParamsSet(p);
  TEST_ASSERT_TRUE(isTrackSteady(a));

  overheadParamsSet(overheadParamsDefaults());
  TEST_ASSERT_FALSE(isTrackSteady(a));
}

static void test_a_non_positive_threshold_is_ignored_not_stored() {
  // A zero radius would silence the readout permanently, which looks like a
  // broken feature rather than a bad setting. DEVICE_FIELDS refuses it first;
  // this is the backstop behind that.
  OverheadParams zeroed = {0.0f, 0.0f, 0.0f};
  overheadParamsSet(zeroed);
  TEST_ASSERT_EQUAL_FLOAT(overheadParamsDefaults().radiusNm,
                          overheadParams().radiusNm);
  TEST_ASSERT_EQUAL_FLOAT(overheadParamsDefaults().horizonS,
                          overheadParams().horizonS);
  TEST_ASSERT_EQUAL_FLOAT(overheadParamsDefaults().maxTurnDegPerNm,
                          overheadParams().maxTurnDegPerNm);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_straight_trail_is_steady);
  RUN_TEST(test_short_trail_is_not_trusted);
  RUN_TEST(test_turning_trail_is_rejected);
  RUN_TEST(test_gentle_wander_is_still_steady);
  RUN_TEST(test_inbound_overhead_is_predicted);
  RUN_TEST(test_receding_aircraft_is_not_predicted);
  RUN_TEST(test_passing_wide_is_not_overhead);
  RUN_TEST(test_beyond_horizon_is_not_predicted);
  RUN_TEST(test_soonest_wins);
  RUN_TEST(test_turning_aircraft_excluded_from_prediction);
  RUN_TEST(test_slow_and_ground_traffic_ignored);
  RUN_TEST(test_age_advances_the_prediction);
  RUN_TEST(test_a_widened_radius_admits_a_wide_pass);
  RUN_TEST(test_a_longer_horizon_admits_a_distant_arrival);
  RUN_TEST(test_a_slack_turn_threshold_admits_a_turning_aircraft);
  RUN_TEST(test_a_non_positive_threshold_is_ignored_not_stored);
  return UNITY_END();
}
