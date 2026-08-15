#include "ui_task.h"
#include <Arduino.h>
#include <string.h>
#include <time.h>
// Required for the BOXRADAR_* feature guards below, and for the siteConfig()
// accessors the night settings read through. Without it those #ifdefs silently
// compile to nothing — the build succeeds and the feature just never runs,
// which is a far worse failure than a link error.
#include "config.h"
#include "night_mode.h"
#include "ui/palette.h"
#include "shared_state.h"
#include "ui/layout.h"
#include "geo_store.h"
#include "ui/scope.h"
#include "ui/status_bar.h"
#include "ui/touch_input.h"
#include "hold_gesture.h"
#include "operator_name.h"
#include "ui/viewport.h"

TFT_eSPI tft;
static TFT_eSprite s_scope(&tft);
static radar::AircraftStore s_snap;
static radar::Metar s_metar;
static UiState s_ui;
// Hold anywhere for three seconds to restart. Duration is the only
// interaction axis this panel has left — position is fully spoken for by the
// tap table in touch_input.h, and a 4-wire resistive panel has no second
// finger to offer. Costs no pixels at rest: the countdown borrows the status
// strip, which is drawn every frame anyway.
static constexpr uint32_t HOLD_HINT_MS = 500, HOLD_RESTART_MS = 3000;
static radar::HoldGesture s_hold(HOLD_HINT_MS, HOLD_RESTART_MS);
static UiState s_uiBeforeHold;
static int s_lastClockMin = -1;

static constexpr int LDR_PIN = 34;
static constexpr int BL_PIN = 21;
static constexpr int BL_CHANNEL = 0;
static constexpr int BL_MIN_DUTY = 40; // never fully dark
// Empirical calibration, this unit, 2026-08-04: ambient room light and a
// direct torch both read raw≈0 (LDR divider swings over a tiny ADC range
// on this board); fully covered/dark reads raw jittering 0-129, smoothed
// settles ~25-38. The only usable signal is near-darkness, so map that
// narrow band to the full duty range instead of the theoretical 0-4095.
static constexpr int LDR_DARK = 35;

static void backlightInit() {
  ledcSetup(BL_CHANNEL, 5000, 8);
  ledcAttachPin(BL_PIN, BL_CHANNEL); // takes over from TFT_eSPI's digital HIGH
  ledcWrite(BL_CHANNEL, 255);
  analogSetPinAttenuation(LDR_PIN, ADC_11db);
}

static constexpr uint32_t UI_FRAME_MS = 100; // ~10 fps

#ifdef BOXRADAR_FRAME_TIME
// Frame budget instrument. Build with:
//   PLATFORMIO_BUILD_FLAGS=-DBOXRADAR_FRAME_TIME pio run -e ota -t upload
//
// Splits the two halves that get conflated when guessing about performance:
// R is building the sprite (the geometry — coastline, airspace, blips,
// datablocks), P is pushing it over SPI to the panel. Only R responds to
// anything we can optimise in the draw code; P is a fixed 153.6KB transfer.
//
// Exponentially smoothed, because raw per-frame figures at 10fps are
// unreadable, and shows the PREVIOUS frame's numbers — the overlay has to be
// drawn into the sprite before the sprite can be pushed.
static float s_renderUs = 0.0f, s_pushUs = 0.0f;

static void drawFrameTime(TFT_eSprite &spr) {
  char buf[24];
  snprintf(buf, sizeof(buf), "R%.1f P%.1f", s_renderUs / 1000.0f,
           s_pushUs / 1000.0f);
  int w = (int)strlen(buf) * 6;
  spr.setTextColor(TFT_MAGENTA, TFT_BLACK); // obviously a debug overlay
  spr.drawString(buf, SCOPE_W - w - 3, 3, 1);
}
#endif

static void backlightUpdate(float nightScale) {
  // CYD LDR: bright ambient -> low reading. Smooth + invert into duty.
  // Starts assuming ambient light, so boot is full-bright; a dark room
  // converges to the dimmed duty within ~3s of the exponential filter.
  static float smoothed = 0.0f;
  smoothed += 0.1f * ((float)analogRead(LDR_PIN) - smoothed);
  // Calibrated to LDR_DARK (see comment above) rather than the full 0-4095
  // ADC range — map()'s output is already clamped to [BL_MIN_DUTY, 255]
  // since the input is constrained to [0, LDR_DARK] first, so the old
  // trailing constrain() is redundant and dropped.
  int duty = map(constrain((int)smoothed, 0, LDR_DARK), 0, LDR_DARK, 255,
                 BL_MIN_DUTY);
  // Interpolate toward the night duty rather than scaling the LDR result.
  // The idle target is absolute and deliberately below BL_MIN_DUTY — that
  // floor exists so the display is never unreadably dim in a dark room,
  // which is the opposite of what is wanted at 3am.
  int idle = nightModeIdleDuty();
  ledcWrite(BL_CHANNEL, idle + (int)((duty - idle) * nightScale));
}

