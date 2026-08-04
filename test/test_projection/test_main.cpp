#include <unity.h>
#include "projection.h"

using namespace radar;

static void test_north_offset_is_pure_y() {
  Vec2 v = project(51.5f, -0.1f, 52.5f, -0.1f); // 1 deg north
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, v.x);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 60.0f, v.y); // 60 NM per deg lat
}

static void test_east_offset_scaled_by_cos_lat() {
  Vec2 v = project(60.0f, 0.0f, 60.0f, 1.0f); // 1 deg east at 60N
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 30.0f, v.x); // cos(60) = 0.5
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, v.y);
}

static void test_range_is_euclidean() {
  TEST_ASSERT_FLOAT_WITHIN(0.001f, 5.0f, rangeNm({3.0f, 4.0f}));
}

static void test_bearing_quadrants() {
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 0.0f, bearingDeg({0.0f, 1.0f}));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 45.0f, bearingDeg({1.0f, 1.0f}));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 90.0f, bearingDeg({1.0f, 0.0f}));
  TEST_ASSERT_FLOAT_WITHIN(0.1f, 270.0f, bearingDeg({-1.0f, 0.0f}));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_north_offset_is_pure_y);
  RUN_TEST(test_east_offset_scaled_by_cos_lat);
  RUN_TEST(test_range_is_euclidean);
  RUN_TEST(test_bearing_quadrants);
  return UNITY_END();
}
