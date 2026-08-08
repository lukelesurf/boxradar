#include "format.h"
#include <stdio.h>
#include <string.h>

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

void formatWind(char *out, size_t cap, const Metar &m) {
  // Calm is checked before direction: a 0kt wind has no meaningful direction
  // to print even when the observation carries one.
  if (m.windKt == 0) {
    snprintf(out, cap, "CALM");
  } else if (m.windDir < 0) {
    snprintf(out, cap, "VRB/%02u", m.windKt);
  } else if (m.gustKt > 0) {
    snprintf(out, cap, "%03d/%02uG%u", m.windDir, m.windKt, m.gustKt);
  } else {
    snprintf(out, cap, "%03d/%02u", m.windDir, m.windKt);
  }
}

void formatCloud(char *out, size_t cap, const Metar &m) {
  const char *cover = m.cover[0] ? m.cover : "NCD";
  // "NCD" is the feed's stand-in for an empty cloud list, which upstream
  // reports identically for NCD, NSC, SKC and CAVOK — there is no way to
  // tell them apart from the parsed fields. "CLEAR" is the honest umbrella
  // term and reads without a glossary.
  if (strcmp(cover, "NCD") == 0) cover = "CLEAR";
  if (m.ceilFt == 0) {
    snprintf(out, cap, "%s", cover);
    return;
  }
  // Hundreds of feet, METAR style: BKN012 is a 1200ft base.
  snprintf(out, cap, "%s%03u", cover, (unsigned)((m.ceilFt + 50) / 100));
}

} // namespace radar
