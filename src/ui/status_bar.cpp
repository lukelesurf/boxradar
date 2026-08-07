#include "status_bar.h"
#include <Arduino.h>
#include <WiFi.h>
#include <stdio.h>

// Five missed polls at POLL_INTERVAL_MS=2000. Long enough that ordinary WiFi
// jitter or a single slow response never trips it, short enough that a truly
// dead feed is called out well before aircraft start ageing off the scope.
static constexpr uint32_t STALE_WARN_S = 10;

// Three short lines stacked in the corner the range ring can never reach:
// the ring is 228px across on a 320px panel, so x < 100 at y < 30 is always
// clear of it at every range setting.
void drawStatusCorner(TFT_eSprite &spr, const radar::AircraftStore &s,
                      int onScreen, int mlatOnScreen) {
  bool wifiOk = WiFi.status() == WL_CONNECTED;
  spr.setTextColor(wifiOk ? TFT_GREEN : TFT_RED, TFT_BLACK);
  spr.drawString(wifiOk ? "WIFI" : "NO WIFI", STATUS_X, STATUS_Y, 1);

  // Aircraft actually drawn, with the MLAT subset in brackets. The bracket
  // is dropped at zero rather than showing "(0)" — MLAT is a couple of
  // percent of traffic, so a permanent zero would be noise most of the time.
  char buf[16];
  if (mlatOnScreen > 0)
    snprintf(buf, sizeof(buf), "AC %d (%d)", onScreen, mlatOnScreen);
  else
    snprintf(buf, sizeof(buf), "AC %d", onScreen);
  spr.setTextColor(s.fetchOk ? TFT_WHITE : TFT_ORANGE, TFT_BLACK);
  spr.drawString(buf, STATUS_X, STATUS_Y + 10, 1);

  // Feed staleness is shown ONLY when there is something wrong. A healthy
  // age counter reads 0s or 2s permanently, which is noise that trains you
  // to stop reading the corner at all — so nothing is drawn until the feed
  // has actually missed several polls.
  //
  // Split across two lines because "NO UPDATES FOR 20s" is 108px on one, and
  // the corner is only 64px before it starts covering the scope.
  if (!s.lastFetchMs) { // never had a successful poll since boot
    spr.setTextColor(TFT_ORANGE, TFT_BLACK);
    spr.drawString("NO UPDATES", STATUS_X, STATUS_Y + 20, 1);
    spr.drawString("YET", STATUS_X, STATUS_Y + 30, 1);
    return;
  }
  uint32_t ageS = (millis() - s.lastFetchMs) / 1000;
  if (ageS < STALE_WARN_S) return; // healthy: draw nothing at all
  // Red once aircraft start being dropped outright rather than just dimmed —
  // past that point the scope is actively emptying, not merely lagging.
  spr.setTextColor(ageS >= (uint32_t)radar::SEEN_DROP_S ? TFT_RED : TFT_ORANGE,
                   TFT_BLACK);
  spr.drawString("NO UPDATES", STATUS_X, STATUS_Y + 20, 1);
  snprintf(buf, sizeof(buf), "FOR %lus",
           (unsigned long)(ageS > 999 ? 999 : ageS));
  spr.drawString(buf, STATUS_X, STATUS_Y + 30, 1);
}
