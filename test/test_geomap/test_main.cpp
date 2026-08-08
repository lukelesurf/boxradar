#include <unity.h>
#include <string.h>
#include "geomap.h"
#include "../test_geoblob/fixture_blob.h"

using namespace radar;

static const float HOME_LAT = 51.8850f;
static const float HOME_LON = 0.2350f;

static void test_opens() {
  GeoMap m;
  TEST_ASSERT_EQUAL(GEO_OK, m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON));
}

static void test_rejects_wrong_home() {
  GeoMap m;
  TEST_ASSERT_EQUAL(GEO_WRONG_HOME,
                    m.open(FIXTURE, FIXTURE_LEN, 55.0f, -3.0f));
}

static void test_counts_match_the_fixture() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL_UINT16(2, m.airspaceCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.coastCount());
  TEST_ASSERT_EQUAL_UINT16(2, m.airfieldCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.runwayCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.waypointCount());
  TEST_ASSERT_EQUAL_UINT16(1, m.townCount());
  TEST_ASSERT_EQUAL_UINT16(0, m.coastDropped());
}

static void test_airspace_vertices() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  TEST_ASSERT_TRUE(m.airspace(0, line));
  TEST_ASSERT_EQUAL_UINT16(4, line.count);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.86523f, line.pts[0].lat);
}

static void test_coast_box_is_computed_from_the_points() {
  // The blob does not store bboxes: a stored one could disagree with its own
  // points, and the symptom is a coastline that silently fails to draw.
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  GeoBox box;
  TEST_ASSERT_TRUE(m.coast(0, line, box));
  TEST_ASSERT_EQUAL_UINT16(3, line.count);
  float minLat = line.pts[0].lat, maxLat = line.pts[0].lat;
  float minLon = line.pts[0].lon, maxLon = line.pts[0].lon;
  for (uint16_t i = 1; i < line.count; i++) {
    if (line.pts[i].lat < minLat) minLat = line.pts[i].lat;
    if (line.pts[i].lat > maxLat) maxLat = line.pts[i].lat;
    if (line.pts[i].lon < minLon) minLon = line.pts[i].lon;
    if (line.pts[i].lon > maxLon) maxLon = line.pts[i].lon;
  }
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, minLat, box.minLat);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, maxLat, box.maxLat);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, minLon, box.minLon);
  TEST_ASSERT_FLOAT_WITHIN(0.00001f, maxLon, box.maxLon);
}

static void test_named_points() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL_STRING("EGSS", m.airfields()[0].name);
  TEST_ASSERT_EQUAL_STRING("LOREL", m.waypoints()[0].name);
  TEST_ASSERT_EQUAL_STRING("STVG", m.towns()[0].name);
}

static void test_runways() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.8795f, m.runways()[0].lat0);
}

static void test_unopened_map_is_empty_not_crashy() {
  GeoMap m;
  GeoPolyline line;
  GeoBox box;
  TEST_ASSERT_EQUAL_UINT16(0, m.airspaceCount());
  TEST_ASSERT_EQUAL_UINT16(0, m.coastCount());
  TEST_ASSERT_FALSE(m.airspace(0, line));
  TEST_ASSERT_FALSE(m.coast(0, line, box));
  TEST_ASSERT_NULL(m.airfields());
}

static void test_reopening_resets_state() {
  // A refetch must not leave stale boxes behind.
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL(GEO_BAD_MAGIC, m.open((const uint8_t *)"XXXXXXXXXXXXXXXX",
                                          16, HOME_LAT, HOME_LON));
  TEST_ASSERT_EQUAL_UINT16(0, m.coastCount());
  TEST_ASSERT_EQUAL_UINT16(0, m.airspaceCount());
}

static void test_out_of_range_indices_are_refused() {
  GeoMap m;
  m.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  GeoBox box;
  TEST_ASSERT_FALSE(m.airspace(2, line));
  TEST_ASSERT_FALSE(m.coast(1, line, box));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_opens);
  RUN_TEST(test_rejects_wrong_home);
  RUN_TEST(test_counts_match_the_fixture);
  RUN_TEST(test_airspace_vertices);
  RUN_TEST(test_coast_box_is_computed_from_the_points);
  RUN_TEST(test_named_points);
  RUN_TEST(test_runways);
  RUN_TEST(test_unopened_map_is_empty_not_crashy);
  RUN_TEST(test_reopening_resets_state);
  RUN_TEST(test_out_of_range_indices_are_refused);
  return UNITY_END();
}
