#include <unity.h>
#include "classify.h"

using namespace radar;

static void test_a320_family_is_common() {
  TEST_ASSERT_TRUE(isCommonType("A320"));
  TEST_ASSERT_TRUE(isCommonType("A321"));
  TEST_ASSERT_TRUE(isCommonType("A20N"));
  TEST_ASSERT_TRUE(isCommonType("A21N"));
}

static void test_737_family_is_common() {
  TEST_ASSERT_TRUE(isCommonType("B738"));
  TEST_ASSERT_TRUE(isCommonType("B38M"));
}

static void test_ejets_and_turboprops_are_common() {
  TEST_ASSERT_TRUE(isCommonType("E190"));
  TEST_ASSERT_TRUE(isCommonType("AT72"));
  TEST_ASSERT_TRUE(isCommonType("DH8D"));
}

static void test_widebodies_are_interesting() {
  TEST_ASSERT_FALSE(isCommonType("B788"));
  TEST_ASSERT_FALSE(isCommonType("A359"));
  TEST_ASSERT_FALSE(isCommonType("B744"));
  TEST_ASSERT_FALSE(isCommonType("A388"));
}

static void test_bizjets_props_helis_military_are_interesting() {
  TEST_ASSERT_FALSE(isCommonType("GLF6"));
  TEST_ASSERT_FALSE(isCommonType("C172"));
  TEST_ASSERT_FALSE(isCommonType("EC35"));
  TEST_ASSERT_FALSE(isCommonType("A400"));
}

// The receiver's aircraft database has gaps and parse.cpp leaves type empty
// on a miss. Flagging those as rare would fire the highlight constantly.
static void test_unknown_type_is_treated_as_common() {
  TEST_ASSERT_TRUE(isCommonType(""));
  TEST_ASSERT_TRUE(isCommonType(nullptr));
}

static void test_type_match_is_exact_not_prefix() {
  TEST_ASSERT_FALSE(isCommonType("A32"));  // truncated, not a real designator
  TEST_ASSERT_FALSE(isCommonType("B7"));
  TEST_ASSERT_FALSE(isCommonType("A3200"));
}

static void test_alert_squawks() {
  TEST_ASSERT_TRUE(isAlertSquawk("7500"));
  TEST_ASSERT_TRUE(isAlertSquawk("7600"));
  TEST_ASSERT_TRUE(isAlertSquawk("7700"));
}

static void test_ordinary_squawks_are_not_alerts() {
  TEST_ASSERT_FALSE(isAlertSquawk("7000")); // VFR conspicuity
  TEST_ASSERT_FALSE(isAlertSquawk("1000")); // Mode S conspicuity
  TEST_ASSERT_FALSE(isAlertSquawk("0100"));
  TEST_ASSERT_FALSE(isAlertSquawk("7701")); // adjacent, not an alert
  TEST_ASSERT_FALSE(isAlertSquawk(""));
  TEST_ASSERT_FALSE(isAlertSquawk(nullptr));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_a320_family_is_common);
  RUN_TEST(test_737_family_is_common);
  RUN_TEST(test_ejets_and_turboprops_are_common);
  RUN_TEST(test_widebodies_are_interesting);
  RUN_TEST(test_bizjets_props_helis_military_are_interesting);
  RUN_TEST(test_unknown_type_is_treated_as_common);
  RUN_TEST(test_type_match_is_exact_not_prefix);
  RUN_TEST(test_alert_squawks);
  RUN_TEST(test_ordinary_squawks_are_not_alerts);
  return UNITY_END();
}
