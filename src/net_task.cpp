#include "net_task.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include "config.h"
#include "parse.h"
#include "shared_state.h"

using radar::AircraftStore;

static AircraftStore s_staging;
static AircraftStore s_prev;

static void printTable(const AircraftStore &s) {
  Serial.printf("---- %d aircraft, heap %u ----\n", s.count,
                esp_get_free_heap_size());
  Serial.println("hex    callsign type   lat      lon     alt   gs trk seen  rssi  rng");
  for (int i = 0; i < s.count; i++) {
    const radar::Aircraft &a = s.list[i];
    Serial.printf("%06lx %-8s %-4s %8.4f %8.4f %5ld %3u %3u %4.1f %5.1f %5.1f\n",
                  (unsigned long)a.hex, a.callsign, a.type, a.lat, a.lon,
                  (long)a.altFt, a.gsKt, a.trackDeg, a.seenS, a.rssi, a.range);
  }
}

static void poll() {
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(3000);
  // HTTP/1.0 disables chunked transfer so ArduinoJson can stream-parse
  http.useHTTP10(true);
  http.begin(RECEIVER_URL);
  int code = http.GET();
  if (code == HTTP_CODE_OK) {
    JsonDocument filter;
    radar::buildAircraftFilter(filter);
    JsonDocument doc;
    DeserializationError err = deserializeJson(
        doc, http.getStream(), DeserializationOption::Filter(filter));
    if (!err) {
      radar::loadStore(doc, s_staging, s_prev, HOME_LAT, HOME_LON);
      s_staging.lastFetchMs = millis();
      s_staging.fetchOk = true;
      s_prev = s_staging;
      publishStore(s_staging);
      printTable(s_staging);
    } else {
      Serial.printf("parse error: %s\n", err.c_str());
      s_prev.fetchOk = false;
      publishStore(s_prev);
    }
  } else {
    Serial.printf("http error: %d\n", code);
    s_prev.fetchOk = false;
    publishStore(s_prev);
  }
  http.end();
}

static void netTaskLoop(void *) {
  uint32_t lastPoll = 0;
  for (;;) {
    ArduinoOTA.handle();
    if (!g_otaActive && WiFi.status() == WL_CONNECTED &&
        millis() - lastPoll >= POLL_INTERVAL_MS) {
      lastPoll = millis();
      poll();
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

void startNetTask() {
  xTaskCreatePinnedToCore(netTaskLoop, "net", 12288, nullptr, 2, nullptr, 0);
}
