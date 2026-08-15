#include "status_bar.h"
#include "palette.h"
#include "format.h"
#include <Arduino.h>
#include <WiFi.h>
#include <stdio.h>
#include <string.h>

// Five missed polls at POLL_INTERVAL_MS=2000. Long enough that ordinary WiFi
// jitter or a single slow response never trips it, short enough that a truly
// dead feed is called out well before aircraft start ageing off the scope.
static constexpr uint32_t STALE_WARN_S = 10;
// Weather older than this is not worth asserting; METARs are half-hourly and
// the Pi refreshes every 5 minutes, so 20 means the feed itself has died.
static constexpr uint32_t METAR_STALE_S = 20 * 60;
// Below this a ceiling means you will not see anything overhead, which for a
// look-out-of-the-window toy is the single most actionable number here.
static constexpr uint16_t LOW_CEILING_FT = 1500;

static constexpr int CH_W = 6;
static constexpr int TEXT_Y = STATUS_Y + 1;

// Zoom hit zone: the drawn range readout, grown to something a finger can
// actually hit. Starts empty so no tap can land on it before the first frame.
static constexpr int ZOOM_ZONE_H = 24, ZOOM_ZONE_PAD = 8;
static HitRect s_rangeHit = {0, 0, 0, 0};

HitRect statusRangeHitZone() { return s_rangeHit; }

// Drawn, not typed: font 1's tick/cross glyphs are codepage-dependent and a
// wrong one reads as corruption. Two lines each, and unambiguous at 7px.
static void drawTick(TFT_eSprite &spr, int x, uint16_t col) {
  spr.drawLine(x, STATUS_Y + 4, x + 2, STATUS_Y + 7, col);
  spr.drawLine(x + 2, STATUS_Y + 7, x + 6, STATUS_Y + 1, col);
}

static void drawCross(TFT_eSprite &spr, int x, uint16_t col) {
  spr.drawLine(x, STATUS_Y + 1, x + 6, STATUS_Y + 7, col);
  spr.drawLine(x + 6, STATUS_Y + 1, x, STATUS_Y + 7, col);
}

// Advances x past whatever it drew, so segments compose without any caller
// having to know how wide the previous one was.
static void seg(TFT_eSprite &spr, int &x, const char *text, uint16_t col) {
  spr.setTextColor(col, TFT_BLACK);
  spr.drawString(text, x, TEXT_Y, 1);
  x += (int)strlen(text) * CH_W;
}

static void sep(TFT_eSprite &spr, int &x) {
  seg(spr, x, " - ", BLOCK_TEXT_DIM);
}

