// Boot + OTA. Brings up wifi/OTA and boot status text, then hands the TFT
// off to the UI task (ui_task.cpp) and the net task for the rest of runtime.
#include <Arduino.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include "config.h"
#include "shared_state.h"
#include "net_task.h"
#include "status_led.h"
#include "ui_task.h"

constexpr uint32_t WIFI_TIMEOUT_MS = 15000;

void drawStatus(const char *msg, uint16_t colour) {
  tft.fillRect(0, 190, tft.width(), 20, TFT_BLACK);
  tft.setTextColor(colour, TFT_BLACK);
  tft.drawString(msg, 10, 190, 2);
}

void setupWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(OTA_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  drawStatus("wifi: connecting...", TFT_YELLOW);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    char buf[48];
    snprintf(buf, sizeof(buf), "wifi: %s", WiFi.localIP().toString().c_str());
    drawStatus(buf, TFT_GREEN);
    Serial.printf("wifi connected: %s\n", WiFi.localIP().toString().c_str());
  } else {
    drawStatus("wifi: FAILED (OTA unavailable)", TFT_RED);
    Serial.println("wifi connect failed");
  }
}

void setup() {
  Serial.begin(115200);

  tft.init();
  tft.setRotation(1); // landscape, 320x240
  tft.fillScreen(TFT_BLACK); // clear stale GRAM contents from a prior boot

  statusLedInit();
  setupWifi();
  // OTA is started from the net task once WiFi is up (see net_task.cpp) —
  // that covers the case where WiFi connects after this boot-time wait.

  sharedStateInit();
  startNetTask();
  Serial.printf("free heap after net start: %u\n", esp_get_free_heap_size());
  startUiTask();
}

void loop() {
  // Everything runs in FreeRTOS tasks; Arduino loop just idles.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
