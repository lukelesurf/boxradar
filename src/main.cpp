// Boot + OTA. Brings up wifi/OTA and boot status text, then hands the TFT
// off to the UI task (ui_task.cpp) and the net task for the rest of runtime.
#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include "config.h"
#include "shared_state.h"
#include "net_task.h"
#include "ui_task.h"

// XPT2046 on its own SPI bus (shares no pins with the TFT)
constexpr int TOUCH_CLK = 25;
constexpr int TOUCH_CS = 33;
constexpr int TOUCH_MOSI = 32;
constexpr int TOUCH_MISO = 39;
constexpr int TOUCH_IRQ = 36;

constexpr uint32_t WIFI_TIMEOUT_MS = 15000;

SPIClass touchSpi(VSPI);
XPT2046_Touchscreen touch(TOUCH_CS, TOUCH_IRQ);

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

void setupOta() {
  ArduinoOTA.setHostname(OTA_HOSTNAME); // registers boxradar.local via mDNS
  ArduinoOTA.setPassword(OTA_PASSWORD);

  // No tft calls here: the UI task (core 1) owns all drawing after boot to
  // avoid a cross-core SPI race with these callbacks (core 0, via
  // ArduinoOTA.handle() in the net task). Progress is published through
  // g_otaActive/g_otaProgress and rendered by ui_task.cpp.
  ArduinoOTA.onStart([]() {
    g_otaActive = true; // pause everything else while flash is being written
    g_otaProgress = 0;
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    g_otaProgress = (uint8_t)((uint64_t)progress * 100 / total);
  });
  ArduinoOTA.onEnd([]() {
    // No visual needed here — the board reboots immediately after.
  });
  ArduinoOTA.onError([](ota_error_t error) {
    g_otaActive = false;
    Serial.printf("OTA error %u\n", error);
  });

  ArduinoOTA.begin();
}

void setup() {
  Serial.begin(115200);

  tft.init();
  tft.setRotation(1); // landscape, 320x240

  touchSpi.begin(TOUCH_CLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
  touch.begin(touchSpi);
  touch.setRotation(1);

  setupWifi();
  if (WiFi.status() == WL_CONNECTED) {
    setupOta();
  }

  sharedStateInit();
  startNetTask();
  Serial.printf("free heap after net start: %u\n", esp_get_free_heap_size());
  startUiTask();
}

void loop() {
  // Everything runs in FreeRTOS tasks; Arduino loop just idles.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
