#include <unity.h>
#include <string.h>
#include "contact_feed.h"
#include "fixture_contacts.h"

using namespace radar;

// Home for these tests. One degree of latitude is 60 NM, so a contact offset
// in latitude alone sits at a range that can be checked by hand.
static const float HOME_LAT = 51.5f;
static const float HOME_LON = -0.1f;

// ---------------------------------------------------------------------------
// A writer, so the tests exercise the reader against bytes rather than against
// a mock. Deliberately independent of contact_feed.cpp: if both sides shared a
// layout constant, an offset error would cancel itself out and pass.
// ---------------------------------------------------------------------------

struct Builder {
  // Room for more records than the board will accept: the cap test has to be
  // able to WRITE an oversized payload in order to check that the reader
  // handles one.
  uint8_t buf[CONTACT_HEADER_LEN + (MAX_AIRCRAFT + 16) * CONTACT_RECORD_LEN];
  size_t len;
  uint16_t count;

  void begin(uint16_t total) {
    memset(buf, 0, sizeof(buf));
    memcpy(buf, "BXAC", 4);
    put16(4, CONTACT_VERSION);
    put16(6, CONTACT_RECORD_LEN);
    put16(8, 0);
    put16(10, total);
    len = CONTACT_HEADER_LEN;
    count = 0;
  }

  void put16(size_t off, uint16_t v) { memcpy(buf + off, &v, 2); }
  void put32(size_t off, uint32_t v) { memcpy(buf + off, &v, 4); }

  // Returns the record's base offset so a test can corrupt one field.
  size_t add(uint32_t hex, double lat, double lon) {
    size_t base = len;
    memset(buf + base, 0, CONTACT_RECORD_LEN);
    put32(base + 0, hex);
    int32_t latE7 = (int32_t)(lat * 1e7);
    int32_t lonE7 = (int32_t)(lon * 1e7);
    memcpy(buf + base + 4, &latE7, 4);
    memcpy(buf + base + 8, &lonE7, 4);
    len += CONTACT_RECORD_LEN;
    count++;
    put16(8, count);
    return base;
  }

  void text(size_t base, size_t off, const char *s, size_t width) {
    size_t n = strlen(s);
    if (n > width) n = width;
    memcpy(buf + base + off, s, n);
  }
};

static Builder b;

static AircraftStore dst, prev;

static void reset() {
  dst.clear();
  prev.clear();
  b.begin(0);
}

static ContactStatus load() {
  return loadContacts(b.buf, b.len, dst, prev, HOME_LAT, HOME_LON);
}

// ---------------------------------------------------------------------------

static void test_empty_feed_is_valid() {
  reset();
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL(0, dst.count);
  TEST_ASSERT_EQUAL_UINT16(0, dst.feedTotal);
}

static void test_decodes_one_contact() {
  reset();
  b.begin(1);
  size_t r = b.add(0x4ca1d2, 51.6, -0.3);
  b.text(r, 12, "RYR12QD", 8);
  b.text(r, 20, "B738", 4);
  b.text(r, 24, "7000", 4);
  int16_t alt = 12000 / 25;
  memcpy(b.buf + r + 28, &alt, 2);
  b.put16(r + 30, 320);   // gs
  b.put16(r + 32, 270);   // track
  int16_t vr = (int16_t)(-1088 / 64);
  memcpy(b.buf + r + 34, &vr, 2);
  b.buf[r + 36] = 3;              // seen
  b.buf[r + 37] = (uint8_t)(int8_t)(-25); // rssi x2 -> -12.5 dBm
  b.buf[r + 38] = 0;

  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL(1, dst.count);
  const Aircraft &a = dst.list[0];
  TEST_ASSERT_EQUAL_UINT32(0x4ca1d2, a.hex);
  TEST_ASSERT_EQUAL_STRING("RYR12QD", a.callsign);
  TEST_ASSERT_EQUAL_STRING("B738", a.type);
  TEST_ASSERT_EQUAL_STRING("7000", a.squawk);
  TEST_ASSERT_EQUAL_INT32(12000, a.altFt);
  TEST_ASSERT_EQUAL_UINT16(320, a.gsKt);
  TEST_ASSERT_EQUAL_UINT16(270, a.trackDeg);
  TEST_ASSERT_EQUAL_INT16(-1088, a.vertRateFpm);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, 3.0f, a.seenS);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, -12.5f, a.rssi);
  TEST_ASSERT_FALSE(a.onGround);
  TEST_ASSERT_FALSE(a.isMlat);
}

static void test_full_width_name_fields_are_terminated() {
  // Eight characters exactly fills the wire field, so the NUL can only come
  // from the reader. This is the case a fixed-width format gets wrong.
  reset();
  b.begin(1);
  size_t r = b.add(0x400001, 51.6, -0.1);
  b.text(r, 12, "ABCDEFGH", 8);
  b.text(r, 20, "A21N", 4);
  b.text(r, 24, "0100", 4);
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL_STRING("ABCDEFGH", dst.list[0].callsign);
  TEST_ASSERT_EQUAL_STRING("A21N", dst.list[0].type);
  TEST_ASSERT_EQUAL_STRING("0100", dst.list[0].squawk);
}

