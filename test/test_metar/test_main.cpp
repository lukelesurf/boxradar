#include <unity.h>
#include <string.h>
#include <ArduinoJson.h>
#include "metar.h"
#include "format.h"

using namespace radar;

// Shape published by tools/metar-feed on the receiver Pi.
static const char SAMPLE[] = R"({"t":1786139838,"stations":[
  {"id":"EGGW","wdir":70,"wspd":2,"gust":0,"vis":9999,"ceil":0,"cov":"NCD",
   "qnh":1022,"temp":17,"rwy":"07","conf":0,"obs":1786139400},
  {"id":"EGSS","wdir":160,"wspd":12,"gust":24,"vis":3000,"ceil":1200,
   "cov":"BKN","qnh":1022,"temp":19,"rwy":"22","conf":1,"obs":1786139400},
  {"id":"EGLL","wdir":-1,"wspd":3,"gust":0,"vis":9999,"ceil":0,"cov":"FEW",
   "qnh":1013,"temp":15,"rwy":"","conf":0,"obs":1786139400}
]})";

static void load(Metar &m, const char *station, bool expectFound = true) {
  JsonDocument doc;
  TEST_ASSERT_FALSE(deserializeJson(doc, SAMPLE));
  bool ok = loadMetar(doc, station, m);
  TEST_ASSERT_EQUAL(expectFound, ok);
}

static void test_selects_the_requested_station() {
  Metar m;
  load(m, "EGSS");
  TEST_ASSERT_EQUAL_STRING("EGSS", m.station);
  TEST_ASSERT_EQUAL_INT16(160, m.windDir);
  TEST_ASSERT_EQUAL_UINT16(12, m.windKt);
  TEST_ASSERT_EQUAL_UINT16(24, m.gustKt);
  TEST_ASSERT_EQUAL_UINT16(3000, m.visM);
  TEST_ASSERT_EQUAL_UINT16(1200, m.ceilFt);
  TEST_ASSERT_EQUAL_STRING("BKN", m.cover);
  TEST_ASSERT_EQUAL_STRING("22", m.runway);
  TEST_ASSERT_TRUE(m.runwayConfident);
  TEST_ASSERT_TRUE(m.valid);
}

static void test_confidence_flag_is_honoured() {
  Metar m;
  load(m, "EGGW");
  TEST_ASSERT_EQUAL_STRING("07", m.runway);
  TEST_ASSERT_FALSE(m.runwayConfident); // 2kt: wind isn't choosing anything
}

// A publish that omits our station must not blank a good previous reading.
static void test_missing_station_leaves_output_untouched() {
  Metar m;
  memset(&m, 0, sizeof(m));
  strcpy(m.station, "EGSS");
  m.windKt = 42;
  m.valid = true;
  JsonDocument doc;
  TEST_ASSERT_FALSE(deserializeJson(doc, SAMPLE));
  TEST_ASSERT_FALSE(loadMetar(doc, "EGKK", m));
  TEST_ASSERT_EQUAL_STRING("EGSS", m.station);
  TEST_ASSERT_EQUAL_UINT16(42, m.windKt);
}

static void test_variable_wind_direction_is_negative_not_north() {
  Metar m;
  load(m, "EGLL");
  TEST_ASSERT_EQUAL_INT16(-1, m.windDir); // must not read as 000 degrees
  TEST_ASSERT_EQUAL_STRING("", m.runway);
}

static void test_wind_formatting() {
  Metar m;
  memset(&m, 0, sizeof(m));
  char buf[16];

  m.windDir = 160; m.windKt = 5; m.gustKt = 0;
  formatWind(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("160/05", buf);

  m.gustKt = 25;
  formatWind(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("160/05G25", buf);

  m.windDir = -1; m.gustKt = 0; m.windKt = 3;
  formatWind(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("VRB/03", buf);

  m.windKt = 0; m.windDir = 160;
  formatWind(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("CALM", buf); // calm beats a stale direction

  m.windDir = 40; m.windKt = 8;
  formatWind(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("040/08", buf); // zero-padded to 3 digits
}

static void test_cloud_formatting() {
  Metar m;
  memset(&m, 0, sizeof(m));
  char buf[16];

  strcpy(m.cover, "NCD"); m.ceilFt = 0;
  formatCloud(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("NCD", buf);

  strcpy(m.cover, "BKN"); m.ceilFt = 1200;
  formatCloud(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("BKN012", buf);

  strcpy(m.cover, "OVC"); m.ceilFt = 300;
  formatCloud(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("OVC003", buf);

  // Scattered cloud is not a ceiling, so no base is printed even though
  // there is cloud in the sky.
  strcpy(m.cover, "SCT"); m.ceilFt = 0;
  formatCloud(buf, sizeof(buf), m);
  TEST_ASSERT_EQUAL_STRING("SCT", buf);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_selects_the_requested_station);
  RUN_TEST(test_confidence_flag_is_honoured);
  RUN_TEST(test_missing_station_leaves_output_untouched);
  RUN_TEST(test_variable_wind_direction_is_negative_not_north);
  RUN_TEST(test_wind_formatting);
  RUN_TEST(test_cloud_formatting);
  return UNITY_END();
}
