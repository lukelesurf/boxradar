#include "type_name.h"
#include <string.h>

namespace radar {

namespace {

// Case-insensitive, because the feed sends uppercase designators and the
// response echoes whatever the Pi uppercased. Comparing exactly would work
// today and break the day either side changes its mind about case, for a
// saving of nothing.
bool sameDesignator(const char *a, const char *b) {
  if (!a || !b) return false;
  for (;; a++, b++) {
    char ca = *a, cb = *b;
    if (ca >= 'a' && ca <= 'z') ca = (char)(ca - 'a' + 'A');
    if (cb >= 'a' && cb <= 'z') cb = (char)(cb - 'a' + 'A');
    if (ca != cb) return false;
    if (ca == '\0') return true;
  }
}

bool okDesignator(const char *d) {
  if (!d || !d[0]) return false;
  size_t n = 0;
  for (const char *p = d; *p; p++, n++) {
    if (n >= 4) return false;
    bool alnum = (*p >= 'A' && *p <= 'Z') || (*p >= 'a' && *p <= 'z') ||
                 (*p >= '0' && *p <= '9');
    if (!alnum) return false;
  }
  return true;
}

} // namespace

bool typeNameUrl(const char *receiverUrl, const char *designator, char *out,
                 size_t cap) {
  if (!out || cap == 0) return false;
  out[0] = '\0';
  if (!receiverUrl || !receiverUrl[0]) return false;
  if (!okDesignator(designator)) return false;

  // The last '/' AFTER the scheme. Searching the whole string would find the
  // one in "http://" for a receiver URL with no path at all, and truncate
  // "http://pi:8081" to "http:/" — a URL that fails in a way pointing nowhere
  // near this function.
  const char *scheme = strstr(receiverUrl, "://");
  const char *from = scheme ? scheme + 3 : receiverUrl;
  const char *lastSlash = strrchr(from, '/');

  size_t keep = lastSlash ? (size_t)(lastSlash - receiverUrl) + 1
                          : strlen(receiverUrl);
  size_t need = keep + 5 /* "type/" */ + strlen(designator);
  if (!lastSlash) need++; // the '/' this URL does not have
  if (need >= cap) return false;

  memcpy(out, receiverUrl, keep);
  out[keep] = '\0';
  if (!lastSlash) strcat(out, "/");
  strcat(out, "type/");
  strcat(out, designator);
  return true;
}

bool loadTypeName(JsonVariantConst root, const char *designator, char *out,
                  size_t cap) {
  if (!out || cap == 0) return false;
  out[0] = '\0';
  if (!designator || !designator[0]) return false;

  for (JsonObjectConst t : root["types"].as<JsonArrayConst>()) {
    const char *id = t["id"] | "";
    if (!sameDesignator(id, designator)) continue;
    const char *name = t["name"] | "";
    // Truncates rather than refusing, unlike cfgSetStr. A name is decoration
    // on a 320px panel: half of "NORTH AMERICAN ROCKWELL Turbo Commander" is
    // worth more than nothing, where half a URL is worth less.
    size_t n = strlen(name);
    if (n >= cap) n = cap - 1;
    memcpy(out, name, n);
    out[n] = '\0';
    return true;
  }
  return false;
}

} // namespace radar