void drawStatusCorner(TFT_eSprite &spr, const radar::AircraftStore &s,
                      const radar::Metar &metar, int onScreen,
                      int mlatOnScreen, float rangeNm) {
  spr.fillRect(0, STATUS_Y, SCOPE_W, STATUS_H, TFT_BLACK);
  char buf[24];
  int x = STATUS_X;

  bool wifiOk = WiFi.status() == WL_CONNECTED;
  if (wifiOk)
    drawTick(spr, x, TFT_GREEN);
  else
    drawCross(spr, x, TFT_RED);
  x += 7 + CH_W;

  // Traffic count, or the staleness warning in its place. Sharing the slot
  // rather than adding one keeps the strip to a single line, and a stale
  // feed makes the count meaningless anyway.
  uint32_t ageS = s.lastFetchMs ? (millis() - s.lastFetchMs) / 1000 : 0;
  if (!s.lastFetchMs) {
    seg(spr, x, "NO DATA YET", TFT_ORANGE);
  } else if (ageS >= STALE_WARN_S) {
    snprintf(buf, sizeof(buf), "NO UPDATE %lus",
             (unsigned long)(ageS > 999 ? 999 : ageS));
    seg(spr, x, buf,
        ageS >= (uint32_t)radar::seenAgeing().dropS ? TFT_RED : TFT_ORANGE);
  } else {
    if (mlatOnScreen > 0)
      snprintf(buf, sizeof(buf), "AC %d (%d)", onScreen, mlatOnScreen);
    else
      snprintf(buf, sizeof(buf), "AC %d", onScreen);
    seg(spr, x, buf, s.fetchOk ? TFT_WHITE : TFT_ORANGE);

    // How many contacts the receiver had that the cap dropped. Shown only
    // when it is actually dropping some, so the strip stays quiet in the
    // normal case. The README describes the cap as a silent cliff; this is
    // the whole reason the feed carries a pre-cap total.
    //
    // Deliberately not folded into the AC count: that one is what is ON
    // SCREEN after the viewport cull, and the dropped ones are the farthest,
    // most of which were never drawable anyway. Two different denominators,
    // so two different numbers.
    if (s.feedTotal > (uint16_t)s.count) {
      snprintf(buf, sizeof(buf), " +%d", (int)(s.feedTotal - s.count));
      seg(spr, x, buf, BLOCK_TEXT_DIM);
    }
  }

  sep(spr, x);
  int rangeX = x;
  snprintf(buf, sizeof(buf), "%.0fnm", (double)rangeNm);
  seg(spr, x, buf, TFT_GREEN);
  s_rangeHit = {rangeX - ZOOM_ZONE_PAD, SCOPE_H - ZOOM_ZONE_H,
                (x - rangeX) + 2 * ZOOM_ZONE_PAD, ZOOM_ZONE_H};

  // Weather is optional and never allowed to break the rest of the line.
  if (!metar.valid) return;
  uint32_t mAgeS =
      metar.lastFetchMs ? (millis() - metar.lastFetchMs) / 1000 : 0;
  if (mAgeS > METAR_STALE_S) return; // silently drop rather than mislead

  if (metar.runway[0]) {
    sep(spr, x);
    // Trailing "?" when the wind is too light to be choosing the runway —
    // the value is still the best guess, just not an assertion.
    snprintf(buf, sizeof(buf), "%s %s%s", metar.station, metar.runway,
             metar.runwayConfident ? "" : "?");
    seg(spr, x, buf, metar.runwayConfident ? TFT_CYAN : BLOCK_TEXT);
  }

  sep(spr, x);
  radar::formatWind(buf, sizeof(buf), metar);
  seg(spr, x, buf, BLOCK_TEXT);

  sep(spr, x);
  radar::formatCloud(buf, sizeof(buf), metar);
  bool lowCloud = metar.ceilFt > 0 && metar.ceilFt < LOW_CEILING_FT;
  seg(spr, x, buf, lowCloud ? TYPE_INTERESTING : BLOCK_TEXT);

  // Visibility only when it is actually restricted; 9999 every day is noise.
  if (metar.visM < 5000) {
    sep(spr, x);
    snprintf(buf, sizeof(buf), "%um", (unsigned)metar.visM);
    seg(spr, x, buf, TYPE_INTERESTING);
  }
}

void drawHoldToRestart(TFT_eSprite &spr, float progress) {
  if (progress < 0.0f) progress = 0.0f;
  if (progress > 1.0f) progress = 1.0f;

  spr.fillRect(0, STATUS_Y, SCOPE_W, STATUS_H, TFT_BLACK);
  spr.setTextColor(TFT_ORANGE, TFT_BLACK);
  spr.drawString("HOLD TO RESTART", 2, TEXT_Y, 1);

  // The bar takes the right-hand half of the strip. Drawn as an outline that
  // fills, so at a glance you can see both how far along it is and how far
  // there is left to go — a bare filling block tells you only the former.
  const int x0 = 96, x1 = SCOPE_W - 2;
  const int y0 = STATUS_Y + 2, h = STATUS_H - 4;
  spr.drawRect(x0, y0, x1 - x0, h, TFT_ORANGE);
  int fill = (int)((float)(x1 - x0 - 2) * progress);
  if (fill > 0) spr.fillRect(x0 + 1, y0 + 1, fill, h - 2, TFT_ORANGE);
}
