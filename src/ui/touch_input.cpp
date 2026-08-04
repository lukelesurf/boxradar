#include "touch_input.h"
#include <Arduino.h>
#include <SPI.h>
#include <XPT2046_Touchscreen.h>

// XPT2046 on its own SPI bus (shares no pins with the TFT)
static constexpr int TOUCH_CLK = 25, TOUCH_CS = 33, TOUCH_MOSI = 32,
                     TOUCH_MISO = 39, TOUCH_IRQ = 36;
// Raw ADC window -> screen px, landscape rotation 1. Verified on this
// board via milestone-1 raw dumps; tweak here if taps land offset.
static constexpr int RAW_X_MIN = 200, RAW_X_MAX = 3700;
static constexpr int RAW_Y_MIN = 240, RAW_Y_MAX = 3800;
static constexpr int TAP_RADIUS_PX = 20;

static SPIClass s_touchSpi(VSPI);
static XPT2046_Touchscreen s_touch(TOUCH_CS, TOUCH_IRQ);
static bool s_wasDown = false;

void touchInputInit() {
  s_touchSpi.begin(TOUCH_CLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
  s_touch.begin(s_touchSpi);
  s_touch.setRotation(1);
}

static const radar::Aircraft *nearestBlip(const radar::AircraftStore &s,
                                          int x, int y) {
  const radar::Aircraft *best = nullptr;
  int bestD2 = TAP_RADIUS_PX * TAP_RADIUS_PX;
  for (int i = 0; i < s.count; i++) {
    const radar::Aircraft &a = s.list[i];
    int dx = a.sx - x, dy = a.sy - y;
    int d2 = dx * dx + dy * dy;
    if (d2 <= bestD2) { bestD2 = d2; best = &a; }
  }
  return best;
}

void touchInputPoll(UiState &ui, const radar::AircraftStore &s) {
  bool down = s_touch.touched();
  if (!down) { s_wasDown = false; return; }
  if (s_wasDown) return; // act on press edge only
  s_wasDown = true;

  TS_Point p = s_touch.getPoint();
  int x = map(constrain((int)p.x, RAW_X_MIN, RAW_X_MAX), RAW_X_MIN, RAW_X_MAX, 0, 319);
  int y = map(constrain((int)p.y, RAW_Y_MIN, RAW_Y_MAX), RAW_Y_MIN, RAW_Y_MAX, 0, 239);

  if (ui.detailOpen) { // any tap dismisses the detail panel
    ui.detailOpen = false;
    return;
  }
  if (x >= LIST_X) { // traffic list: tap row selects
    int row = y / LIST_ROW_H;
    if (y < STATUS_Y && row < LIST_ROWS && row < s.count) {
      ui.selectedHex = s.list[row].hex;
      ui.detailOpen = true;
    }
    return;
  }
  const radar::Aircraft *hit = nearestBlip(s, x, y);
  if (hit) {
    ui.selectedHex = hit->hex;
    ui.detailOpen = true;
  } else {
    ui.rangeIdx = (ui.rangeIdx + 1) % N_RANGES; // background tap: cycle range
  }
}