static void test_position_is_projected_against_the_boards_own_home() {
  reset();
  b.begin(1);
  b.add(0x400001, 51.6, -0.1); // 0.1 deg north = 6 NM
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 6.0f, dst.list[0].range);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 6.0f, dst.list[0].pos.y);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, dst.list[0].pos.x);
}

static void test_flags_decode() {
  reset();
  b.begin(2);
  size_t r0 = b.add(0x400001, 51.6, -0.1);
  int16_t alt = 400;              // would be 10000 ft
  memcpy(b.buf + r0 + 28, &alt, 2);
  b.buf[r0 + 38] = 0x01;          // on ground
  size_t r1 = b.add(0x400002, 51.7, -0.1);
  b.buf[r1 + 38] = 0x02;          // mlat

  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_TRUE(dst.list[0].onGround);
  TEST_ASSERT_EQUAL_INT32(0, dst.list[0].altFt); // ground overrides altitude
  TEST_ASSERT_FALSE(dst.list[0].isMlat);
  TEST_ASSERT_TRUE(dst.list[1].isMlat);
  TEST_ASSERT_FALSE(dst.list[1].onGround);
}

static void test_store_stays_nearest_first() {
  reset();
  b.begin(3);
  b.add(0x000003, 51.9, -0.1); // 24 NM
  b.add(0x000001, 51.6, -0.1); // 6 NM
  b.add(0x000002, 51.7, -0.1); // 12 NM
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL(3, dst.count);
  TEST_ASSERT_EQUAL_UINT32(0x000001, dst.list[0].hex);
  TEST_ASSERT_EQUAL_UINT32(0x000002, dst.list[1].hex);
  TEST_ASSERT_EQUAL_UINT32(0x000003, dst.list[2].hex);
}

static void test_total_can_exceed_count() {
  reset();
  b.begin(58);
  b.add(0x400001, 51.6, -0.1);
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL(1, dst.count);
  TEST_ASSERT_EQUAL_UINT16(58, dst.feedTotal);
}

static void test_more_records_than_the_store_holds_keeps_the_nearest() {
  reset();
  b.begin(MAX_AIRCRAFT + 8);
  // Farthest first, so a reader that simply appended would keep the wrong set.
  for (int i = MAX_AIRCRAFT + 7; i >= 0; i--)
    b.add(0x500000 + i, 51.5 + (i + 1) * 0.01, -0.1);
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL(MAX_AIRCRAFT, dst.count);
  TEST_ASSERT_EQUAL_UINT32(0x500000, dst.list[0].hex);
  TEST_ASSERT_NULL(dst.findByHex(0x500000 + MAX_AIRCRAFT + 7));
}

static void test_trails_are_inherited_across_polls() {
  reset();
  b.begin(1);
  b.add(0x400001, 51.6, -0.1);
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL_UINT8(1, dst.list[0].trailLen);

  prev = dst;
  b.begin(1);
  b.add(0x400001, 51.7, -0.1); // 6 NM further on
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL_UINT8(2, dst.list[0].trailLen);
}

static void test_rejects_bad_magic() {
  reset();
  b.begin(1);
  b.add(0x400001, 51.6, -0.1);
  b.buf[0] = 'X';
  TEST_ASSERT_EQUAL(CONTACT_BAD_MAGIC, load());
  TEST_ASSERT_EQUAL(0, dst.count);
}

static void test_rejects_unknown_version() {
  reset();
  b.begin(1);
  b.add(0x400001, 51.6, -0.1);
  b.put16(4, CONTACT_VERSION + 1);
  TEST_ASSERT_EQUAL(CONTACT_BAD_VERSION, load());
  TEST_ASSERT_EQUAL(0, dst.count);
}

static void test_rejects_a_record_length_from_another_build() {
  reset();
  b.begin(1);
  b.add(0x400001, 51.6, -0.1);
  b.put16(6, CONTACT_RECORD_LEN + 4);
  TEST_ASSERT_EQUAL(CONTACT_BAD_RECORD_LEN, load());
  TEST_ASSERT_EQUAL(0, dst.count);
}

static void test_rejects_a_short_header() {
  reset();
  b.begin(0);
  b.len = 6;
  TEST_ASSERT_EQUAL(CONTACT_TRUNCATED, load());
}

static void test_rejects_a_payload_shorter_than_its_count_claims() {
  reset();
  b.begin(2);
  b.add(0x400001, 51.6, -0.1);
  b.put16(8, 2); // claims two records, carries one
  TEST_ASSERT_EQUAL(CONTACT_TRUNCATED, load());
  TEST_ASSERT_EQUAL(0, dst.count);
}

static void test_a_rejected_payload_leaves_no_stale_traffic() {
  // The store is cleared before validation, so a board that loses the feed
  // shows nothing rather than a frozen scope it cannot distinguish from live.
  reset();
  b.begin(1);
  b.add(0x400001, 51.6, -0.1);
  TEST_ASSERT_EQUAL(CONTACT_OK, load());
  TEST_ASSERT_EQUAL(1, dst.count);
  b.buf[0] = 'X';
  TEST_ASSERT_EQUAL(CONTACT_BAD_MAGIC, load());
  TEST_ASSERT_EQUAL(0, dst.count);
  TEST_ASSERT_EQUAL_UINT16(0, dst.feedTotal);
}

