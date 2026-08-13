#include "touch_input.h"
#include "status_bar.h"
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
static uint32_t s_downAtMs = 0;

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

// Shared press-edge detector. Both callers consume the same edge, but only
// one of them runs in any given frame — dark frames never reach the full
// poll, and lit frames never call the tap-only path.
static bool pressEdge() {
  bool down = s_touch.touched();
  if (!down) { s_wasDown = false; s_downAtMs = 0; return false; }
  if (s_wasDown) return false; // act on press edge only
  s_wasDown = true;
  s_downAtMs = millis();
  return true;
}

uint32_t touchInputHeldMs() {
  // Reads the state pressEdge() maintains rather than polling the panel
  // again: touch is on its own SPI bus but a second transaction per frame
  // would be pure waste, and the caller always runs pressEdge() first.
  if (!s_wasDown || s_downAtMs == 0) return 0;
  uint32_t held = millis() - s_downAtMs;
  // Never report zero while a finger is genuinely down — zero is the "nothing
  // pressed" signal to HoldGesture, and on the press-edge frame the elapsed
  // time really is zero.
  return held == 0 ? 1 : held;
}

bool touchInputTapped() { return pressEdge(); }

bool touchInputPoll(UiState &ui, const radar::AircraftStore &s,
                    const Viewport &vp) {
  if (!pressEdge()) return false;

  TS_Point p = s_touch.getPoint();
  int x = map(constrain((int)p.x, RAW_X_MIN, RAW_X_MAX), RAW_X_MIN, RAW_X_MAX, 0, 319);
  int y = map(constrain((int)p.y, RAW_Y_MIN, RAW_Y_MAX), RAW_Y_MIN, RAW_Y_MAX, 0, 239);

  if (ui.detailOpen) {
    // Any tap dismisses the panel AND drops the selection. The highlight has
    // no meaning once the panel is closed — leaving it set stranded a yellow
    // blip on the scope with no gesture to clear it.
    ui.detailOpen = false;
    ui.selectedHex = 0;
    return true;
  }

  if (ui.view == ViewState::OVERVIEW) {
    // Every tap zooms; blips are not hit-tested at all. The centre comes from
    // inverting the tap through the overview transform, which is also why it
    // can never land outside the generated map — the interaction bounds
    // itself geometrically and no clamping is needed.
    //
    // Except on the home marker, which snaps: that is how you get back to a
    // true home-centred view, and the cross drawn at the centre is its own
    // affordance. See detailCentreForTap().
    ui.detailCentre = detailCentreForTap(vp, x, y);
    ui.detailRangeIdx = 0; // always arrive at the wider detail scale
    ui.view = ViewState::DETAIL;
    return true;
  }

  // Detail. The zoom toggle is checked first so it stays a single tap even
  // when a blip happens to be sitting over the status strip.
  if (statusRangeHitZone().contains(x, y)) {
    ui.detailRangeIdx = (ui.detailRangeIdx + 1) % N_DETAIL_RANGES;
    return true;
  }
  const radar::Aircraft *hit = nearestBlip(s, x, y);
  if (hit) {
    ui.selectedHex = hit->hex;
    ui.detailOpen = true;
  } else {
    ui.view = ViewState::OVERVIEW;
    ui.selectedHex = 0; // no selection survives into overview
  }
  return true;
}
