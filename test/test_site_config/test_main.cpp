#include <unity.h>
#include <string.h>
#include "site_config_data.h"

using namespace radar;

static SiteConfig good() {
  SiteConfig c;
  memset(&c, 0, sizeof(c));
  cfgSetStr(c.wifiSsid, CFG_SSID_LEN, "somewifi");
  cfgSetStr(c.receiverUrl, CFG_URL_LEN, "http://host/data/aircraft.json");
  c.homeLat = 51.8850f;
  c.homeLon = 0.2350f;
  c.pollIntervalMs = 2000;
  c.nightStartHour = 0;
  c.nightEndHour = 7;
  return c;
}

static void test_a_plausible_config_is_valid() {
  TEST_ASSERT_TRUE(siteConfigValid(good()));
  TEST_ASSERT_EQUAL_STRING("", siteConfigProblem(good()));
}

static void test_set_str_copies() {
  char buf[8];
  TEST_ASSERT_TRUE(cfgSetStr(buf, sizeof(buf), "abc"));
  TEST_ASSERT_EQUAL_STRING("abc", buf);
}

static void test_set_str_fills_exactly() {
  char buf[4];
  TEST_ASSERT_TRUE(cfgSetStr(buf, sizeof(buf), "abc"));
  TEST_ASSERT_EQUAL_STRING("abc", buf);
}

static void test_set_str_refuses_rather_than_truncating() {
  // A silently shortened SSID or URL fails later and further away than a
  // rejected one.
  char buf[4] = "old";
  TEST_ASSERT_FALSE(cfgSetStr(buf, sizeof(buf), "abcd"));
  TEST_ASSERT_EQUAL_STRING("old", buf);
}

static void test_set_str_null_clears() {
  char buf[8] = "abc";
  TEST_ASSERT_TRUE(cfgSetStr(buf, sizeof(buf), NULL));
  TEST_ASSERT_EQUAL_STRING("", buf);
}

static void test_missing_ssid_is_invalid() {
  SiteConfig c = good();
  c.wifiSsid[0] = '\0';
  TEST_ASSERT_FALSE(siteConfigValid(c));
  TEST_ASSERT_EQUAL_STRING("no WiFi SSID", siteConfigProblem(c));
}

static void test_missing_receiver_is_invalid() {
  SiteConfig c = good();
  c.receiverUrl[0] = '\0';
  TEST_ASSERT_FALSE(siteConfigValid(c));
}

static void test_home_at_null_island_is_rejected() {
  // 0,0 is in the Gulf of Guinea. Far likelier to mean "never set" than to be
  // a real site, and the whole map would project around the wrong place.
  SiteConfig c = good();
  c.homeLat = 0.0f;
  c.homeLon = 0.0f;
  TEST_ASSERT_FALSE(siteConfigValid(c));
}

static void test_out_of_range_home_is_rejected() {
  SiteConfig c = good();
  c.homeLat = 91.0f;
  TEST_ASSERT_FALSE(siteConfigValid(c));
  c = good();
  c.homeLon = -181.0f;
  TEST_ASSERT_FALSE(siteConfigValid(c));
}

static void test_absurd_poll_interval_is_rejected() {
  SiteConfig c = good();
  c.pollIntervalMs = 10;
  TEST_ASSERT_FALSE(siteConfigValid(c));
}

static void test_bad_night_hour_is_rejected() {
  SiteConfig c = good();
  c.nightEndHour = 25;
  TEST_ASSERT_FALSE(siteConfigValid(c));
}

static void test_a_southern_hemisphere_site_is_fine() {
  // Validation must reject the broken, not the unusual.
  SiteConfig c = good();
  c.homeLat = -33.9f;
  c.homeLon = 151.2f;
  TEST_ASSERT_TRUE(siteConfigValid(c));
}

static void test_empty_optional_fields_are_fine() {
  // No METAR and no geography URL is a valid site: both features are optional.
  SiteConfig c = good();
  c.metarUrl[0] = '\0';
  c.geoUrl[0] = '\0';
  TEST_ASSERT_TRUE(siteConfigValid(c));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_a_plausible_config_is_valid);
  RUN_TEST(test_set_str_copies);
  RUN_TEST(test_set_str_fills_exactly);
  RUN_TEST(test_set_str_refuses_rather_than_truncating);
  RUN_TEST(test_set_str_null_clears);
  RUN_TEST(test_missing_ssid_is_invalid);
  RUN_TEST(test_missing_receiver_is_invalid);
  RUN_TEST(test_home_at_null_island_is_rejected);
  RUN_TEST(test_out_of_range_home_is_rejected);
  RUN_TEST(test_absurd_poll_interval_is_rejected);
  RUN_TEST(test_bad_night_hour_is_rejected);
  RUN_TEST(test_a_southern_hemisphere_site_is_fine);
  RUN_TEST(test_empty_optional_fields_are_fine);
  return UNITY_END();
}
