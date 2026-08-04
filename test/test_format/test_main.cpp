#include <unity.h>
#include <string.h>
#include "format.h"

using namespace radar;

static void test_on_ground_shows_gnd_regardless_of_altitude() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 12345, true);
  TEST_ASSERT_EQUAL_STRING("GND", buf);
}

static void test_zero_feet() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 0, false);
  TEST_ASSERT_EQUAL_STRING("0", buf);
}

static void test_just_below_transition_shows_feet() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 5950, false);
  TEST_ASSERT_EQUAL_STRING("5950", buf);
}

static void test_5999_shows_feet_not_flight_level() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 5999, false);
  TEST_ASSERT_EQUAL_STRING("5999", buf);
}

static void test_6000_is_flight_level() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 6000, false);
  TEST_ASSERT_EQUAL_STRING("FL060", buf);
}

static void test_17950_rounds_to_fl180() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 17950, false);
  TEST_ASSERT_EQUAL_STRING("FL180", buf);
}

static void test_34975_rounds_to_fl350() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), 34975, false);
  TEST_ASSERT_EQUAL_STRING("FL350", buf);
}

static void test_negative_altitude() {
  char buf[8];
  formatAltitude(buf, sizeof(buf), -50, false);
  TEST_ASSERT_EQUAL_STRING("-50", buf);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_on_ground_shows_gnd_regardless_of_altitude);
  RUN_TEST(test_zero_feet);
  RUN_TEST(test_just_below_transition_shows_feet);
  RUN_TEST(test_5999_shows_feet_not_flight_level);
  RUN_TEST(test_6000_is_flight_level);
  RUN_TEST(test_17950_rounds_to_fl180);
  RUN_TEST(test_34975_rounds_to_fl350);
  RUN_TEST(test_negative_altitude);
  return UNITY_END();
}
