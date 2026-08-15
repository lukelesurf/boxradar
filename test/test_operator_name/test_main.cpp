#include <unity.h>
#include <string.h>
#include <ArduinoJson.h>
#include "operator_name.h"

using namespace radar;

// -------------------------------------------------- deriving the code

static bool code(const char *callsign, char *out) {
  return operatorCodeFrom(callsign, out, 8);
}

static void test_an_airline_callsign_yields_its_code() {
  char out[8];
  TEST_ASSERT_TRUE(code("BAW123", out));
  TEST_ASSERT_EQUAL_STRING("BAW", out);
  TEST_ASSERT_TRUE(code("RYR4ZQ", out));
  TEST_ASSERT_EQUAL_STRING("RYR", out);
  TEST_ASSERT_TRUE(code("EZY85TG", out));
  TEST_ASSERT_EQUAL_STRING("EZY", out);
}

static void test_lowercase_is_accepted_and_raised() {
  char out[8];
  TEST_ASSERT_TRUE(code("baw123", out));
  TEST_ASSERT_EQUAL_STRING("BAW", out);
}

// The case this rule exists for. A UK registration reaches the board as
// GBXYZ, and taking its first three characters gives GBX — a perfectly
// plausible key that may well be somebody's real airline. The lookup would
// not fail, it would answer confidently and wrongly.
static void test_a_registration_is_refused_rather_than_guessed() {
  char out[8];
  TEST_ASSERT_FALSE(code("GBXYZ", out));
  TEST_ASSERT_EQUAL_STRING("", out);
  TEST_ASSERT_FALSE(code("GABCD", out));
  TEST_ASSERT_FALSE(code("N123AB", out));   // first three are not all letters
  TEST_ASSERT_FALSE(code("DEABC", out));
}

static void test_the_fourth_character_must_be_a_digit() {
  char out[8];
  TEST_ASSERT_FALSE(code("BAWA23", out));
  TEST_ASSERT_TRUE(code("BAW023", out));
}

static void test_short_and_empty_callsigns_are_refused() {
  char out[8];
  TEST_ASSERT_FALSE(code("", out));
  TEST_ASSERT_FALSE(code("BAW", out));   // no flight number at all
  TEST_ASSERT_FALSE(code(nullptr, out));
}

static void test_a_tiny_buffer_is_refused_not_overrun() {
  char out[4];
  TEST_ASSERT_TRUE(operatorCodeFrom("BAW123", out, sizeof(out)));
  TEST_ASSERT_EQUAL_STRING("BAW", out);
  char tiny[3];
  TEST_ASSERT_FALSE(operatorCodeFrom("BAW123", tiny, sizeof(tiny)));
}

// ------------------------------------------------------------- the URL

static void test_url_swaps_the_last_segment() {
  char out[128];
  TEST_ASSERT_TRUE(
      operatorUrl("http://pi:8081/contacts", "BAW", out, sizeof(out)));
  TEST_ASSERT_EQUAL_STRING("http://pi:8081/operator/BAW", out);
}

static void test_url_with_no_path_gains_a_slash() {
  char out[128];
  TEST_ASSERT_TRUE(operatorUrl("http://pi:8081", "RYR", out, sizeof(out)));
  TEST_ASSERT_EQUAL_STRING("http://pi:8081/operator/RYR", out);
}

static void test_a_deeper_path_keeps_its_prefix() {
  char out[128];
  TEST_ASSERT_TRUE(
      operatorUrl("http://pi:8081/api/v1/contacts", "GTI", out, sizeof(out)));
  TEST_ASSERT_EQUAL_STRING("http://pi:8081/api/v1/operator/GTI", out);
}

static void test_a_bad_code_never_reaches_a_url() {
  char out[128];
  TEST_ASSERT_FALSE(operatorUrl("http://pi:8081/contacts", "BA", out,
                                sizeof(out)));
  TEST_ASSERT_FALSE(operatorUrl("http://pi:8081/contacts", "BAW1", out,
                                sizeof(out)));
  TEST_ASSERT_FALSE(operatorUrl("http://pi:8081/contacts", "", out,
                                sizeof(out)));
  TEST_ASSERT_EQUAL_STRING("", out);
}

static void test_a_url_that_will_not_fit_is_refused_not_truncated() {
  char out[20];
  TEST_ASSERT_FALSE(operatorUrl("http://a-very-long-host.example/contacts",
                                "BAW", out, sizeof(out)));
  TEST_ASSERT_EQUAL_STRING("", out);
}

// ---------------------------------------------------- parsing the reply

static bool parse(const char *json, const char *want, char *name,
                  char *radio) {
  JsonDocument doc;
  deserializeJson(doc, json);
  return loadOperatorName(doc, want, name, OPERATOR_NAME_LEN, radio,
                          OPERATOR_RADIO_LEN);
}

