#include "ui_task.h"
#include <Arduino.h>
#include "shared_state.h"
#include "ui/layout.h"
#include "ui/side_panel.h"

TFT_eSPI tft;
static TFT_eSprite s_scope(&tft);
static radar::AircraftStore s_snap;
static UiState s_ui;

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

static void uiTaskLoop(void *) {
  createScopeSprite();
  tft.fillScreen(TFT_BLACK);
  for (;;) {
    if (g_otaActive) { // OTA owns flash + screen; go quiet
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    snapshotStore(s_snap);
    s_scope.fillSprite(TFT_BLACK);
    // Placeholder centre marker until Task 6 draws the real scope
    s_scope.drawLine(SCOPE_CX - 4, SCOPE_CY, SCOPE_CX + 4, SCOPE_CY, TFT_GREEN);
    s_scope.drawLine(SCOPE_CX, SCOPE_CY - 4, SCOPE_CX, SCOPE_CY + 4, TFT_GREEN);
    s_scope.pushSprite(0, 0);
    drawSidePanel(tft, s_snap, s_ui);
    vTaskDelay(pdMS_TO_TICKS(100)); // ~10 fps
  }
}

void startUiTask() {
  xTaskCreatePinnedToCore(uiTaskLoop, "ui", 8192, nullptr, 2, nullptr, 1);
}
