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


// The hoisted form must agree exactly with the single-shot one, or the
// coastline would render offset from everything else on the scope.
static void test_project_with_matches_project() {
  const float H_LAT = 51.9f, H_LON = 0.03f;
  const float scale = lonScaleNm(H_LAT);
  const float pts[][2] = {{51.9f, 0.03f}, {52.4f, -0.9f},
                          {51.2f, 1.4f}, {50.5f, 0.0f}};
  for (auto &pt : pts) {
    Vec2 a = project(H_LAT, H_LON, pt[0], pt[1]);
    Vec2 b = projectWith(scale, H_LAT, H_LON, pt[0], pt[1]);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, a.x, b.x);
    TEST_ASSERT_FLOAT_WITHIN(1e-5f, a.y, b.y);
  }
}

static void test_lon_scale_shrinks_with_latitude() {
  // 60nm per degree at the equator, shrinking toward the pole.
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 60.0f, lonScaleNm(0.0f));
  TEST_ASSERT_TRUE(lonScaleNm(51.9f) < lonScaleNm(0.0f));
  TEST_ASSERT_FLOAT_WITHIN(0.5f, 37.1f, lonScaleNm(51.9f));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_north_offset_is_pure_y);
  RUN_TEST(test_east_offset_scaled_by_cos_lat);
  RUN_TEST(test_range_is_euclidean);
  RUN_TEST(test_bearing_quadrants);
  RUN_TEST(test_project_with_matches_project);
  RUN_TEST(test_lon_scale_shrinks_with_latitude);
  return UNITY_END();
}
