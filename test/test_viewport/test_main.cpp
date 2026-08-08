#include <unity.h>
#include "ui/viewport.h"

// The transform is the one part of the viewport work that fails silently: a
// sign or centre-offset error draws a plausible-looking scope of the wrong
// place, and there is no way to tell by looking at the panel.

static void test_home_centred_view_puts_home_at_screen_centre() {
  UiState ui; // defaults: detail on home
  radar::AircraftStore s;
  Viewport vp = viewportFor(ui, s);
  TEST_ASSERT_EQUAL_INT(SCOPE_CX, vp.sx(0.0f));
  TEST_ASSERT_EQUAL_INT(SCOPE_CY, vp.sy(0.0f));
  TEST_ASSERT_TRUE(vp.homeCentred());
}

static void test_north_is_up_and_east_is_right() {
  UiState ui;
  radar::AircraftStore s;
  Viewport vp = viewportFor(ui, s);
  TEST_ASSERT_TRUE(vp.sx(1.0f) > SCOPE_CX); // 1nm east
  TEST_ASSERT_TRUE(vp.sy(1.0f) < SCOPE_CY); // 1nm north: screen y decreases
}

static void test_offset_centre_puts_that_point_at_screen_centre() {
  UiState ui;
  ui.detailCentre = {7.6f, -3.2f}; // roughly Stansted
  radar::AircraftStore s;
  Viewport vp = viewportFor(ui, s);
  TEST_ASSERT_EQUAL_INT(SCOPE_CX, vp.sx(7.6f));
  TEST_ASSERT_EQUAL_INT(SCOPE_CY, vp.sy(-3.2f));
  TEST_ASSERT_FALSE(vp.homeCentred()); // so the range rings are suppressed
}

// The interaction that matters: a tap on the overview must become a detail
// view centred on whatever was under the finger.
static void test_overview_tap_round_trips_to_detail_centre() {
  UiState ui;
  ui.view = ViewState::OVERVIEW;
  radar::AircraftStore s;
  Viewport over = viewportFor(ui, s);

  const int tapX = 210, tapY = 70;
  ui.detailCentre = over.toNm(tapX, tapY);
  ui.view = ViewState::DETAIL;
  Viewport det = viewportFor(ui, s);

  TEST_ASSERT_EQUAL_INT(SCOPE_CX, det.sx(ui.detailCentre.x));
  TEST_ASSERT_EQUAL_INT(SCOPE_CY, det.sy(ui.detailCentre.y));
  // ...and the same world point was where the finger was in the overview.
  TEST_ASSERT_INT_WITHIN(1, tapX, over.sx(ui.detailCentre.x));
  TEST_ASSERT_INT_WITHIN(1, tapY, over.sy(ui.detailCentre.y));
}

// Without the snap, only a tap on the exact centre pixel produced a
// home-centred detail view — the tolerance in homeCentred() is measured at
// the detail scale while the tap is aimed at the 5x coarser overview scale.
// These pin that down, since it is invisible short of counting pixels on the
// panel and wondering why the range rings never came back.
static void test_tap_on_home_marker_snaps_to_exactly_home() {
  UiState ui;
  ui.view = ViewState::OVERVIEW;
  radar::AircraftStore s;
  Viewport over = viewportFor(ui, s);

  for (int off = 0; off <= HOME_SNAP_PX; off++) {
    ui.detailCentre = detailCentreForTap(over, SCOPE_CX + off, SCOPE_CY);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, ui.detailCentre.x);
    TEST_ASSERT_EQUAL_FLOAT(0.0f, ui.detailCentre.y);
  }
  // ...and the point of it all: the detail view keeps its range rings.
  ui.view = ViewState::DETAIL;
  TEST_ASSERT_TRUE(viewportFor(ui, s).homeCentred());
}

static void test_tap_clear_of_home_is_not_snapped() {
  UiState ui;
  ui.view = ViewState::OVERVIEW;
  radar::AircraftStore s;
  Viewport over = viewportFor(ui, s);

  const int px = SCOPE_CX + HOME_SNAP_PX + 5, py = SCOPE_CY - 40;
  radar::Vec2 c = detailCentreForTap(over, px, py);
  radar::Vec2 raw = over.toNm(px, py);
  TEST_ASSERT_EQUAL_FLOAT(raw.x, c.x);
  TEST_ASSERT_EQUAL_FLOAT(raw.y, c.y);

  ui.detailCentre = c;
  ui.view = ViewState::DETAIL;
  TEST_ASSERT_FALSE(viewportFor(ui, s).homeCentred()); // rings suppressed
}

// The snap is a radius, not a bounding box: a diagonal tap just outside it
// must not be caught.
static void test_snap_region_is_circular() {
  UiState ui;
  ui.view = ViewState::OVERVIEW;
  radar::AircraftStore s;
  Viewport over = viewportFor(ui, s);
  radar::Vec2 c = detailCentreForTap(over, SCOPE_CX + HOME_SNAP_PX,
                                     SCOPE_CY + HOME_SNAP_PX);
  TEST_ASSERT_TRUE(c.x != 0.0f || c.y != 0.0f);
}

static void test_scale_is_height_bound() {
  // Radius in px is fixed; only the NM it represents changes.
  const float usableR = (float)(SCOPE_CY - SCOPE_MARGIN);
  TEST_ASSERT_FLOAT_WITHIN(0.001f, usableR / OVERVIEW_NM,
                           scopePxPerNm(OVERVIEW_NM));
  TEST_ASSERT_FLOAT_WITHIN(0.001f, usableR / 5.0f, scopePxPerNm(5.0f));
}

// Zooming in must shrink the world-space gap so the dots stay ~5px apart.
static void test_trail_spacing_tightens_as_range_shrinks() {
  TEST_ASSERT_TRUE(trailSpacingNm(5.0f) < trailSpacingNm(10.0f));
  TEST_ASSERT_TRUE(trailSpacingNm(10.0f) < trailSpacingNm(OVERVIEW_NM));
}

// The overview is outside the two-line threshold and every detail range is
// inside it — the property the datablock degradation now leans on.
static void test_detail_gets_two_lines_overview_does_not() {
  TEST_ASSERT_TRUE(OVERVIEW_NM > TWO_LINE_MAX_NM);
  for (int i = 0; i < N_DETAIL_RANGES; i++)
    TEST_ASSERT_TRUE(DETAIL_RANGES_NM[i] <= TWO_LINE_MAX_NM);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_home_centred_view_puts_home_at_screen_centre);
  RUN_TEST(test_north_is_up_and_east_is_right);
  RUN_TEST(test_offset_centre_puts_that_point_at_screen_centre);
  RUN_TEST(test_overview_tap_round_trips_to_detail_centre);
  RUN_TEST(test_tap_on_home_marker_snaps_to_exactly_home);
  RUN_TEST(test_tap_clear_of_home_is_not_snapped);
  RUN_TEST(test_snap_region_is_circular);
  RUN_TEST(test_scale_is_height_bound);
  RUN_TEST(test_trail_spacing_tightens_as_range_shrinks);
  RUN_TEST(test_detail_gets_two_lines_overview_does_not);
  return UNITY_END();
}
