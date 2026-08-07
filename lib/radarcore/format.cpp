#include "format.h"
#include <stdio.h>

namespace radar {

void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround) {
  if (onGround) {
    snprintf(out, cap, "GND");
    return;
  }
  // Round half away from zero so the sign doesn't bias the result. Feeds do
  // emit small negatives near sea level when QNH is above standard; those
  // render as "-01" rather than being clamped, because silently showing 000
  // for a genuine below-datum reading would be a lie.
  long hundreds = (altFt >= 0 ? altFt + 50 : altFt - 50) / 100;
  snprintf(out, cap, "%03ld", hundreds);
}

void formatCallsign(char *out, size_t cap, const char *callsign, uint32_t hex) {
  if (callsign && callsign[0])
    snprintf(out, cap, "%s", callsign);
  else
    snprintf(out, cap, "%04lx", (unsigned long)(hex & 0xFFFF));
}

} // namespace radar
