#include "status_led.h"
#include <Arduino.h>

// CYD RGB LED, active low
static constexpr int LED_R = 4, LED_G = 16, LED_B = 17;

void statusLedInit() {
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  statusLedSet(LedStatus::NoWifi);
}

void statusLedSet(LedStatus s) {
  bool r = s == LedStatus::NoWifi || s == LedStatus::NoData; // amber = r+g
  bool g = s == LedStatus::NoData;
  digitalWrite(LED_R, r ? LOW : HIGH);
  digitalWrite(LED_G, g ? LOW : HIGH);
  digitalWrite(LED_B, HIGH);
}
