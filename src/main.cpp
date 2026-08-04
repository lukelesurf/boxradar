// Milestone 1+5: hello screen + OTA. TFT colours, touch coords, ArduinoOTA
// with on-screen progress. Dual-core task split comes with the data layer.
#include <Arduino.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include "config.h"

// XPT2046 on its own SPI bus (shares no pins with the TFT)
constexpr int TOUCH_CLK = 25;
constexpr int TOUCH_CS = 33;
constexpr int TOUCH_MOSI = 32;
constexpr int TOUCH_MISO = 39;
constexpr int TOUCH_IRQ = 36;

constexpr uint32_t WIFI_TIMEOUT_MS = 15000;

TFT_eSPI tft;
SPIClass touchSpi(VSPI);
XPT2046_Touchscreen touch(TOUCH_CS, TOUCH_IRQ);

bool otaActive = false;

void drawTestPattern() {
  // Colour bars: if red/blue are swapped or colours inverted, flip the
  // driver/inversion build flags in platformio.ini (batch variant).
  const uint16_t bars[] = {TFT_RED, TFT_GREEN, TFT_BLUE, TFT_WHITE, TFT_BLACK};
  const char *names[] = {"RED", "GREEN", "BLUE", "WHITE", "BLACK"};
  const int w = tft.width() / 5;
  for (int i = 0; i < 5; i++) {
    tft.fillRect(i * w, 0, w, 160, bars[i]);
    tft.setTextColor(i == 4 ? TFT_WHITE : TFT_BLACK, bars[i]);
    tft.drawString(names[i], i * w + 4, 70, 2);
  }
  tft.fillRect(0, 160, tft.width(), tft.height() - 160, TFT_BLACK);
  tft.setTextColor(TFT_GREEN, TFT_BLACK);
  tft.drawString("BOXRADAR v2 - hello screen", 10, 170, 2);
}

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

  ArduinoOTA.onStart([]() {
    otaActive = true; // pause everything else while flash is being written
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_YELLOW, TFT_BLACK);
    tft.drawString("OTA update", 10, 90, 4);
    tft.drawRect(10, 140, tft.width() - 20, 20, TFT_WHITE);
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    int w = (int)((uint64_t)progress * (tft.width() - 24) / total);
    tft.fillRect(12, 142, w, 16, TFT_GREEN);
  });
  ArduinoOTA.onEnd([]() {
    tft.setTextColor(TFT_GREEN, TFT_BLACK);
    tft.drawString("done - rebooting", 10, 170, 2);
  });
  ArduinoOTA.onError([](ota_error_t error) {
    otaActive = false;
    tft.setTextColor(TFT_RED, TFT_BLACK);
    char buf[24];
    snprintf(buf, sizeof(buf), "OTA error %u", error);
    tft.drawString(buf, 10, 170, 2);
    Serial.printf("OTA error %u\n", error);
  });

  ArduinoOTA.begin();
}

void setup() {
  Serial.begin(115200);

  tft.init();
  tft.setRotation(1); // landscape, 320x240
  drawTestPattern();

  touchSpi.begin(TOUCH_CLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
  touch.begin(touchSpi);
  touch.setRotation(1);

  setupWifi();
  if (WiFi.status() == WL_CONNECTED) {
    setupOta();
  }

  Serial.printf("free heap: %u\n", esp_get_free_heap_size());
}

void loop() {
  ArduinoOTA.handle();
  if (otaActive) {
    return; // no touch/TFT traffic while OTA owns the flash
  }

  if (touch.touched()) {
    TS_Point p = touch.getPoint(); // raw 0..4095
    Serial.printf("touch raw x=%d y=%d z=%d\n", p.x, p.y, p.z);
    tft.fillRect(0, 214, tft.width(), 26, TFT_BLACK);
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
    char buf[48];
    snprintf(buf, sizeof(buf), "raw x=%d y=%d z=%d", p.x, p.y, p.z);
    tft.drawString(buf, 10, 214, 2);
    delay(50);
  }
}
