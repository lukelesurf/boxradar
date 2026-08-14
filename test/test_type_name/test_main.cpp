#include <unity.h>
#include <string.h>
#include "type_name.h"

using namespace radar;

void setUp(void) {}
void tearDown(void) {}

static bool parse(const char *json, const char *designator, char *out,
                  size_t cap) {
  JsonDocument doc;
  deserializeJson(doc, json);
  return loadTypeName(doc, designator, out, cap);
}

static void test_a_named_designator_comes_back() {
  char name[TYPE_NAME_LEN];
  TEST_ASSERT_TRUE(parse("{\"types\":[{\"id\":\"PC12\","
                         "\"name\":\"PILATUS PC-12\"}]}",
                         "PC12", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("PILATUS PC-12", name);
}

// The distinction the whole protocol turns on: answered-with-no-name is a
// definitive answer, not a failure, so it returns TRUE with an empty string.
// Returning false here would have the board asking again forever for a
// designator the database is never going to have.
static void test_an_id_with_no_name_is_answered_not_failed() {
  char name[TYPE_NAME_LEN];
  TEST_ASSERT_TRUE(parse("{\"types\":[{\"id\":\"GLID\"}]}",
                         "GLID", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("", name);
}

static void test_an_absent_id_is_not_an_answer() {
  // The Pi echoes every id it was asked about, so this means it answered
  // something unexpected — worth another go, unlike the case above.
  char name[TYPE_NAME_LEN];
  TEST_ASSERT_FALSE(parse("{\"types\":[{\"id\":\"A320\",\"name\":\"AIRBUS\"}]}",
                          "PC12", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("", name);
}

static void test_the_wanted_one_is_picked_out_of_several() {
  char name[TYPE_NAME_LEN];
  TEST_ASSERT_TRUE(parse("{\"types\":[{\"id\":\"A318\",\"name\":\"AIRBUS A-318\"},"
                         "{\"id\":\"PC12\",\"name\":\"PILATUS PC-12\"},"
                         "{\"id\":\"B738\",\"name\":\"BOEING 737-800\"}]}",
                         "PC12", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("PILATUS PC-12", name);
}

static void test_case_does_not_matter() {
  char name[TYPE_NAME_LEN];
  TEST_ASSERT_TRUE(parse("{\"types\":[{\"id\":\"PC12\",\"name\":\"PILATUS PC-12\"}]}",
                         "pc12", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("PILATUS PC-12", name);
}

static void test_the_longest_real_name_fits_whole() {
  // 47 characters, the longest in tar1090-db's table. A buffer that could not
  // hold it would truncate in transport, where the panel — which is the thing
  // that actually runs out of room — could never get it back.
  const char *longest = "NORTH AMERICAN ROCKWELL Turbo Commander 690/840";
  TEST_ASSERT_EQUAL_size_t(47, strlen(longest));
  TEST_ASSERT_TRUE(strlen(longest) < TYPE_NAME_LEN);

  char json[160], name[TYPE_NAME_LEN];
  snprintf(json, sizeof(json), "{\"types\":[{\"id\":\"AC90\",\"name\":\"%s\"}]}",
           longest);
  TEST_ASSERT_TRUE(parse(json, "AC90", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING(longest, name);
}

static void test_an_oversized_name_truncates_rather_than_overflowing() {
  char name[8];
  TEST_ASSERT_TRUE(parse("{\"types\":[{\"id\":\"PC12\",\"name\":\"PILATUS PC-12\"}]}",
                         "PC12", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("PILATUS", name);
  TEST_ASSERT_EQUAL_size_t(7, strlen(name));
}

static void test_rubbish_does_not_crash_or_leave_stale_text() {
  char name[TYPE_NAME_LEN];
  strcpy(name, "STALE");
  TEST_ASSERT_FALSE(parse("{}", "PC12", name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("", name);

  strcpy(name, "STALE");
  TEST_ASSERT_FALSE(parse("{\"types\":\"not an array\"}", "PC12", name,
                          sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("", name);

  strcpy(name, "STALE");
  TEST_ASSERT_FALSE(parse("{\"error\":\"no aircraft type database\"}", "PC12",
                          name, sizeof(name)));
  TEST_ASSERT_EQUAL_STRING("", name);
}

static void test_no_designator_is_refused() {
  char name[TYPE_NAME_LEN];
  TEST_ASSERT_FALSE(parse("{\"types\":[{\"id\":\"PC12\",\"name\":\"X\"}]}", "",
                          name, sizeof(name)));
  TEST_ASSERT_FALSE(parse("{\"types\":[{\"id\":\"PC12\",\"name\":\"X\"}]}",
                          nullptr, name, sizeof(name)));
}

// ------------------------------------------------------------------- the URL

static void test_the_last_path_segment_is_swapped() {
  char url[96];
  TEST_ASSERT_TRUE(typeNameUrl("http://receiver.lan:8081/contacts", "PC12",
                               url, sizeof(url)));
  TEST_ASSERT_EQUAL_STRING("http://receiver.lan:8081/type/PC12", url);
}

static void test_a_receiver_url_with_no_path_still_works() {
  // The trap this exists for: searching the whole string for the last '/'
  // finds the one in "http://" and produces "http:/type/PC12", which fails
  // somewhere that gives no hint where it came from.
  char url[96];
  TEST_ASSERT_TRUE(typeNameUrl("http://192.0.2.10:8081", "PC12", url,
                               sizeof(url)));
  TEST_ASSERT_EQUAL_STRING("http://192.0.2.10:8081/type/PC12", url);
}

static void test_a_deeper_path_keeps_its_prefix() {
  char url[96];
  TEST_ASSERT_TRUE(typeNameUrl("http://pi/boxradar/contacts", "A320", url,
                               sizeof(url)));
  TEST_ASSERT_EQUAL_STRING("http://pi/boxradar/type/A320", url);
}

static void test_a_rubbish_designator_never_reaches_a_url() {
  // Aircraft::type arrives over the wire in the contact feed. A URL is the
  // wrong place to discover that something upstream sent nonsense.
  char url[96];
  const char *bad[] = {"PC-12", "TOOLONG", "../etc", "PC 1", "a/b", ""};
  for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
    strcpy(url, "STALE");
    TEST_ASSERT_FALSE(typeNameUrl("http://pi:8081/contacts", bad[i], url,
                                  sizeof(url)));
    TEST_ASSERT_EQUAL_STRING("", url);
  }
  TEST_ASSERT_FALSE(typeNameUrl("http://pi:8081/contacts", nullptr, url,
                                sizeof(url)));
}

static void test_short_and_numeric_designators_are_allowed() {
  // A1 and A002 are real designators; a four-letter rule would reject both.
  char url[96];
  TEST_ASSERT_TRUE(typeNameUrl("http://pi:8081/contacts", "A1", url,
                               sizeof(url)));
  TEST_ASSERT_EQUAL_STRING("http://pi:8081/type/A1", url);
  TEST_ASSERT_TRUE(typeNameUrl("http://pi:8081/contacts", "A002", url,
                               sizeof(url)));
  TEST_ASSERT_EQUAL_STRING("http://pi:8081/type/A002", url);
}

static void test_a_url_that_will_not_fit_is_refused_not_truncated() {
  // A truncated URL is a request to somewhere else, so this refuses on the
  // same principle as cfgSetStr rather than sending a half one.
  char url[16];
  TEST_ASSERT_FALSE(typeNameUrl("http://receiver.lan:8081/contacts", "PC12",
                                url, sizeof(url)));
  TEST_ASSERT_EQUAL_STRING("", url);
}

static void test_no_receiver_url_is_refused() {
  char url[96];
  TEST_ASSERT_FALSE(typeNameUrl("", "PC12", url, sizeof(url)));
  TEST_ASSERT_FALSE(typeNameUrl(nullptr, "PC12", url, sizeof(url)));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_a_named_designator_comes_back);
  RUN_TEST(test_an_id_with_no_name_is_answered_not_failed);
  RUN_TEST(test_an_absent_id_is_not_an_answer);
  RUN_TEST(test_the_wanted_one_is_picked_out_of_several);
  RUN_TEST(test_case_does_not_matter);
  RUN_TEST(test_the_longest_real_name_fits_whole);
  RUN_TEST(test_an_oversized_name_truncates_rather_than_overflowing);
  RUN_TEST(test_rubbish_does_not_crash_or_leave_stale_text);
  RUN_TEST(test_no_designator_is_refused);
  RUN_TEST(test_the_last_path_segment_is_swapped);
  RUN_TEST(test_a_receiver_url_with_no_path_still_works);
  RUN_TEST(test_a_deeper_path_keeps_its_prefix);
  RUN_TEST(test_a_rubbish_designator_never_reaches_a_url);
  RUN_TEST(test_short_and_numeric_designators_are_allowed);
  RUN_TEST(test_a_url_that_will_not_fit_is_refused_not_truncated);
  RUN_TEST(test_no_receiver_url_is_refused);
  return UNITY_END();
}
