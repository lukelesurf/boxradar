#include <unity.h>
#include <string.h>
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

// ------------------------------------------------- a configured list

static void test_an_override_replaces_the_built_in_list() {
  // The built-in list is explicitly "types that saturate a LONDON-area feed".
  // A box somewhere else wants a different one, and that should not be a
  // reflash.
  classifySetCommonTypes("C172,PA28");
  TEST_ASSERT_TRUE(isCommonType("C172"));
  TEST_ASSERT_TRUE(isCommonType("PA28"));
  TEST_ASSERT_FALSE(isCommonType("A320"));  // no longer boring here
  classifySetCommonTypes(nullptr);
  TEST_ASSERT_TRUE(isCommonType("A320"));   // built-in restored
}

static void test_an_empty_override_falls_back_to_the_built_in() {
  // Distinct from "everything is interesting": an empty setting is far more
  // likely to be a cleared box than a deliberate choice, and silently making
  // every aircraft light up would be a poor reading of it.
  classifySetCommonTypes("");
  TEST_ASSERT_TRUE(isCommonType("A320"));
  classifySetCommonTypes(nullptr);
}

static void test_a_list_is_read_case_insensitively() {
  // Feeds send uppercase, but a list is typed by a person.
  classifySetCommonTypes("a320,b738");
  TEST_ASSERT_TRUE(isCommonType("A320"));
  TEST_ASSERT_TRUE(isCommonType("B738"));
  classifySetCommonTypes(nullptr);
}

static void test_spaces_around_entries_are_tolerated() {
  classifySetCommonTypes(" A320 , B738 ");
  TEST_ASSERT_TRUE(isCommonType("A320"));
  TEST_ASSERT_TRUE(isCommonType("B738"));
  classifySetCommonTypes(nullptr);
}

static void test_a_prefix_does_not_match() {
  // "A32" must not match "A320": entries are whole designators.
  classifySetCommonTypes("A320");
  TEST_ASSERT_FALSE(isCommonType("A32"));
  TEST_ASSERT_FALSE(isCommonType("A3200"));
  classifySetCommonTypes(nullptr);
}

static void test_empty_entries_are_skipped() {
  // Trailing commas and doubled separators are what hand-edited lists look
  // like, and an empty entry must not match an empty type.
  classifySetCommonTypes("A320,,B738,");
  TEST_ASSERT_TRUE(isCommonType("A320"));
  TEST_ASSERT_TRUE(isCommonType("B738"));
  TEST_ASSERT_FALSE(isCommonType("C172"));
  classifySetCommonTypes(nullptr);
}

static void test_the_built_in_list_is_readable() {
  // The UI seeds its box with this, so it has to be reachable and non-empty.
  const char *csv = classifyDefaultCommonTypes();
  TEST_ASSERT_NOT_NULL(csv);
  TEST_ASSERT_TRUE(strlen(csv) > 0);
  TEST_ASSERT_TRUE(isCommonTypeIn("A320", csv));
  TEST_ASSERT_FALSE(isCommonTypeIn("B788", csv));
}

static void test_an_unknown_type_is_still_boring_under_an_override() {
  // The reason is unchanged: the type only exists if readsb was started with
  // a --db-file, and that database has gaps. Treating a lookup miss as rare
  // would fire the highlight on noise.
  classifySetCommonTypes("C172");
  TEST_ASSERT_TRUE(isCommonType(""));
  TEST_ASSERT_TRUE(isCommonType(nullptr));
  classifySetCommonTypes(nullptr);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_an_override_replaces_the_built_in_list);
  RUN_TEST(test_an_empty_override_falls_back_to_the_built_in);
  RUN_TEST(test_a_list_is_read_case_insensitively);
  RUN_TEST(test_spaces_around_entries_are_tolerated);
  RUN_TEST(test_a_prefix_does_not_match);
  RUN_TEST(test_empty_entries_are_skipped);
  RUN_TEST(test_the_built_in_list_is_readable);
  RUN_TEST(test_an_unknown_type_is_still_boring_under_an_override);
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
