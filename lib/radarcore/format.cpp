#include "format.h"
#include <stdio.h>

namespace radar {

void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround) {
  if (onGround)
    snprintf(out, cap, "GND");
  else if (altFt >= TRANSITION_ALT_FT)
    snprintf(out, cap, "FL%03ld", (long)((altFt + 50) / 100));
  else
    snprintf(out, cap, "%ld", (long)altFt);
}

} // namespace radar
