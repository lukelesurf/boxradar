#include "scope.h"
#include "side_panel.h"
#include "projection.h"
#include "config.h"
#include <math.h>
#include <stdio.h>

static constexpr int SCOPE_MARGIN = 6; // outer ring inset from sprite edge

static void drawRings(TFT_eSprite &spr, float rangeNmOuter, float pxPerNm) {
  for (int i = 1; i <= 2; i++) { // rings at 1/2 and full range
    int r = (int)(pxPerNm * rangeNmOuter * i / 2.0f);
    spr.drawCircle(SCOPE_CX, SCOPE_CY, r, TFT_DARKGREEN);
  }
  // Range legend, bottom-left of scope
  char buf[10];
  snprintf(buf, sizeof(buf), "%.0fnm", rangeNmOuter);
  spr.setTextColor(TFT_GREEN, TFT_BLACK);
  spr.drawString(buf, 4, SCOPE_H - 12, 1);
  // Home marker
  spr.drawLine(SCOPE_CX - 4, SCOPE_CY, SCOPE_CX + 4, SCOPE_CY, TFT_GREEN);
  spr.drawLine(SCOPE_CX, SCOPE_CY - 4, SCOPE_CX, SCOPE_CY + 4, TFT_GREEN);
}

static void drawBlip(TFT_eSprite &spr, const radar::Aircraft &a, bool selected) {
  bool dim = a.seenS > radar::SEEN_DIM_S;
  uint16_t col = selected ? TFT_YELLOW : (dim ? TFT_DARKGREY : TFT_CYAN);
  spr.fillCircle(a.sx, a.sy, 2, col);
  // Heading vector: 6px + 1px per 30kt, in track direction (north-up scope)
  float rad = a.trackDeg * (float)M_PI / 180.0f;
  int len = 6 + a.gsKt / 30;
  spr.drawLine(a.sx, a.sy, a.sx + (int)(sinf(rad) * len),
               a.sy - (int)(cosf(rad) * len), col);
  if (selected) spr.drawCircle(a.sx, a.sy, 6, TFT_YELLOW);
  // Label: callsign, else last 4 of hex
  char label[9];
  if (a.callsign[0])
    snprintf(label, sizeof(label), "%s", a.callsign);
  else
    snprintf(label, sizeof(label), "%04lx", (unsigned long)(a.hex & 0xFFFF));
  spr.setTextColor(dim ? TFT_DARKGREY : TFT_SILVER, TFT_BLACK);
  spr.drawString(label, a.sx + 5, a.sy + 3, 1);
}

void drawScope(TFT_eSprite &spr, radar::AircraftStore &s, const UiState &ui) {
  spr.fillSprite(TFT_BLACK);
  float rangeOuter = RANGES_NM[ui.rangeIdx];
  float pxPerNm = (float)(SCOPE_CX - SCOPE_MARGIN) / rangeOuter;
  drawRings(spr, rangeOuter, pxPerNm);
  for (int i = s.count - 1; i >= 0; i--) { // draw far->near so near wins overlap
    radar::Aircraft &a = s.list[i];
    int sx = SCOPE_CX + (int)(a.pos.x * pxPerNm);
    int sy = SCOPE_CY - (int)(a.pos.y * pxPerNm);
    if (sx < 0 || sx >= SCOPE_W || sy < 0 || sy >= SCOPE_H) {
      a.sx = a.sy = -1000; // off-scope: not tappable
      continue;
    }
    a.sx = (int16_t)sx;
    a.sy = (int16_t)sy;
    // Trails: oldest->newest as dimming dots behind the blip
    for (int t = 0; t < a.trailLen; t++) {
      int idx = (a.trailHead - a.trailLen + t + 2 * radar::TRAIL_LEN) %
                radar::TRAIL_LEN;
      radar::Vec2 tp = radar::project(HOME_LAT, HOME_LON, a.trail[idx].lat,
                                      a.trail[idx].lon);
      int tx = SCOPE_CX + (int)(tp.x * pxPerNm);
      int ty = SCOPE_CY - (int)(tp.y * pxPerNm);
      if (tx < 0 || tx >= SCOPE_W || ty < 0 || ty >= SCOPE_H) continue;
      // 3 brightness steps oldest->newest
      uint16_t col = t < a.trailLen / 3       ? 0x18E3   // very dark grey
                     : t < (2 * a.trailLen) / 3 ? TFT_DARKGREY
                                                : 0x8410; // mid grey
      spr.drawPixel(tx, ty, col);
      if (t >= (2 * a.trailLen) / 3) spr.drawPixel(tx + 1, ty, col);
    }
    drawBlip(spr, a, ui.selectedHex != 0 && a.hex == ui.selectedHex);
  }
}

void drawDetailPanel(TFT_eSprite &spr, const radar::AircraftStore &s,
                     const UiState &ui) {
  if (!ui.detailOpen || ui.selectedHex == 0) return;
  const radar::Aircraft *a = s.findByHex(ui.selectedHex);
  if (!a) return;
  constexpr int W = 150, H = 92, X = 4, Y = SCOPE_H - H - 16;
  spr.fillRect(X, Y, W, H, TFT_BLACK);
  spr.drawRect(X, Y, W, H, TFT_YELLOW);
  spr.setTextColor(TFT_YELLOW, TFT_BLACK);
  char l1[24];
  snprintf(l1, sizeof(l1), "%s  %06lx",
           a->callsign[0] ? a->callsign : "(no cs)", (unsigned long)a->hex);
  spr.drawString(l1, X + 4, Y + 4, 2);
  spr.setTextColor(TFT_WHITE, TFT_BLACK);
  char alt[8], line[26];
  formatAltitude(alt, sizeof(alt), a->altFt, a->onGround);
  snprintf(line, sizeof(line), "%-4s  %s  %ukt", a->type[0] ? a->type : "-",
           alt, a->gsKt);
  spr.drawString(line, X + 4, Y + 26, 1);
  snprintf(line, sizeof(line), "trk %u", a->trackDeg);
  spr.drawString(line, X + 4, Y + 40, 1);
  snprintf(line, sizeof(line), "%.1fnm brg %.0f", (double)a->range,
           (double)radar::bearingDeg(a->pos));
  spr.drawString(line, X + 4, Y + 54, 1);
  snprintf(line, sizeof(line), "rssi %.1f  seen %.0fs", (double)a->rssi,
           (double)a->seenS);
  spr.drawString(line, X + 4, Y + 68, 1);
}
