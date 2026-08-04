#pragma once
#include <stddef.h>
#include <stdint.h>

namespace radar {

constexpr int32_t TRANSITION_ALT_FT = 6000; // UK-ish; FL above, feet below

// "FL350" at/above transition, "4500" below, "GND" on ground
void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround);

} // namespace radar