// Font 7 is the 7-segment face, already compiled in via LOAD_FONT7. At
// textSize 2 it is 96px tall — about 40% of the panel — and "00:00" comes
// to roughly 288px wide, which fits 320 with a little margin.
static void drawNightClock(TFT_eSprite &spr, const struct tm *lt) {
  spr.fillSprite(TFT_BLACK);
  char buf[8];
  if (lt)
    snprintf(buf, sizeof(buf), "%02d:%02d", lt->tm_hour, lt->tm_min);
  else
    snprintf(buf, sizeof(buf), "--:--"); // no NTP yet: say so, don't guess
  spr.setTextColor(NIGHT_CLOCK_COLOUR, TFT_BLACK);
  spr.setTextSize(2);
  spr.setTextDatum(MC_DATUM);
  spr.drawString(buf, SCOPE_W / 2, SCOPE_H / 2, 7);
  // Restore: every other drawString in the codebase assumes top-left datum
  // and size 1, and these persist on the sprite across frames.
  spr.setTextDatum(TL_DATUM);
  spr.setTextSize(1);
}

// Non-destructive probe for the planned full-screen (320x240) layout: the
// two current sprites total 76.8KB but in two chunks, and full-screen needs
// that as ONE contiguous block. This board already fails a 115KB contiguous
// alloc (see the 16-bit fallback below), so 76.8KB is an open question.
// Allocates, reports, frees — leaves the running layout untouched.
// 8-bit only. 16-bit at 320x240 would want 153.6KB and this board's largest
// contiguous block is ~110KB (measured on-device 2026-08-07: 110580 B free,
// 76800 B needed, 33.7KB headroom). No banded fallback for the same reason —
// the margin is comfortable, so a second render path would be dead code.
static void createScopeSprite() {
  uint32_t before = esp_get_free_heap_size();
  s_scope.setColorDepth(8);
  if (s_scope.createSprite(SCOPE_W, SCOPE_H) == nullptr) {
    Serial.println("FATAL: no scope sprite");
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_RED, TFT_BLACK);
    tft.drawString("FATAL: scope sprite alloc", 10, 100, 2);
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
  }
  Serial.printf("scope sprite: heap %u -> %u\n", before,
                esp_get_free_heap_size());
}