// ---------------------------------------------------------------------------
// The only test that crosses the implementation boundary. Everything above
// checks the reader against bytes this file wrote; this checks it against
// bytes boxradar_site.contacts wrote. A field at the wrong offset in both
// implementations passes both suites and fails only here.
// ---------------------------------------------------------------------------

static void test_decodes_a_payload_written_by_the_python_writer() {
  const float FIX_LAT = 51.8850f, FIX_LON = 0.2350f;
  dst.clear();
  prev.clear();
  TEST_ASSERT_EQUAL(CONTACT_OK,
                    loadContacts(CONTACT_FIXTURE, CONTACT_FIXTURE_LEN, dst,
                                 prev, FIX_LAT, FIX_LON));

  // Five valid contacts, capped to four by the writer.
  TEST_ASSERT_EQUAL(4, dst.count);
  TEST_ASSERT_EQUAL_UINT16(5, dst.feedTotal);
  TEST_ASSERT_NULL(dst.findByHex(0x3fcafe)); // the farthest, dropped

  // Nearest first, at 1, 2, 6 and 12 NM due north of the fixture's home.
  const Aircraft &near = dst.list[0];
  TEST_ASSERT_EQUAL_UINT32(0x400001, near.hex);
  TEST_ASSERT_EQUAL_STRING("ABCDEFGH", near.callsign); // fills the field
  TEST_ASSERT_EQUAL_STRING("A21N", near.type);
  TEST_ASSERT_EQUAL_STRING("0100", near.squawk); // leading zero survives
  TEST_ASSERT_EQUAL_INT32(2500, near.altFt);
  TEST_ASSERT_EQUAL_UINT16(180, near.gsKt);
  TEST_ASSERT_EQUAL_UINT16(45, near.trackDeg);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 1.0f, near.range);

  const Aircraft &ground = dst.list[1];
  TEST_ASSERT_EQUAL_UINT32(0xa1b2c3, ground.hex); // tilde stripped by writer
  TEST_ASSERT_TRUE(ground.onGround);
  TEST_ASSERT_EQUAL_INT32(0, ground.altFt);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, -5.0f, ground.rssi);

  const Aircraft &jet = dst.list[2];
  TEST_ASSERT_EQUAL_UINT32(0x4ca1d2, jet.hex);
  TEST_ASSERT_EQUAL_STRING("RYR12QD", jet.callsign); // trailing space trimmed
  TEST_ASSERT_EQUAL_INT32(12000, jet.altFt);
  TEST_ASSERT_EQUAL_INT16(-1088, jet.vertRateFpm);
  TEST_ASSERT_EQUAL_UINT16(320, jet.gsKt);
  TEST_ASSERT_EQUAL_UINT16(270, jet.trackDeg);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, -12.5f, jet.rssi);
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 6.0f, jet.range);

  const Aircraft &mlat = dst.list[3];
  TEST_ASSERT_EQUAL_UINT32(0x406b9e, mlat.hex);
  TEST_ASSERT_TRUE(mlat.isMlat);
  TEST_ASSERT_EQUAL_INT16(1024, mlat.vertRateFpm); // geom_rate fallback
  TEST_ASSERT_FLOAT_WITHIN(0.05f, 12.0f, mlat.range);
}

static void test_status_names_are_distinct_and_present() {
  TEST_ASSERT_EQUAL_STRING("ok", contactStatusName(CONTACT_OK));
  TEST_ASSERT_TRUE(strlen(contactStatusName(CONTACT_BAD_MAGIC)) > 0);
  TEST_ASSERT_TRUE(strlen(contactStatusName(CONTACT_TRUNCATED)) > 0);
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_empty_feed_is_valid);
  RUN_TEST(test_decodes_one_contact);
  RUN_TEST(test_full_width_name_fields_are_terminated);
  RUN_TEST(test_position_is_projected_against_the_boards_own_home);
  RUN_TEST(test_flags_decode);
  RUN_TEST(test_store_stays_nearest_first);
  RUN_TEST(test_total_can_exceed_count);
  RUN_TEST(test_more_records_than_the_store_holds_keeps_the_nearest);
  RUN_TEST(test_trails_are_inherited_across_polls);
  RUN_TEST(test_rejects_bad_magic);
  RUN_TEST(test_rejects_unknown_version);
  RUN_TEST(test_rejects_a_record_length_from_another_build);
  RUN_TEST(test_rejects_a_short_header);
  RUN_TEST(test_rejects_a_payload_shorter_than_its_count_claims);
  RUN_TEST(test_a_rejected_payload_leaves_no_stale_traffic);
  RUN_TEST(test_decodes_a_payload_written_by_the_python_writer);
  RUN_TEST(test_status_names_are_distinct_and_present);
  return UNITY_END();
}
