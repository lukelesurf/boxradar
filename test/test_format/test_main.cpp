#include <unity.h>
#include <string.h>
#include "format.h"

using namespace radar;

static void expectAlt(const char *want, int32_t altFt, bool onGround = false) {
  char buf[8];
  formatAltitude(buf, sizeof(buf), altFt, onGround);
  TEST_ASSERT_EQUAL_STRING(want, buf);
}

static void test_on_ground_shows_gnd_regardless_of_altitude() {
  expectAlt("GND", 12345, true);
}

static void test_zero_feet() { expectAlt("000", 0); }

static void test_cruise_levels() {
  expectAlt("350", 34975);
  expectAlt("180", 17950);
}

// The behaviour change: these used to render as raw feet ("5950", "4500")
// below a 6000ft transition altitude. There is no transition any more.
static void test_below_old_transition_is_still_hundreds() {
  expectAlt("060", 5950);
  expectAlt("045", 4500);
}

static void test_no_discontinuity_across_the_old_transition() {
  expectAlt("059", 5949);
  expectAlt("060", 5950);
  expectAlt("060", 6000);
  expectAlt("061", 6050);
}

static void test_rounds_to_nearest_hundred() {
  expectAlt("000", 49);
  expectAlt("001", 50);
  expectAlt("001", 149);
  expectAlt("002", 150);
}

// Below-datum readings happen when QNH is above standard. Report them rather
// than clamping to 000, which would misrepresent a real value.
static void test_small_negatives_round_away_from_zero() {
  expectAlt("000", -49);
  expectAlt("-01", -50);
  expectAlt("-02", -150);
}

static void test_always_three_digits_for_low_levels() {
  expectAlt("005", 500);
  expectAlt("010", 1000);
}

static void test_callsign_used_when_present() {
  char buf[10];
  formatCallsign(buf, sizeof(buf), "RYR12QD", 0x4ca1d2);
  TEST_ASSERT_EQUAL_STRING("RYR12QD", buf);
}

static void test_callsign_falls_back_to_last_four_hex() {
  char buf[10];
  formatCallsign(buf, sizeof(buf), "", 0x4ca1d2);
  TEST_ASSERT_EQUAL_STRING("a1d2", buf);
  formatCallsign(buf, sizeof(buf), nullptr, 0x406b9e);
  TEST_ASSERT_EQUAL_STRING("6b9e", buf);
}

// Leading zeros in the hex tail must survive, or two aircraft can collide
// onto the same label.
static void test_callsign_hex_fallback_is_zero_padded() {
  char buf[10];
  formatCallsign(buf, sizeof(buf), "", 0x400042);
  TEST_ASSERT_EQUAL_STRING("0042", buf);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_on_ground_shows_gnd_regardless_of_altitude);
  RUN_TEST(test_zero_feet);
  RUN_TEST(test_cruise_levels);
  RUN_TEST(test_below_old_transition_is_still_hundreds);
  RUN_TEST(test_no_discontinuity_across_the_old_transition);
  RUN_TEST(test_rounds_to_nearest_hundred);
  RUN_TEST(test_small_negatives_round_away_from_zero);
  RUN_TEST(test_always_three_digits_for_low_levels);
  RUN_TEST(test_callsign_used_when_present);
  RUN_TEST(test_callsign_falls_back_to_last_four_hex);
  RUN_TEST(test_callsign_hex_fallback_is_zero_padded);
  return UNITY_END();
}
