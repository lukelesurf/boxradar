#include "classify.h"
#include <string.h>

namespace radar {

// ICAO type designators, sorted by family for readability rather than by
// frequency — the scan is linear over ~22 entries at most 32 times a frame,
// which is nothing next to the JSON parse.
static const char *const COMMON_TYPES[] = {
    // A320 family
    "A319", "A320", "A321", "A20N", "A21N", "A318",
    // 737 family
    "B737", "B738", "B739", "B736", "B38M", "B39M", "B37M",
    // Embraer E-jets (incl. E2)
    "E170", "E175", "E190", "E195", "E75L", "E75S", "E290", "E295",
    // Regional turboprops
    "AT43", "AT45", "AT72", "AT75", "AT76", "DH8D",
};

bool isCommonType(const char *type) {
  if (!type || !type[0]) return true; // unknown -> not interesting
  for (const char *t : COMMON_TYPES)
    if (strcmp(t, type) == 0) return true;
  return false;
}

bool isAlertSquawk(const char *squawk) {
  if (!squawk) return false;
  return strcmp(squawk, "7500") == 0 || strcmp(squawk, "7600") == 0 ||
         strcmp(squawk, "7700") == 0;
}

} // namespace radar
