#include "ui_task.h"
#include <Arduino.h>
#include "shared_state.h"
#include "ui/layout.h"
#include "ui/scope.h"
#include "ui/side_panel.h"
#include "ui/touch_input.h"

TFT_eSPI tft;
static TFT_eSprite s_scope(&tft);
static TFT_eSprite s_panel(&tft);
static bool s_panelSpriteOk = false;
static radar::AircraftStore s_snap;
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

static void backlightUpdate() {
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
  ledcWrite(BL_CHANNEL, duty);
}

static void createScopeSprite() {
  uint32_t before = esp_get_free_heap_size();
  s_scope.setColorDepth(16);
  if (s_scope.createSprite(SCOPE_W, SCOPE_H) == nullptr) {
    // RAM budget fallback per spec: 8-bit palette sprite (57KB vs 115KB)
    Serial.println("16-bit scope sprite failed, falling back to 8-bit");
    s_scope.setColorDepth(8);
    if (s_scope.createSprite(SCOPE_W, SCOPE_H) == nullptr) {
      Serial.println("FATAL: no scope sprite");
      for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
  }
  Serial.printf("scope sprite: heap %u -> %u\n", before,
                esp_get_free_heap_size());
}

static void createPanelSprite() {
  uint32_t before = esp_get_free_heap_size();
  s_panel.setColorDepth(8);
  if (s_panel.createSprite(LIST_W, 240) == nullptr) {
    Serial.println("panel sprite failed, direct drawing retained");
    s_panelSpriteOk = false;
    return;
  }
  s_panelSpriteOk = true;
  Serial.printf("panel sprite: heap %u -> %u\n", before,
                esp_get_free_heap_size());
}

static void uiTaskLoop(void *) {
  createScopeSprite();
  createPanelSprite();
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
    snapshotStore(s_snap);
    touchInputPoll(s_ui, s_snap);
    if (s_ui.selectedHex && !s_snap.findByHex(s_ui.selectedHex)) {
      // selected aircraft aged out of the snapshot: clear stale selection
      s_ui.selectedHex = 0;
      s_ui.detailOpen = false;
    }
    drawScope(s_scope, s_snap, s_ui);
    drawDetailPanel(s_scope, s_snap, s_ui);
    s_scope.pushSprite(0, 0);
    if (s_panelSpriteOk) {
      drawSidePanel(s_panel, s_snap, s_ui);
      s_panel.pushSprite(LIST_X, 0);
    }
    // else: panel sprite alloc failed at startup — skip rendering rather
    // than draw with wrong (0-based) coordinates on the real screen.
    backlightUpdate();
    vTaskDelay(pdMS_TO_TICKS(100)); // ~10 fps
  }
}

void startUiTask() {
  xTaskCreatePinnedToCore(uiTaskLoop, "ui", 8192, nullptr, 2, nullptr, 1);
}
