#include <unity.h>
#include <ArduinoJson.h>
#include "parse.h"

using namespace radar;

// Home for tests: 51.5, -0.1
// 4ca1d2: ~9.6 NM out. 406b9e: ~30 NM out, on ground.
// aabbcc: no position -> skipped. badcaf: seen 70s -> skipped.
static const char SAMPLE[] = R"({
  "now": 1722787200.0,
  "messages": 1234567,
  "aircraft": [
    {"hex":"4ca1d2","flight":"RYR12QD ","t":"B738","lat":51.6,"lon":-0.3,
     "alt_baro":12000,"gs":320.5,"track":270.3,"seen":0.2,"rssi":-12.3,
     "category":"A3","nav_qnh":1013.6,"version":2},
    {"hex":"406b9e","lat":51.9,"lon":0.4,"alt_baro":"ground","seen":1.0,"rssi":-30.1},
    {"hex":"aabbcc","flight":"NOPOS","seen":5.0},
    {"hex":"badcaf","lat":50.0,"lon":-3.0,"alt_baro":35000,"seen":70.0}
  ]})";

static void parseSample(JsonDocument &doc, bool filtered) {
  if (filtered) {
    JsonDocument filter;
    buildAircraftFilter(filter);
    TEST_ASSERT_FALSE(
        deserializeJson(doc, SAMPLE, DeserializationOption::Filter(filter)));
  } else {
    TEST_ASSERT_FALSE(deserializeJson(doc, SAMPLE));
  }
}

static void test_loads_positioned_recent_aircraft_nearest_first() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore dst, prev;
  prev.clear();
  int n = loadStore(doc, dst, prev, 51.5f, -0.1f);
  TEST_ASSERT_EQUAL(2, n);
  TEST_ASSERT_EQUAL_UINT32(0x4ca1d2, dst.list[0].hex); // nearer
  TEST_ASSERT_EQUAL_UINT32(0x406b9e, dst.list[1].hex);
}

static void test_field_extraction() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore dst, prev;
  prev.clear();
  loadStore(doc, dst, prev, 51.5f, -0.1f);
  const Aircraft &a = dst.list[0];
  TEST_ASSERT_EQUAL_STRING("RYR12QD", a.callsign); // trailing space trimmed
  TEST_ASSERT_EQUAL_STRING("B738", a.type);
  TEST_ASSERT_EQUAL_INT32(12000, a.altFt);
  TEST_ASSERT_FALSE(a.onGround);
  TEST_ASSERT_EQUAL_UINT16(320, a.gsKt);
  TEST_ASSERT_EQUAL_UINT16(270, a.trackDeg);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, -12.3f, a.rssi);
  TEST_ASSERT_FLOAT_WITHIN(0.5f, 9.6f, a.range);
}

static void test_ground_altitude_and_missing_fields() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore dst, prev;
  prev.clear();
  loadStore(doc, dst, prev, 51.5f, -0.1f);
  const Aircraft *g = dst.findByHex(0x406b9e);
  TEST_ASSERT_NOT_NULL(g);
  TEST_ASSERT_TRUE(g->onGround);
  TEST_ASSERT_EQUAL_INT32(0, g->altFt);
  TEST_ASSERT_EQUAL_STRING("", g->callsign); // missing flight -> empty
  TEST_ASSERT_EQUAL_UINT16(0, g->gsKt);
}

static void test_filter_strips_unwanted_fields() {
  JsonDocument doc;
  parseSample(doc, true);
  JsonObjectConst first = doc["aircraft"][0];
  TEST_ASSERT_FALSE(first["category"].is<const char *>());
  TEST_ASSERT_FALSE(first["nav_qnh"].is<float>());
  TEST_ASSERT_TRUE(first["hex"].is<const char *>());
}

static void test_trails_flow_through_loadStore() {
  JsonDocument doc;
  parseSample(doc, true);
  AircraftStore prev;
  prev.clear();
  {
    AircraftStore tmp;
    loadStore(doc, tmp, prev, 51.5f, -0.1f); // trailLen becomes 1 each
    prev = tmp;
  }
  AircraftStore dst;
  int n = loadStore(doc, dst, prev, 51.5f, -0.1f); // same positions again
  TEST_ASSERT_EQUAL(2, n);
  TEST_ASSERT_EQUAL_UINT8(1, dst.list[0].trailLen); // stationary: no dup
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_loads_positioned_recent_aircraft_nearest_first);
  RUN_TEST(test_field_extraction);
  RUN_TEST(test_ground_altitude_and_missing_fields);
  RUN_TEST(test_filter_strips_unwanted_fields);
  RUN_TEST(test_trails_flow_through_loadStore);
  return UNITY_END();
}
