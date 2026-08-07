#include "status_bar.h"
#include <Arduino.h>
#include <WiFi.h>
#include <stdio.h>

// Three short lines stacked in the corner the range ring can never reach:
// the ring is 228px across on a 320px panel, so x < 100 at y < 30 is always
// clear of it at every range setting.
void drawStatusCorner(TFT_eSprite &spr, const radar::AircraftStore &s) {
  bool wifiOk = WiFi.status() == WL_CONNECTED;
  spr.setTextColor(wifiOk ? TFT_GREEN : TFT_RED, TFT_BLACK);
  spr.drawString(wifiOk ? "WIFI" : "NO WIFI", STATUS_X, STATUS_Y, 1);

  char buf[12];
  snprintf(buf, sizeof(buf), "AC %d", s.count);
  spr.setTextColor(s.fetchOk ? TFT_WHITE : TFT_ORANGE, TFT_BLACK);
  spr.drawString(buf, STATUS_X, STATUS_Y + 10, 1);

  // Age of the last successful poll, clamped so a dead feed can't widen the
  // field past the corner and overlap the scope.
  uint32_t ageS = s.lastFetchMs ? (millis() - s.lastFetchMs) / 1000 : 999;
  snprintf(buf, sizeof(buf), "%lus", (unsigned long)(ageS > 999 ? 999 : ageS));
  spr.setTextColor(ageS > 10 ? TFT_ORANGE : TFT_SILVER, TFT_BLACK);
  spr.drawString(buf, STATUS_X, STATUS_Y + 20, 1);
}
