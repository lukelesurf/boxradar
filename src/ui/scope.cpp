#include "scope.h"
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
    drawBlip(spr, a, ui.selectedHex != 0 && a.hex == ui.selectedHex);
  }
}
