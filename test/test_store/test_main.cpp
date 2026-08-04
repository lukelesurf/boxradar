#include <unity.h>
#include <string.h>
#include "aircraft.h"

using namespace radar;

static Aircraft mk(uint32_t hex, float range, float lat = 51.0f, float lon = 0.0f) {
  Aircraft a;
  memset(&a, 0, sizeof(a));
  a.hex = hex;
  a.range = range;
  a.lat = lat;
  a.lon = lon;
  return a;
}

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
  Aircraft a = mk(42, 5.0f, 51.10f, 0.10f);
  a.trail[0] = {51.08f, 0.08f};
  a.trail[1] = {51.09f, 0.09f};
  a.trailLen = 2;
  a.trailHead = 2;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.1f, 51.11f, 0.11f)); // moved
  next.insertByRange(mk(7, 2.0f, 51.01f, 0.01f));  // new aircraft
  next.inheritTrails(prev);

  const Aircraft *c = next.findByHex(42);
  TEST_ASSERT_NOT_NULL(c);
  TEST_ASSERT_EQUAL_UINT8(3, c->trailLen); // 2 inherited + current pos
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 51.11f, c->trail[2].lat);
  const Aircraft *n = next.findByHex(7);
  TEST_ASSERT_EQUAL_UINT8(1, n->trailLen); // first sighting seeds trail
}

static void test_trail_not_duplicated_when_stationary() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 51.10f, 0.10f);
  a.trail[0] = {51.10f, 0.10f};
  a.trailLen = 1;
  a.trailHead = 1;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 51.10f, 0.10f)); // same position
  next.inheritTrails(prev);
  TEST_ASSERT_EQUAL_UINT8(1, next.findByHex(42)->trailLen);
}

static void test_trail_ring_wraps_at_capacity() {
  AircraftStore prev;
  prev.clear();
  Aircraft a = mk(42, 5.0f, 51.0f, 0.0f);
  for (int i = 0; i < TRAIL_LEN; i++) a.trail[i] = {50.0f + i, 0.0f};
  a.trailLen = TRAIL_LEN;
  a.trailHead = 0;
  prev.insertByRange(a);

  AircraftStore next;
  next.clear();
  next.insertByRange(mk(42, 5.0f, 51.99f, 0.5f));
  next.inheritTrails(prev);
  const Aircraft *c = next.findByHex(42);
  TEST_ASSERT_EQUAL_UINT8(TRAIL_LEN, c->trailLen); // still capped
  TEST_ASSERT_FLOAT_WITHIN(1e-4f, 51.99f, c->trail[0].lat); // overwrote oldest
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_insert_keeps_sorted_by_range);
  RUN_TEST(test_cap_drops_farthest);
  RUN_TEST(test_trails_carried_and_appended);
  RUN_TEST(test_trail_not_duplicated_when_stationary);
  RUN_TEST(test_trail_ring_wraps_at_capacity);
  return UNITY_END();
}
