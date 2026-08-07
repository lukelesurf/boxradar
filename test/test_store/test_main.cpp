#include <unity.h>
#include <string.h>
#include "aircraft.h"

using namespace radar;

// Trails work in the NM east/north frame, so positions here are NM offsets
// from home rather than lat/lon.
static Aircraft mk(uint32_t hex, float range, float px = 0.0f,
                   float py = 0.0f) {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = hex;
  a.range = range;
  a.pos = {px, py};
  return a;
}

static constexpr float SPACING = 0.5f; // NM between trail dots

static void test_insert_keeps_sorted_by_range() {
  AircraftStore s;
  s.clear();
  s.insertByRange(mk(1, 30.0f));
  s.insertByRange(mk(2, 10.0f));
  s.insertByRange(mk(3, 20.0f));
  TEST_ASSERT_EQUAL(3, s.count);
  TEST_ASSERT_EQUAL_UINT32(2, s.list[0].hex);
  TEST_ASSERT_EQUAL_UINT32(3, s.list[1].hex);
  TEST_ASSERT_EQUAL_UINT32(1, s.list[2].hex);
}

static void test_cap_drops_farthest() {
  AircraftStore s;
  s.clear();
  for (int i = 0; i < MAX_AIRCRAFT; i++) s.insertByRange(mk(100 + i, 50.0f + i));
  TEST_ASSERT_EQUAL(MAX_AIRCRAFT, s.count);
  s.insertByRange(mk(999, 1.0f)); // nearer than all: displaces the farthest
  TEST_ASSERT_EQUAL(MAX_AIRCRAFT, s.count);
  TEST_ASSERT_EQUAL_UINT32(999, s.list[0].hex);
  TEST_ASSERT_NULL(s.findByHex(100 + MAX_AIRCRAFT - 1));
  s.insertByRange(mk(888, 500.0f)); // farther than all: rejected
  TEST_ASSERT_NULL(s.findByHex(888));
}

static void test_trails_carried_and_appended() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 1.0f, 0.0f);
  a.trail[0] = {0.0f, 0.0f};
  a.trail[1] = {0.5f, 0.0f};
  a.trailLen = 2;
  a.trailHead = 2;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.1f, 1.5f, 0.0f)); // moved a full spacing
  next.insertByRange(mk(7, 2.0f, 3.0f, 3.0f));  // new aircraft
  next.inheritTrails(prev, SPACING);

  const Aircraft *c = next.findByHex(42);
  TEST_ASSERT_NOT_NULL(c);
  TEST_ASSERT_EQUAL_UINT8(3, c->trailLen); // 2 inherited + current pos
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 1.5f, c->trail[2].x);
  const Aircraft *n = next.findByHex(7);
  TEST_ASSERT_EQUAL_UINT8(1, n->trailLen); // first sighting seeds trail
}

static void test_trail_not_duplicated_when_stationary() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 1.0f, 0.0f);
  a.trail[0] = {1.0f, 0.0f};
  a.trailLen = 1;
  a.trailHead = 1;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 1.0f, 0.0f)); // same position
  next.inheritTrails(prev, SPACING);
  TEST_ASSERT_EQUAL_UINT8(1, next.findByHex(42)->trailLen);
}

// The point of distance gating: a slow aircraft must not lay down a dot on
// every poll, or its trail bunches into a blob a few pixels across.
static void test_slow_movement_below_spacing_does_not_append() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 1.0f, 0.0f);
  a.trail[0] = {1.0f, 0.0f};
  a.trailLen = 1;
  a.trailHead = 1;
  prev.insertByRange(a);

  // Three polls, each moving well under SPACING: still one point.
  AircraftStore cur = prev;
  for (int i = 1; i <= 3; i++) {
    AircraftStore next;
    next.clear();
    next.insertByRange(mk(42, 5.0f, 1.0f + 0.1f * i, 0.0f));
    next.inheritTrails(cur, SPACING);
    TEST_ASSERT_EQUAL_UINT8(1, next.findByHex(42)->trailLen);
    cur = next;
  }
  // Crossing the threshold finally appends.
  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 1.6f, 0.0f)); // 0.6nm from the last dot
  next.inheritTrails(cur, SPACING);
  TEST_ASSERT_EQUAL_UINT8(2, next.findByHex(42)->trailLen);
}

// Distance is euclidean, not per-axis: diagonal travel counts.
static void test_spacing_measured_diagonally() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 0.0f, 0.0f);
  a.trail[0] = {0.0f, 0.0f};
  a.trailLen = 1;
  a.trailHead = 1;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  // 0.4 east + 0.4 north = 0.566nm, over SPACING although neither axis is.
  next.insertByRange(mk(42, 5.0f, 0.4f, 0.4f));
  next.inheritTrails(prev, SPACING);
  TEST_ASSERT_EQUAL_UINT8(2, next.findByHex(42)->trailLen);
}

static void test_trail_ring_wraps_at_capacity() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 0.0f, 0.0f);
  for (int i = 0; i < TRAIL_LEN; i++) a.trail[i] = {(float)i, 0.0f};
  a.trailLen = TRAIL_LEN;
  a.trailHead = 0;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 99.0f, 0.0f));
  next.inheritTrails(prev, SPACING);
  const Aircraft *c = next.findByHex(42);
  TEST_ASSERT_EQUAL_UINT8(TRAIL_LEN, c->trailLen);      // still capped
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 99.0f, c->trail[0].x); // overwrote oldest
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_insert_keeps_sorted_by_range);
  RUN_TEST(test_cap_drops_farthest);
  RUN_TEST(test_trails_carried_and_appended);
  RUN_TEST(test_trail_not_duplicated_when_stationary);
  RUN_TEST(test_slow_movement_below_spacing_does_not_append);
  RUN_TEST(test_spacing_measured_diagonally);
  RUN_TEST(test_trail_ring_wraps_at_capacity);
  return UNITY_END();
}
