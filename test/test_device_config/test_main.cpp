#include <unity.h>
#include <string.h>
#include "classify.h"
#include "device_config.h"
#include "site_config_data.h"

using namespace radar;

// ------------------------------------------------------------- the table

static void test_only_safe_keys_are_offered() {
  // WiFi, OTA and the receiver URL stay behind the captive portal. Reaching
  // any of them from the LAN would let a typo cost the board the network that
  // makes it reflashable.
  const char *forbidden[] = {"ssid", "pass", "recv", "otahost", "otapass",
                             "metar", "geo", "lat", "lon"};
  for (size_t i = 0; i < sizeof(forbidden) / sizeof(forbidden[0]); i++)
    TEST_ASSERT_NULL(deviceFieldByKey(forbidden[i]));
}

static void test_the_expected_keys_are_present() {
  const char *expected[] = {"nstart",  "nend",  "nwake", "nfade", "nduty",
                            "poll",    "mpoll", "gpoll", "metaron",
                            "geoon",   "ntp",   "tz",    "types"};
  size_t n = sizeof(expected) / sizeof(expected[0]);
  TEST_ASSERT_EQUAL_size_t(n, DEVICE_FIELD_COUNT);
  for (size_t i = 0; i < n; i++)
    TEST_ASSERT_NOT_NULL(deviceFieldByKey(expected[i]));
}

static void test_keys_fit_the_nvs_limit() {
  // NVS caps key names at 15 characters. site_config.cpp treats these as a
  // wire format for the same reason.
  for (size_t i = 0; i < DEVICE_FIELD_COUNT; i++)
    TEST_ASSERT_TRUE(strlen(DEVICE_FIELDS[i].key) <= 15);
}

static void test_unknown_key_is_not_a_field() {
  TEST_ASSERT_NULL(deviceFieldByKey("nope"));
  TEST_ASSERT_NULL(deviceFieldByKey(""));
  TEST_ASSERT_NULL(deviceFieldByKey(nullptr));
}

// -------------------------------------------------------------- numbers

static uint32_t parsed(const char *key, const char *value,
                       const char **problem) {
  const DeviceField *f = deviceFieldByKey(key);
  TEST_ASSERT_NOT_NULL(f);
  uint32_t out = 0xDEADBEEF;
  *problem = deviceFieldProblem(*f, value, &out);
  return out;
}

static void test_a_value_in_range_parses() {
  const char *problem = "unset";
  uint32_t v = parsed("nstart", "23", &problem);
  TEST_ASSERT_NULL(problem);
  TEST_ASSERT_EQUAL_UINT32(23, v);
}

static void test_bounds_are_inclusive() {
  const char *problem = "unset";
  parsed("nstart", "0", &problem);
  TEST_ASSERT_NULL(problem);
  parsed("nstart", "23", &problem);
  TEST_ASSERT_NULL(problem);
  parsed("nstart", "24", &problem);
  TEST_ASSERT_NOT_NULL(problem);
}

static void test_equal_night_hours_are_accepted() {
  // night_mode.cpp treats start == end as "disabled". It is the off switch.
  const char *problem = "unset";
  parsed("nstart", "3", &problem);
  TEST_ASSERT_NULL(problem);
  parsed("nend", "3", &problem);
  TEST_ASSERT_NULL(problem);
}

static void test_a_negative_number_does_not_wrap() {
  // strtoul() would turn "-1" into 4294967295, which passes any upper bound
  // wide enough. This is why the parser is hand-rolled.
  const char *problem = "unset";
  parsed("nfade", "-1", &problem);
  TEST_ASSERT_NOT_NULL(problem);
}

static void test_trailing_text_is_refused() {
  // strtoul() would accept "2000ms" as 2000 and drop the units silently.
  const char *problem = "unset";
  parsed("poll", "2000ms", &problem);
  TEST_ASSERT_NOT_NULL(problem);
}

static void test_overflow_is_refused_rather_than_wrapped() {
  const char *problem = "unset";
  parsed("gpoll", "99999999999999999999", &problem);
  TEST_ASSERT_NOT_NULL(problem);
}

static void test_empty_is_refused() {
  const char *problem = "unset";
  parsed("poll", "", &problem);
  TEST_ASSERT_NOT_NULL(problem);
}

static void test_a_failed_parse_does_not_write_out() {
  const DeviceField *f = deviceFieldByKey("poll");
  uint32_t out = 12345;
  TEST_ASSERT_NOT_NULL(deviceFieldProblem(*f, "banana", &out));
  TEST_ASSERT_EQUAL_UINT32(12345, out);  // untouched
}

