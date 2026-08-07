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

// Advances the fade and returns a 0.0-1.0 backlight multiplier applied on
// top of the LDR's own dimming. Call once per UI frame with the frame period.
float nightModeUpdate(uint32_t frameMs);

// A tap during night hours: hold the display up for NIGHT_WAKE_S. Safe to
// call at any hour — outside the night window it does nothing.
void nightModeWake();

// True while the panel is fully dark, so the caller can skip rendering
// entirely rather than build a sprite nobody can see.
bool nightModeDark();
