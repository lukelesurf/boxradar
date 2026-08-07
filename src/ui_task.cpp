#include "ui_task.h"
#include <Arduino.h>
#include "night_mode.h"
#include "shared_state.h"
#include "ui/layout.h"
#include "ui/scope.h"
#include "ui/touch_input.h"

TFT_eSPI tft;
static TFT_eSprite s_scope(&tft);
static radar::AircraftStore s_snap;
static radar::Metar s_metar;
static UiState s_ui;

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
  // Night mode scales on top of the LDR result and deliberately bypasses
  // BL_MIN_DUTY — that floor exists so the display is never unreadably dim
  // in a dark room, which is the opposite of what is wanted at 3am.
  ledcWrite(BL_CHANNEL, (int)(duty * nightScale));
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
      // Fully dark: skip the sprite build and the 153KB SPI push entirely,
      // but keep polling touch so a tap can still wake it. The tap is
      // consumed here rather than passed to touchInputPoll, so waking the
      // display never also opens a detail panel for whatever was underneath.
      if (touchInputTapped()) nightModeWake();
      backlightUpdate(nightScale);
      vTaskDelay(pdMS_TO_TICKS(UI_FRAME_MS));
      continue;
    }
    // Published before rendering so a range change reaches the net task by
    // the next poll; existing points keep their old spacing until the ring
    // refills, which self-corrects within a few polls.
    g_trailSpacingNm = trailSpacingNm(s_ui.rangeIdx);
    snapshotStore(s_snap);
    snapshotMetar(s_metar);
    drawScope(s_scope, s_snap, s_metar, s_ui); // fills sx/sy for this frame
    // Any interaction during night hours extends the wake window, so poking
    // around at 3am doesn't have the screen die under your finger.
    if (touchInputPoll(s_ui, s_snap)) nightModeWake();
    if (s_ui.selectedHex && !s_snap.findByHex(s_ui.selectedHex)) {
      // selected aircraft aged out of the snapshot: clear stale selection
      s_ui.selectedHex = 0;
      s_ui.detailOpen = false;
    }
    // Selection highlight now lags one frame behind a fresh tap (drawScope
    // already ran); the detail panel below reflects the tap immediately.
    drawDetailPanel(s_scope, s_snap, s_ui);
    s_scope.pushSprite(0, 0);
    backlightUpdate(nightScale);
    vTaskDelay(pdMS_TO_TICKS(UI_FRAME_MS));
  }
}

void startUiTask() {
  xTaskCreatePinnedToCore(uiTaskLoop, "ui", 8192, nullptr, 2, nullptr, 1);
}