static void test_the_feed_switches_are_boolean() {
  // Stored and read as UInt32 like every other numeric key — the type
  // mismatch that made the night clock invisible is not worth repeating for
  // the sake of a narrower field.
  const char *problem = "unset";
  parsed("metaron", "0", &problem);
  TEST_ASSERT_NULL(problem);
  parsed("geoon", "1", &problem);
  TEST_ASSERT_NULL(problem);
  parsed("metaron", "2", &problem);
  TEST_ASSERT_NOT_NULL(problem);
}

static void test_the_type_list_field_is_wide_enough_for_the_built_in_one() {
  // The default list is 134 characters. A field that could not hold what the
  // board already uses would make the UI unable to show its own default.
  const DeviceField *f = deviceFieldByKey("types");
  TEST_ASSERT_NOT_NULL(f);
  TEST_ASSERT_EQUAL_UINT32(CFG_TYPES_LEN - 1, f->high);
  TEST_ASSERT_TRUE(strlen(classifyDefaultCommonTypes()) < f->high);
  TEST_ASSERT_NULL(deviceFieldProblem(*f, classifyDefaultCommonTypes(),
                                      nullptr));
}

static void test_poll_floor_protects_the_receiver() {
  const char *problem = "unset";
  parsed("poll", "10", &problem);
  TEST_ASSERT_NOT_NULL(problem);
  parsed("poll", "2000", &problem);
  TEST_ASSERT_NULL(problem);
}

// -------------------------------------------------------------- strings

static void test_a_string_within_its_field_is_accepted() {
  const DeviceField *f = deviceFieldByKey("ntp");
  TEST_ASSERT_NULL(deviceFieldProblem(*f, "pool.ntp.org", nullptr));
}

static void test_string_limits_match_the_struct_they_land_in() {
  // A value that passes here must be one cfgSetStr() also accepts, or the
  // board would report a problem for something the UI called valid.
  TEST_ASSERT_EQUAL_UINT32(CFG_HOST_LEN - 1, deviceFieldByKey("ntp")->high);
  TEST_ASSERT_EQUAL_UINT32(CFG_TZ_LEN - 1, deviceFieldByKey("tz")->high);
}

static void test_an_oversized_string_is_refused_not_truncated() {
  const DeviceField *f = deviceFieldByKey("tz");
  char big[CFG_TZ_LEN + 8];
  memset(big, 'X', sizeof(big) - 1);
  big[sizeof(big) - 1] = '\0';
  TEST_ASSERT_NOT_NULL(deviceFieldProblem(*f, big, nullptr));
}

static void test_a_string_exactly_at_the_limit_fits() {
  const DeviceField *f = deviceFieldByKey("tz");
  char exact[CFG_TZ_LEN];
  memset(exact, 'X', CFG_TZ_LEN - 1);
  exact[CFG_TZ_LEN - 1] = '\0';
  TEST_ASSERT_NULL(deviceFieldProblem(*f, exact, nullptr));
}

static void test_an_empty_string_is_refused() {
  const DeviceField *f = deviceFieldByKey("ntp");
  TEST_ASSERT_NOT_NULL(deviceFieldProblem(*f, "", nullptr));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_only_safe_keys_are_offered);
  RUN_TEST(test_the_expected_keys_are_present);
  RUN_TEST(test_keys_fit_the_nvs_limit);
  RUN_TEST(test_unknown_key_is_not_a_field);
  RUN_TEST(test_a_value_in_range_parses);
  RUN_TEST(test_bounds_are_inclusive);
  RUN_TEST(test_equal_night_hours_are_accepted);
  RUN_TEST(test_a_negative_number_does_not_wrap);
  RUN_TEST(test_trailing_text_is_refused);
  RUN_TEST(test_overflow_is_refused_rather_than_wrapped);
  RUN_TEST(test_empty_is_refused);
  RUN_TEST(test_a_failed_parse_does_not_write_out);
  RUN_TEST(test_the_feed_switches_are_boolean);
  RUN_TEST(test_the_type_list_field_is_wide_enough_for_the_built_in_one);
  RUN_TEST(test_poll_floor_protects_the_receiver);
  RUN_TEST(test_a_string_within_its_field_is_accepted);
  RUN_TEST(test_string_limits_match_the_struct_they_land_in);
  RUN_TEST(test_an_oversized_string_is_refused_not_truncated);
  RUN_TEST(test_a_string_exactly_at_the_limit_fits);
  RUN_TEST(test_an_empty_string_is_refused);
  return UNITY_END();
}
