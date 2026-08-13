#include <unity.h>
#include <string.h>
#include "geoblob.h"
#include "geostream.h"

using namespace radar;

// A minimal but genuine blob: header, home, zero sections. Built by hand so
// the validator is tested against the format rather than against the writer.
static uint8_t s_blob[64];
static size_t s_len;

static void putU16(uint8_t *p, uint16_t v) { p[0] = v & 0xFF; p[1] = v >> 8; }
static void putU32(uint8_t *p, uint32_t v) {
  p[0] = v & 0xFF; p[1] = (v >> 8) & 0xFF;
  p[2] = (v >> 16) & 0xFF; p[3] = (v >> 24) & 0xFF;
}
static void putF32(uint8_t *p, float v) { memcpy(p, &v, 4); }

static void build(float lat = 51.8850f, float lon = 0.2350f) {
  memset(s_blob, 0, sizeof(s_blob));
  memcpy(s_blob, "BXRG", 4);
  putU16(s_blob + 4, 1);            // version
  // body: homeLat, homeLon, sectionCount, then 2 bytes of padding to 28
  putF32(s_blob + 16, lat);
  putF32(s_blob + 20, lon);
  putU16(s_blob + 24, 0);           // no sections
  uint32_t bodyLen = 28 - 16;
  putU32(s_blob + 12, bodyLen);
  putU32(s_blob + 8, geoCrc32(s_blob + 16, bodyLen));
  s_len = 28;
}

// Feeds the blob through the streaming validator in `chunk`-sized pieces,
// which is how it actually arrives off a socket.
static GeoStatus stream(size_t chunk, float homeLat = 51.8850f,
                        float homeLon = 0.2350f) {
  GeoStreamCheck check;
  check.begin(homeLat, homeLon);
  for (size_t at = 0; at < s_len; at += chunk) {
    size_t n = (at + chunk > s_len) ? s_len - at : chunk;
    check.feed(s_blob + at, n);
  }
  return check.finish(s_len);
}

// ------------------------------------------------------- incremental CRC

static void test_incremental_crc_matches_one_shot() {
  // The whole design rests on this: validating as the bytes arrive has to
  // produce the byte-for-byte same answer as validating a complete buffer,
  // or a good blob would be rejected.
  const uint8_t data[] = "the quick brown fox jumps over the lazy dog";
  size_t len = sizeof(data) - 1;
  uint32_t oneShot = geoCrc32(data, len);
  for (size_t chunk = 1; chunk <= len; chunk++) {
    uint32_t crc = geoCrc32Begin();
    for (size_t at = 0; at < len; at += chunk) {
      size_t n = (at + chunk > len) ? len - at : chunk;
      crc = geoCrc32Update(crc, data + at, n);
    }
    TEST_ASSERT_EQUAL_UINT32(oneShot, geoCrc32End(crc));
  }
}

static void test_empty_input_crc() {
  TEST_ASSERT_EQUAL_UINT32(geoCrc32(nullptr, 0),
                           geoCrc32End(geoCrc32Begin()));
}

// ------------------------------------------------------------ acceptance

static void test_a_good_blob_validates_whatever_the_chunking() {
  build();
  // 1 byte at a time is the worst case: the header itself spans chunks, so
  // this exercises the partial-header buffering.
  for (size_t chunk = 1; chunk <= 40; chunk++) {
    TEST_ASSERT_EQUAL(GEO_OK, stream(chunk));
  }
}

static void test_it_agrees_with_the_buffer_reader() {
  // Two validators, one format. If they ever disagree, one of them accepts
  // something the other rejects and the swap goes wrong in one direction or
  // the other.
  build();
  GeoBlob blob;
  TEST_ASSERT_EQUAL(GEO_OK, blob.open(s_blob, s_len, 51.8850f, 0.2350f));
  TEST_ASSERT_EQUAL(GEO_OK, stream(8));
}

// ------------------------------------------------------------- rejection

static void test_bad_magic() {
  build();
  s_blob[0] = 'Z';  // not [1]: "BXRG" already has an X there
  TEST_ASSERT_EQUAL(GEO_BAD_MAGIC, stream(4));
}

static void test_bad_version() {
  build();
  putU16(s_blob + 4, 2);
  TEST_ASSERT_EQUAL(GEO_BAD_VERSION, stream(4));
}

static void test_a_corrupt_body_fails_the_crc() {
  build();
  s_blob[24] ^= 0xFF;  // inside the CRC'd body
  TEST_ASSERT_EQUAL(GEO_BAD_CRC, stream(4));
}

static void test_wrong_home_is_refused() {
  // A blob for a different site must not be drawn: it would render another
  // area's map with no indication at all.
  build(52.5f, 1.0f);
  TEST_ASSERT_EQUAL(GEO_WRONG_HOME, stream(4));
}

static void test_home_within_tolerance_is_accepted() {
  // The Pi stores home at 4dp and the board holds a float; they differ in the
  // last decimals and must still match.
  build(51.8850f, 0.2350f);
  TEST_ASSERT_EQUAL(GEO_OK, stream(4, 51.88501837f, 0.23502731f));
}

static void test_a_short_body_is_truncated() {
  // Declares more body than actually arrives, which is how a cut-off
  // download presents. It must never reach the CRC comparison.
  build();
  putU32(s_blob + 12, 900);
  putU32(s_blob + 8, geoCrc32(s_blob + 16, 12));
  TEST_ASSERT_EQUAL(GEO_TRUNCATED, stream(4));
}

static void test_nothing_at_all_is_truncated() {
  GeoStreamCheck check;
  check.begin(51.8850f, 0.2350f);
  TEST_ASSERT_EQUAL(GEO_TRUNCATED, check.finish(0));
}

static void test_a_header_only_stream_is_truncated() {
  build();
  s_len = 10;  // stops mid-header
  TEST_ASSERT_EQUAL(GEO_TRUNCATED, stream(4));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_incremental_crc_matches_one_shot);
  RUN_TEST(test_empty_input_crc);
  RUN_TEST(test_a_good_blob_validates_whatever_the_chunking);
  RUN_TEST(test_it_agrees_with_the_buffer_reader);
  RUN_TEST(test_bad_magic);
  RUN_TEST(test_bad_version);
  RUN_TEST(test_a_corrupt_body_fails_the_crc);
  RUN_TEST(test_wrong_home_is_refused);
  RUN_TEST(test_home_within_tolerance_is_accepted);
  RUN_TEST(test_a_short_body_is_truncated);
  RUN_TEST(test_nothing_at_all_is_truncated);
  RUN_TEST(test_a_header_only_stream_is_truncated);
  return UNITY_END();
}
