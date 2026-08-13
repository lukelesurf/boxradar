#include <unity.h>
#include "hold_gesture.h"

using namespace radar;

static const uint32_t HINT = 500, FIRE = 3000;

static HoldGesture fresh() { return HoldGesture(HINT, FIRE); }

// ------------------------------------------------------- ordinary taps

static void test_nothing_pressed_is_idle() {
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(0));
}

static void test_a_brief_tap_never_hints() {
  // The whole point of the hint threshold: a normal tap must not flash a
  // countdown at you.
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(1));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(120));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(499));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(0));  // released: not a cancel
}

// ------------------------------------------------------------- hinting

static void test_hinting_starts_at_the_threshold() {
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(499));
  TEST_ASSERT_EQUAL(HOLD_HINTING, g.update(500));
  TEST_ASSERT_EQUAL(HOLD_HINTING, g.update(1500));
}

static void test_releasing_after_a_hint_is_a_cancel() {
  // The caller undoes the press edge's tap action on this, so it has to be
  // distinguishable from an ordinary release.
  HoldGesture g = fresh();
  g.update(800);
  TEST_ASSERT_EQUAL(HOLD_CANCELLED, g.update(0));
}

static void test_a_cancel_is_reported_once_only() {
  HoldGesture g = fresh();
  g.update(800);
  TEST_ASSERT_EQUAL(HOLD_CANCELLED, g.update(0));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(0));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(0));
}

// -------------------------------------------------------------- firing

static void test_firing_at_the_threshold() {
  HoldGesture g = fresh();
  g.update(1000);
  TEST_ASSERT_EQUAL(HOLD_HINTING, g.update(2999));
  TEST_ASSERT_EQUAL(HOLD_FIRED, g.update(3000));
}

static void test_it_fires_only_once_per_press() {
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL(HOLD_FIRED, g.update(3000));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(3100));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(9000));
}

static void test_releasing_after_firing_is_not_a_cancel() {
  // It already fired; undoing the view at that point would be wrong, and the
  // board is restarting anyway.
  HoldGesture g = fresh();
  g.update(3000);
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(0));
}

static void test_a_second_press_can_fire_again() {
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL(HOLD_FIRED, g.update(3000));
  TEST_ASSERT_EQUAL(HOLD_IDLE, g.update(0));
  TEST_ASSERT_EQUAL(HOLD_FIRED, g.update(3000));
}

static void test_a_press_that_jumps_straight_past_the_threshold_fires() {
  // Frames are ~100ms, but a stalled frame must not swallow the gesture.
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL(HOLD_FIRED, g.update(60000));
}

// ------------------------------------------------------------ progress

static void test_progress_is_zero_below_the_hint() {
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL_FLOAT(0.0f, g.progress(0));
  TEST_ASSERT_EQUAL_FLOAT(0.0f, g.progress(499));
}

static void test_progress_spans_hint_to_fire() {
  HoldGesture g = fresh();
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.5f, g.progress(1750));
  TEST_ASSERT_EQUAL_FLOAT(1.0f, g.progress(3000));
}

static void test_progress_is_clamped_past_the_end() {
  HoldGesture g = fresh();
  TEST_ASSERT_EQUAL_FLOAT(1.0f, g.progress(99999));
}

static void test_a_degenerate_window_does_not_divide_by_zero() {
  HoldGesture g(500, 500);
  TEST_ASSERT_EQUAL_FLOAT(0.0f, g.progress(500));
  TEST_ASSERT_EQUAL_FLOAT(0.0f, g.progress(9000));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_nothing_pressed_is_idle);
  RUN_TEST(test_a_brief_tap_never_hints);
  RUN_TEST(test_hinting_starts_at_the_threshold);
  RUN_TEST(test_releasing_after_a_hint_is_a_cancel);
  RUN_TEST(test_a_cancel_is_reported_once_only);
  RUN_TEST(test_firing_at_the_threshold);
  RUN_TEST(test_it_fires_only_once_per_press);
  RUN_TEST(test_releasing_after_firing_is_not_a_cancel);
  RUN_TEST(test_a_second_press_can_fire_again);
  RUN_TEST(test_a_press_that_jumps_straight_past_the_threshold_fires);
  RUN_TEST(test_progress_is_zero_below_the_hint);
  RUN_TEST(test_progress_spans_hint_to_fire);
  RUN_TEST(test_progress_is_clamped_past_the_end);
  RUN_TEST(test_a_degenerate_window_does_not_divide_by_zero);
  return UNITY_END();
}
