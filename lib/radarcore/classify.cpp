#include "classify.h"
#include <string.h>

namespace radar {

// ICAO type designators that saturate a London-area feed, as a comma list so
// the built-in default and a configured override share one code path.
//
// Sorted by family for readability rather than by frequency — the scan is
// linear over ~27 entries at most 32 times a frame, which is nothing next to
// the JSON parse.
//
// **This list is regional, and so is its polarity.** It is a whitelist of
// boring, so anything absent lights up; at a GA field the everyday traffic is
// light singles, none of which are here, and everything would read as
// interesting. That is why it is configurable rather than merely long.
static const char *const DEFAULT_COMMON_TYPES =
    // A320 family
    "A319,A320,A321,A20N,A21N,A318,"
    // 737 family
    "B737,B738,B739,B736,B38M,B39M,B37M,"
    // Embraer E-jets (incl. E2)
    "E170,E175,E190,E195,E75L,E75S,E290,E295,"
    // Regional turboprops
    "AT43,AT45,AT72,AT75,AT76,DH8D";

// Whatever the board is currently configured with, or null for the built-in.
// A borrowed pointer: the caller owns the storage. In the firmware that is the
// SiteConfig struct, which is static and outlives everything.
static const char *s_commonTypes = nullptr;

namespace {

char upper(char c) { return (c >= 'a' && c <= 'z') ? (char)(c - 32) : c; }

bool isSpace(char c) { return c == ' ' || c == '\t'; }

// Whole-token comparison against one entry of the list, case-insensitively and
// ignoring surrounding spaces. `entry` runs to `end`.
bool entryMatches(const char *entry, const char *end, const char *type) {
  while (entry < end && isSpace(*entry)) entry++;
  while (end > entry && isSpace(end[-1])) end--;
  if (entry == end) return false;  // an empty entry matches nothing, not ""
  size_t n = (size_t)(end - entry);
  if (strlen(type) != n) return false;  // whole designators only: A32 != A320
  for (size_t i = 0; i < n; i++)
    if (upper(entry[i]) != upper(type[i])) return false;
  return true;
}

} // namespace

const char *classifyDefaultCommonTypes() { return DEFAULT_COMMON_TYPES; }

void classifySetCommonTypes(const char *csv) {
  // An empty setting falls back to the built-in rather than meaning "nothing
  // is boring". A cleared box is far more likely than a deliberate choice to
  // have every aircraft on screen light up at once.
  s_commonTypes = (csv && csv[0]) ? csv : nullptr;
}

bool isCommonTypeIn(const char *type, const char *csv) {
  if (!type || !type[0]) return true;  // unknown -> not interesting
  if (!csv || !csv[0]) return false;
  const char *at = csv;
  while (*at) {
    const char *comma = strchr(at, ',');
    const char *end = comma ? comma : at + strlen(at);
    if (entryMatches(at, end, type)) return true;
    if (!comma) break;
    at = comma + 1;
  }
  return false;
}

bool isCommonType(const char *type) {
  if (!type || !type[0]) return true; // unknown -> not interesting
  return isCommonTypeIn(type, s_commonTypes ? s_commonTypes
                                            : DEFAULT_COMMON_TYPES);
}

bool isAlertSquawk(const char *squawk) {
  if (!squawk) return false;
  return strcmp(squawk, "7500") == 0 || strcmp(squawk, "7600") == 0 ||
         strcmp(squawk, "7700") == 0;
}

} // namespace radar