static void uiTaskLoop(void *) {
  createScopeSprite();
  backlightInit();
  touchInputInit(); // keeps all touch-SPI traffic on core 1
  tft.fillScreen(TFT_BLACK);
  bool otaScreenDrawn = false; // latch: draw the OTA frame/title once, not every iteration
  for (;;) {
    if (g_otaActive) {
      // UI task owns all drawing, including OTA progress — the callbacks in
      // main.cpp (core 0) never touch tft, so there's no cross-core race.
      if (!otaScreenDrawn) {
        tft.fillScreen(TFT_BLACK);
        tft.setTextColor(TFT_YELLOW, TFT_BLACK);
        tft.drawString("OTA update", 10, 90, 4);
        tft.drawRect(10, 140, 300, 20, TFT_WHITE);
        otaScreenDrawn = true;
      }
      uint8_t pct = g_otaProgress;
      tft.fillRect(12, 142, (296 * pct) / 100, 16, TFT_GREEN);
      vTaskDelay(pdMS_TO_TICKS(50)); // smoother bar while flashing
      continue;
    }
    if (otaScreenDrawn) {
      // Fell out of OTA (error path — success reboots before we get here).
      // Clear once so normal rendering resumes on a clean screen.
      tft.fillScreen(TFT_BLACK);
      otaScreenDrawn = false;
    }
    float nightScale = nightModeUpdate(UI_FRAME_MS);
    if (nightModeDark()) {
      // Night: keep polling touch so a tap can still wake it. The tap is
      // consumed here rather than passed to touchInputPoll, so waking the
      // display never also opens a detail panel for whatever was underneath.
      if (touchInputTapped()) nightModeWake();
      if (nightModeClockOn()) {
        // Redraw only when the minute actually changes, so the saving from
        // skipping the radar render survives almost intact — one 38ms push a
        // minute instead of ten a second.
        time_t now = time(nullptr);
        struct tm lt;
        bool haveTime = now > 1700000000 && localtime_r(&now, &lt) != nullptr;
        int minuteNow = haveTime ? lt.tm_hour * 60 + lt.tm_min : -1;
        if (minuteNow != s_lastClockMin) {
          s_lastClockMin = minuteNow;
          drawNightClock(s_scope, haveTime ? &lt : nullptr);
          s_scope.pushSprite(0, 0);
        }
      }
      backlightUpdate(nightScale);
      vTaskDelay(pdMS_TO_TICKS(UI_FRAME_MS));
      continue;
    }
    s_lastClockMin = -1; // awake: force a redraw when night resumes
    snapshotStore(s_snap);
    snapshotMetar(s_metar);
    // Built once per frame into a local and passed to everything that needs
    // it, rather than stored on UiState. That is deliberate: a follow-a-
    // selected-aircraft state would make the centre a function of the current
    // store, and this is the shape that admits it without touching a single
    // draw site. See docs/viewport-design.md.
    Viewport vp = viewportFor(s_ui, s_snap);
    // Published before rendering so a range change reaches the net task by
    // the next poll; existing points keep their old spacing until the ring
    // refills, which self-corrects within a few polls.
    g_trailSpacingNm = trailSpacingNm(vp.rangeNm);
#ifdef BOXRADAR_FRAME_TIME
    uint32_t t0 = micros();
#endif
    // Held for the frame that reads the map. geoblob is zero-copy, so every
    // airspace outline and town label drawn below is a pointer into the blob
    // buffer that the net task may be about to free — see geoStoreLock().
    // The store only ever holds this for pointer assignments, so the wait is
    // microseconds even when a swap lands mid-frame.
    geoStoreLock();
    drawScope(s_scope, s_snap, s_metar, s_ui, vp); // fills sx/sy for this frame
    geoStoreUnlock();
    // Any interaction during night hours extends the wake window, so poking
    // around at 3am doesn't have the screen die under your finger. Hit-tested
    // against the viewport the frame above was drawn with, which is the one
    // the finger was actually aiming at.
    // Captured before the poll, because the poll mutates it. Touch is
    // edge-triggered, so the first touch of a long press has already fired
    // its ordinary tap action (a zoom) by the time the hold is knowable —
    // cancelling the hold has to put that back.
    UiState beforePress = s_ui;
    if (touchInputPoll(s_ui, s_snap, vp)) {
      nightModeWake();
      s_uiBeforeHold = beforePress;
    }
    switch (s_hold.update(touchInputHeldMs())) {
    case radar::HOLD_HINTING:
      drawHoldToRestart(s_scope, s_hold.progress(touchInputHeldMs()));
      break;
    case radar::HOLD_CANCELLED:
      s_ui = s_uiBeforeHold;  // undo the zoom the press edge caused
      break;
    case radar::HOLD_FIRED: {
      // One last frame so the panel says what is about to happen, rather than
      // going black with no explanation.
      drawHoldToRestart(s_scope, 1.0f);
      s_scope.pushSprite(0, 0);
      Serial.println("ui: hold-to-restart fired");
      delay(400);
      ESP.restart();
      break;
    }
    default:
      break;
    }
    if (s_ui.selectedHex && !s_snap.findByHex(s_ui.selectedHex)) {
      // selected aircraft aged out of the snapshot: clear stale selection
      s_ui.selectedHex = 0;
      s_ui.detailOpen = false;
    }
    // Ask the Pi what the selected aircraft's type designator means. Every
    // frame, deliberately: requestTypeName() is a no-op for an unchanged
    // designator, so this is a string compare at 10fps rather than a fetch,
    // and expressing it as "what is selected right now" avoids having to
    // detect the several ways a selection can change.
    if (s_ui.detailOpen && s_ui.selectedHex) {
      const radar::Aircraft *sel = s_snap.findByHex(s_ui.selectedHex);
      if (sel && sel->type[0]) requestTypeName(sel->type);
      // The operator, from the callsign's three-letter prefix. Silently does
      // nothing for a registration or an empty callsign, which is most GA
      // traffic — operatorCodeFrom() refuses anything that is not three
      // letters then a digit, precisely so a registration cannot resolve to
      // somebody else's airline.
      char code[8];
      if (sel && radar::operatorCodeFrom(sel->callsign, code, sizeof(code)))
        requestOperator(code);
    }
    // Selection highlight now lags one frame behind a fresh tap (drawScope
    // already ran); the detail panel below reflects the tap immediately.
    drawDetailPanel(s_scope, s_snap, s_ui);
#ifdef BOXRADAR_FRAME_TIME
    uint32_t t1 = micros();
    drawFrameTime(s_scope);
    s_scope.pushSprite(0, 0);
    uint32_t t2 = micros();
    // Unsigned subtraction survives the ~71 minute micros() wrap.
    s_renderUs += 0.1f * ((float)(t1 - t0) - s_renderUs);
    s_pushUs += 0.1f * ((float)(t2 - t1) - s_pushUs);
#else
    s_scope.pushSprite(0, 0);
#endif
    backlightUpdate(nightScale);
    vTaskDelay(pdMS_TO_TICKS(UI_FRAME_MS));
  }
}

void startUiTask() {
  xTaskCreatePinnedToCore(uiTaskLoop, "ui", 8192, nullptr, 2, nullptr, 1);
}
