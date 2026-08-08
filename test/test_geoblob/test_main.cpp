#include <unity.h>
#include <string.h>
#include "geoblob.h"
#include "fixture_blob.h"

using namespace radar;

static const float HOME_LAT = 51.8850f;
static const float HOME_LON = 0.2350f;

static void test_opens_a_good_blob() {
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_OK, b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON));
  TEST_ASSERT_TRUE(b.valid());
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, HOME_LAT, b.homeLat());
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, HOME_LON, b.homeLon());
}

static void test_rejects_bad_magic() {
  uint8_t copy[16];
  memcpy(copy, FIXTURE, sizeof(copy));
  copy[0] = 'X';
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_BAD_MAGIC,
                    b.open(copy, sizeof(copy), HOME_LAT, HOME_LON));
  TEST_ASSERT_FALSE(b.valid());
}

static void test_rejects_truncation() {
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_TRUNCATED,
                    b.open(FIXTURE, FIXTURE_LEN - 8, HOME_LAT, HOME_LON));
}

static void test_rejects_a_blob_for_the_wrong_area() {
  // The documented trap: "Regenerate after moving, or it will keep drawing
  // the previous area's coast." A visible refusal beats a silent wrong map.
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_WRONG_HOME,
                    b.open(FIXTURE, FIXTURE_LEN, 55.0f, -3.0f));
}

static void test_record_counts() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL_UINT16(2, b.recordCount(GEO_AIRSPACE));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_COASTLINE));
  TEST_ASSERT_EQUAL_UINT16(2, b.recordCount(GEO_AIRFIELDS));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_RUNWAYS));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_WAYPOINTS));
  TEST_ASSERT_EQUAL_UINT16(1, b.recordCount(GEO_TOWNS));
}

static void test_missing_section_has_no_records() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_EQUAL_UINT16(0, b.recordCount((GeoKind)99));
}

static void test_unopened_blob_yields_nothing() {
  GeoBlob b;
  TEST_ASSERT_FALSE(b.valid());
  TEST_ASSERT_EQUAL_UINT16(0, b.recordCount(GEO_AIRSPACE));
  TEST_ASSERT_NULL(b.runways());
}

static void test_polyline_vertices() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  TEST_ASSERT_TRUE(b.polyline(GEO_AIRSPACE, 0, line));
  TEST_ASSERT_EQUAL_UINT16(4, line.count);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.86523f, line.pts[0].lat);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.02170f, line.pts[0].lon);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.90447f, line.pts[2].lat);
}

static void test_second_polyline_is_reachable() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  TEST_ASSERT_TRUE(b.polyline(GEO_AIRSPACE, 1, line));
  TEST_ASSERT_EQUAL_UINT16(3, line.count);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.75222f, line.pts[0].lat);
}

static void test_polyline_index_out_of_range() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  TEST_ASSERT_FALSE(b.polyline(GEO_AIRSPACE, 2, line));
}

static void test_vertex_pointers_are_4_byte_aligned() {
  // If this fails the format is broken, not the test: an unaligned 32-bit
  // load can fault or silently misread on the ESP32.
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  GeoPolyline line;
  for (uint16_t i = 0; i < b.recordCount(GEO_AIRSPACE); i++) {
    TEST_ASSERT_TRUE(b.polyline(GEO_AIRSPACE, i, line));
    TEST_ASSERT_EQUAL_UINT32(0, ((uintptr_t)line.pts) % 4);
  }
  for (uint16_t i = 0; i < b.recordCount(GEO_COASTLINE); i++) {
    TEST_ASSERT_TRUE(b.polyline(GEO_COASTLINE, i, line));
    TEST_ASSERT_EQUAL_UINT32(0, ((uintptr_t)line.pts) % 4);
  }
}

static void test_named_points() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  const GeoNamedPoint *fields = b.namedPoints(GEO_AIRFIELDS);
  TEST_ASSERT_NOT_NULL(fields);
  TEST_ASSERT_EQUAL_STRING("EGSS", fields[0].name);
  TEST_ASSERT_EQUAL_STRING("EGGW", fields[1].name);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.885f, fields[0].lat);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, -0.368f, fields[1].lon);
}

static void test_named_points_rejects_a_non_point_kind() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  TEST_ASSERT_NULL(b.namedPoints(GEO_AIRSPACE));
  TEST_ASSERT_NULL(b.namedPoints(GEO_RUNWAYS));
}

static void test_names_are_nul_terminated_even_at_full_length() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  const GeoNamedPoint *fixes = b.namedPoints(GEO_WAYPOINTS);
  TEST_ASSERT_EQUAL_STRING("LOREL", fixes[0].name);
  TEST_ASSERT_EQUAL_CHAR('\0', fixes[0].name[7]);
}

static void test_runways() {
  GeoBlob b;
  b.open(FIXTURE, FIXTURE_LEN, HOME_LAT, HOME_LON);
  const GeoRunway *r = b.runways();
  TEST_ASSERT_NOT_NULL(r);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 51.8795f, r[0].lat0);
  TEST_ASSERT_FLOAT_WITHIN(0.0001f, 0.2493f, r[0].lon1);
}

static void test_crc_catches_a_flipped_payload_byte() {
  // The reader's CRC must agree with Python's zlib.crc32 or it would reject
  // every real blob. The fixture is produced BY that writer, so a mismatched
  // implementation shows up as test_opens_a_good_blob failing; this asserts
  // the other direction, that corruption is actually detected.
  static uint8_t copy[FIXTURE_LEN];
  memcpy(copy, FIXTURE, FIXTURE_LEN);
  copy[FIXTURE_LEN - 4] ^= 0xFF;
  GeoBlob b;
  TEST_ASSERT_EQUAL(GEO_BAD_CRC,
                    b.open(copy, FIXTURE_LEN, HOME_LAT, HOME_LON));
}

static void test_status_names_are_distinct() {
  TEST_ASSERT_EQUAL_STRING("ok", geoStatusName(GEO_OK));
  TEST_ASSERT_NOT_EQUAL(0, strcmp(geoStatusName(GEO_BAD_CRC),
                                  geoStatusName(GEO_WRONG_HOME)));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_opens_a_good_blob);
  RUN_TEST(test_rejects_bad_magic);
  RUN_TEST(test_rejects_truncation);
  RUN_TEST(test_rejects_a_blob_for_the_wrong_area);
  RUN_TEST(test_record_counts);
  RUN_TEST(test_missing_section_has_no_records);
  RUN_TEST(test_unopened_blob_yields_nothing);
  RUN_TEST(test_polyline_vertices);
  RUN_TEST(test_second_polyline_is_reachable);
  RUN_TEST(test_polyline_index_out_of_range);
  RUN_TEST(test_vertex_pointers_are_4_byte_aligned);
  RUN_TEST(test_named_points);
  RUN_TEST(test_named_points_rejects_a_non_point_kind);
  RUN_TEST(test_names_are_nul_terminated_even_at_full_length);
  RUN_TEST(test_runways);
  RUN_TEST(test_crc_catches_a_flipped_payload_byte);
  RUN_TEST(test_status_names_are_distinct);
  return UNITY_END();
}
