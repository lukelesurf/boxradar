#include "night_mode.h"
#include <Arduino.h>
#include <time.h>
#include "config.h"

#ifdef NIGHT_BLANKING

// Anything earlier than this means SNTP has not landed yet — the clock still
// reads the 1970 epoch. Picked as a date safely in the past rather than a
// magic constant tied to a build.
static constexpr time_t TIME_SYNCED_AFTER = 1700000000; // ~Nov 2023

static float s_level = 1.0f; // 0 = dark, 1 = full brightness
static uint32_t s_wakeUntilMs = 0;

void nightModeInit() {
  // Sets TZ and starts the SNTP client. Safe before WiFi is up; it retries
  // on its own once the network appears.
  configTzTime(NIGHT_TZ, NTP_SERVER);
}

static bool inNightHours() {
  time_t now = time(nullptr);
  if (now < TIME_SYNCED_AFTER) return false; // no trustworthy clock: stay on
  struct tm lt;
  if (!localtime_r(&now, &lt)) return false;
  int h = lt.tm_hour;
  // Handles a window that wraps midnight (e.g. 22 -> 07) as well as one that
  // does not (e.g. 00 -> 07).
  if (NIGHT_START_HOUR == NIGHT_END_HOUR) return false; // disabled
  if (NIGHT_START_HOUR < NIGHT_END_HOUR)
    return h >= NIGHT_START_HOUR && h < NIGHT_END_HOUR;
  return h >= NIGHT_START_HOUR || h < NIGHT_END_HOUR;
}

void nightModeWake() {
  if (!inNightHours()) return;
  s_wakeUntilMs = millis() + (uint32_t)NIGHT_WAKE_S * 1000;
}

float nightModeUpdate(uint32_t frameMs) {
  bool awake = s_wakeUntilMs && (int32_t)(s_wakeUntilMs - millis()) > 0;
  if (!awake) s_wakeUntilMs = 0;
  float target = (inNightHours() && !awake) ? 0.0f : 1.0f;

  // Ramp rather than snap. At 3am the difference between a fade and a full
  // backlight appearing instantly is the difference between glancing at it
  // and being woken up by it.
  float step = (NIGHT_FADE_MS > 0)
                   ? (float)frameMs / (float)NIGHT_FADE_MS
                   : 1.0f;
  if (s_level < target)
    s_level = (s_level + step > target) ? target : s_level + step;
  else if (s_level > target)
    s_level = (s_level - step < target) ? target : s_level - step;
  return s_level;
}

bool nightModeDark() { return s_level <= 0.001f; }

int nightModeIdleDuty() {
#ifdef NIGHT_CLOCK
  return NIGHT_CLOCK_DUTY;
#else
  return 0;
#endif
}

#else // NIGHT_BLANKING disabled

void nightModeInit() {}
float nightModeUpdate(uint32_t) { return 1.0f; }
void nightModeWake() {}
bool nightModeDark() { return false; }
int nightModeIdleDuty() { return 0; }

#endif
