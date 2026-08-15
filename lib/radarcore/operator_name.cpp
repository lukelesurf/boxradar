#include "operator_name.h"
#include <string.h>

namespace radar {

namespace {

bool isUpper(char c) { return c >= 'A' && c <= 'Z'; }
bool isLower(char c) { return c >= 'a' && c <= 'z'; }
bool isDigit(char c) { return c >= '0' && c <= '9'; }

char upper(char c) { return isLower(c) ? (char)(c - 'a' + 'A') : c; }

bool okCode(const char *code) {
  if (!code) return false;
  for (int i = 0; i < 3; i++)
    if (!isUpper(code[i])) return false;
  return code[3] == '\0';
}

bool sameCode(const char *a, const char *b) {
  if (!a || !b) return false;
  for (size_t i = 0;; i++) {
    if (upper(a[i]) != upper(b[i])) return false;
    if (a[i] == '\0') return true;
  }
}

void copyTruncating(char *out, size_t cap, const char *src) {
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(out, src, n);
  out[n] = '\0';
}

} // namespace

bool operatorCodeFrom(const char *callsign, char *out, size_t cap) {
  if (!out || cap < 4) return false;
  out[0] = '\0';
  if (!callsign) return false;

  // Three letters then a digit. Anything else is not an airline callsign —
  // most often a registration, which would otherwise yield a three-character
  // key that resolves to somebody else's airline. See the header.
  for (int i = 0; i < 3; i++) {
    char c = upper(callsign[i]);
    if (!isUpper(c)) return false;
  }
  if (!isDigit(callsign[3])) return false;

  for (int i = 0; i < 3; i++) out[i] = upper(callsign[i]);
  out[3] = '\0';
  return true;
}

bool operatorUrl(const char *receiverUrl, const char *code, char *out,
                 size_t cap) {
  if (!out || cap == 0) return false;
  out[0] = '\0';
  if (!receiverUrl || !receiverUrl[0]) return false;
  if (!okCode(code)) return false;

  // The last '/' AFTER the scheme, for the reason typeNameUrl() spells out:
  // searching the whole string finds the one in "http://" when the receiver
  // URL has no path, and truncates "http://pi:8081" to "http:/".
  const char *scheme = strstr(receiverUrl, "://");
  const char *from = scheme ? scheme + 3 : receiverUrl;
  const char *lastSlash = strrchr(from, '/');

  size_t keep = lastSlash ? (size_t)(lastSlash - receiverUrl) + 1
                          : strlen(receiverUrl);
  size_t need = keep + 9 /* "operator/" */ + strlen(code);
  if (!lastSlash) need++; // the '/' this URL does not have
  if (need >= cap) return false;

  memcpy(out, receiverUrl, keep);
  out[keep] = '\0';
  if (!lastSlash) strcat(out, "/");
  strcat(out, "operator/");
  strcat(out, code);
  return true;
}

bool loadOperatorName(JsonVariantConst root, const char *code, char *name,
                      size_t nameCap, char *radio, size_t radioCap) {
  if (!name || nameCap == 0 || !radio || radioCap == 0) return false;
  name[0] = '\0';
  radio[0] = '\0';
  if (!code || !code[0]) return false;

  for (JsonObjectConst o : root["operators"].as<JsonArrayConst>()) {
    const char *id = o["id"] | "";
    if (!sameCode(id, code)) continue;
    // Truncated rather than refused, unlike cfgSetStr: a name is decoration on
    // a 320px panel, and half of one is worth more than nothing where half a
    // URL is worth less.
    copyTruncating(name, nameCap, o["name"] | "");
    copyTruncating(radio, radioCap, o["radio"] | "");
    // Answered, even with nothing. The Pi echoes every id it was asked about,
    // so an empty name is the database saying it has no entry — a fact that
    // will not change, and retrying it would spend all three attempts
    // relearning it.
    return true;
  }
  return false;
}

} // namespace radar
