#pragma once
#include <stddef.h>
#include <stdint.h>
#include "metar.h"

namespace radar {

// Altitude as hundreds of feet, always — "350", "060", "GND" on the ground.
// Deliberately NOT split into flight levels above a transition altitude and
// feet below it: the distinction costs two characters in every datablock and
// tells a desk-toy user nothing they act on. Rounds to the nearest 100ft,
// which is the Mode C reporting granularity anyway.
void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround);

// Callsign, falling back to the last 4 hex digits of the ICAO address when
// the feed carries no flight id. Never empty — a blank label on the scope
// would be indistinguishable from a rendering failure.
void formatCallsign(char *out, size_t cap, const char *callsign, uint32_t hex);

// "160/05", "160/05G25", "VRB/03", "CALM". Compact enough for a status line
// and close enough to METAR convention to read without a legend.
void formatWind(char *out, size_t cap, const Metar &m);

// "BKN012" (cover plus base in hundreds of feet) or the bare cover when
// there is no ceiling — "NCD", "FEW", "SCT". A base is only meaningful for
// the broken/overcast layers that actually hide the sky.
void formatCloud(char *out, size_t cap, const Metar &m);

} // namespace radar
