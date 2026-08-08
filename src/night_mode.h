#pragma once
#include <stdint.h>

// Blanks the display overnight, waking on a tap.
//
// The CYD has no RTC, so this depends entirely on NTP — which the ESP32 runs
// itself via the IDF's SNTP client. Until the first sync lands, the clock
// reads 1970 and night mode stays OFF: a board that failed to get the time
// and sat dark would be indistinguishable from a crashed one, so the failure
// mode points at "visibly on" rather than "silently dark".
//
// Timezone is a POSIX TZ rule, not a fixed offset, so BST transitions are
// handled by localtime() forever rather than drifting an hour twice a year.

void nightModeInit();

// Advances the fade and returns 1.0 = fully awake, 0.0 = fully night.
// Call once per UI frame with the frame period.
//
// This is an interpolation weight, NOT a multiplier. The backlight is
// lerped between nightModeIdleDuty() and the LDR's own duty, because with
// a clock the night target is a specific low brightness rather than zero,
// and scaling the LDR reading would let night brightness drift with
// ambient light — in a dark room the LDR sits near its own floor of 40,
// which leaves almost no usable range below it.
float nightModeUpdate(uint32_t frameMs);

// Absolute backlight duty (0-255) when fully night: 0 when blanking, or
// NIGHT_CLOCK_DUTY when showing the clock.
int nightModeIdleDuty();

// A tap during night hours: hold the display up for NIGHT_WAKE_S. Safe to
// call at any hour — outside the night window it does nothing.
void nightModeWake();

// True while the panel is fully dark, so the caller can skip rendering
// entirely rather than build a sprite nobody can see.
bool nightModeDark();