static void test_name_and_radio_are_both_read() {
  char name[OPERATOR_NAME_LEN], radio[OPERATOR_RADIO_LEN];
  TEST_ASSERT_TRUE(parse(
      "{\"operators\":[{\"id\":\"BAW\",\"name\":\"British Airways\","
      "\"radio\":\"SPEEDBIRD\"}]}", "BAW", name, radio));
  TEST_ASSERT_EQUAL_STRING("British Airways", name);
  TEST_ASSERT_EQUAL_STRING("SPEEDBIRD", radio);
}

static void test_a_missing_radio_is_a_partial_answer_not_a_failure() {
  // Several hundred operators are registered with no radio callsign. That is
  // still an answer — the name is the useful half — so it must not be
  // discarded or retried.
  char name[OPERATOR_NAME_LEN], radio[OPERATOR_RADIO_LEN];
  TEST_ASSERT_TRUE(parse(
      "{\"operators\":[{\"id\":\"ZZZ\",\"name\":\"Some Air\"}]}", "ZZZ",
      name, radio));
  TEST_ASSERT_EQUAL_STRING("Some Air", name);
  TEST_ASSERT_EQUAL_STRING("", radio);
}

static void test_an_echoed_code_with_no_name_is_answered_not_failed() {
  // The Pi echoes every id it was asked about, so this means the table has
  // nothing for the code — a definitive answer. Returning false would spend
  // all three retries relearning a fact that will not change.
  char name[OPERATOR_NAME_LEN], radio[OPERATOR_RADIO_LEN];
  TEST_ASSERT_TRUE(parse("{\"operators\":[{\"id\":\"QQQ\"}]}", "QQQ", name,
                         radio));
  TEST_ASSERT_EQUAL_STRING("", name);
}

static void test_an_absent_code_is_a_failure_worth_retrying() {
  char name[OPERATOR_NAME_LEN], radio[OPERATOR_RADIO_LEN];
  TEST_ASSERT_FALSE(parse("{\"operators\":[{\"id\":\"BAW\",\"name\":\"BA\"}]}",
                          "RYR", name, radio));
  TEST_ASSERT_FALSE(parse("{}", "BAW", name, radio));
  TEST_ASSERT_FALSE(parse("{\"operators\":[]}", "BAW", name, radio));
}

static void test_the_right_entry_is_picked_out_of_several() {
  char name[OPERATOR_NAME_LEN], radio[OPERATOR_RADIO_LEN];
  TEST_ASSERT_TRUE(parse(
      "{\"operators\":[{\"id\":\"BAW\",\"name\":\"British Airways\"},"
      "{\"id\":\"RYR\",\"name\":\"Ryanair\",\"radio\":\"RYANAIR\"}]}",
      "RYR", name, radio));
  TEST_ASSERT_EQUAL_STRING("Ryanair", name);
  TEST_ASSERT_EQUAL_STRING("RYANAIR", radio);
}

static void test_an_overlong_name_is_truncated_not_dropped() {
  // A name is decoration on a 320px panel: half of one is worth more than
  // nothing, unlike half a URL.
  char name[OPERATOR_NAME_LEN], radio[OPERATOR_RADIO_LEN];
  char json[160];
  snprintf(json, sizeof(json),
           "{\"operators\":[{\"id\":\"AAA\",\"name\":\"%s\"}]}",
           "AAAAAAAAAABBBBBBBBBBCCCCCCCCCCDDDDDDDDDDEEEEEEEEEEFFFFFFFFFF");
  TEST_ASSERT_TRUE(parse(json, "AAA", name, radio));
  TEST_ASSERT_EQUAL_size_t(OPERATOR_NAME_LEN - 1, strlen(name));
}

int main(int, char **) {
  UNITY_BEGIN();
  RUN_TEST(test_an_airline_callsign_yields_its_code);
  RUN_TEST(test_lowercase_is_accepted_and_raised);
  RUN_TEST(test_a_registration_is_refused_rather_than_guessed);
  RUN_TEST(test_the_fourth_character_must_be_a_digit);
  RUN_TEST(test_short_and_empty_callsigns_are_refused);
  RUN_TEST(test_a_tiny_buffer_is_refused_not_overrun);
  RUN_TEST(test_url_swaps_the_last_segment);
  RUN_TEST(test_url_with_no_path_gains_a_slash);
  RUN_TEST(test_a_deeper_path_keeps_its_prefix);
  RUN_TEST(test_a_bad_code_never_reaches_a_url);
  RUN_TEST(test_a_url_that_will_not_fit_is_refused_not_truncated);
  RUN_TEST(test_name_and_radio_are_both_read);
  RUN_TEST(test_a_missing_radio_is_a_partial_answer_not_a_failure);
  RUN_TEST(test_an_echoed_code_with_no_name_is_answered_not_failed);
  RUN_TEST(test_an_absent_code_is_a_failure_worth_retrying);
  RUN_TEST(test_the_right_entry_is_picked_out_of_several);
  RUN_TEST(test_an_overlong_name_is_truncated_not_dropped);
  return UNITY_END();
}
