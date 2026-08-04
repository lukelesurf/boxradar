#include "side_panel.h"
#include <Arduino.h>
#include <WiFi.h>
#include <stdio.h>

void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround) {
  if (onGround)
    snprintf(out, cap, "GND");
  else if (altFt >= TRANSITION_ALT_FT)
    snprintf(out, cap, "FL%03ld", (long)((altFt + 50) / 100));
  else
    snprintf(out, cap, "%ld", (long)altFt);
}

void drawSidePanel(TFT_eSPI &tft, const radar::AircraftStore &s,
                   const UiState &ui) {
  // Renders at x-origin 0 — caller positions the surface (sprite or screen).
  // Traffic list: two text lines per aircraft, nearest first
  for (int row = 0; row < LIST_ROWS; row++) {
    int y = row * LIST_ROW_H;
    bool has = row < s.count;
    const radar::Aircraft *a = has ? &s.list[row] : nullptr;
    bool sel = has && ui.selectedHex != 0 && a->hex == ui.selectedHex;
    uint16_t bg = sel ? TFT_NAVY : TFT_BLACK;
    tft.fillRect(0, y, LIST_W, LIST_ROW_H, bg);
    if (!has) continue;
    bool dim = a->seenS > radar::SEEN_DIM_S;
    tft.setTextColor(dim ? TFT_DARKGREY : TFT_WHITE, bg);
    char cs[9];
    snprintf(cs, sizeof(cs), "%s", a->callsign[0] ? a->callsign : "-");
    tft.drawString(cs, 2, y + 1, 1);
    char alt[8];
    formatAltitude(alt, sizeof(alt), a->altFt, a->onGround);
    char line2[14];
    snprintf(line2, sizeof(line2), "%-6s%s", alt, a->type);
    tft.setTextColor(dim ? TFT_DARKGREY : TFT_SILVER, bg);
    tft.drawString(line2, 2, y + 10, 1);
  }
  // Status strip
  tft.fillRect(0, STATUS_Y, LIST_W, 240 - STATUS_Y, TFT_BLACK);
  bool wifiOk = WiFi.status() == WL_CONNECTED;
  tft.setTextColor(wifiOk ? TFT_GREEN : TFT_RED, TFT_BLACK);
  tft.drawString(wifiOk ? "WIFI OK" : "NO WIFI", 2, STATUS_Y + 2, 1);
  char buf[12];
  snprintf(buf, sizeof(buf), "AC %d", s.count);
  tft.setTextColor(s.fetchOk ? TFT_WHITE : TFT_ORANGE, TFT_BLACK);
  tft.drawString(buf, 2, STATUS_Y + 14, 1);
  uint32_t ageS = s.lastFetchMs ? (millis() - s.lastFetchMs) / 1000 : 999;
  snprintf(buf, sizeof(buf), "AGE %lus", (unsigned long)(ageS > 999 ? 999 : ageS));
  tft.setTextColor(ageS > 10 ? TFT_ORANGE : TFT_SILVER, TFT_BLACK);
  tft.drawString(buf, 2, STATUS_Y + 26, 1);
}
