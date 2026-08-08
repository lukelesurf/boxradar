#include "net_task.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <string.h>
#include "config.h"
#include "geo_store.h"
#include "parse.h"
#include "metar.h"
#include "shared_state.h"
#include "status_led.h"

using radar::AircraftStore;

// WiFi.status() reports WL_CONNECTED before DHCP has bound an address, so the
// first fetch after boot fails with a connection error every time. Harmless
// for the 60s weather poll; expensive for the 10-minute geography poll, where
// it would mean ten minutes on a possibly stale cache after every reboot.
static bool netReady() {
  return WiFi.status() == WL_CONNECTED && WiFi.localIP() != INADDR_NONE;
}

static AircraftStore s_staging;
static AircraftStore s_prev;

// Started lazily, the first time WiFi is up — not just at boot — so a board
// that fails the 15s boot-time WiFi wait still becomes OTA-flashable once
// WiFi eventually connects (previously it stayed unflashable until a power
// cycle). setupOta() itself is not idempotent (ArduinoOTA.begin() etc.), so
// the caller guards it with a one-shot latch.
static void setupOta() {
  ArduinoOTA.setHostname(OTA_HOSTNAME); // registers boxradar.local via mDNS
  ArduinoOTA.setPassword(OTA_PASSWORD);

  // No tft calls here: the UI task (core 1) owns all drawing after boot to
  // avoid a cross-core SPI race with these callbacks (core 0, via
  // ArduinoOTA.handle() below). Progress is published through
  // g_otaActive/g_otaProgress and rendered by ui_task.cpp.
  ArduinoOTA.onStart([]() {
    // ArduinoOTA's _runUpdate read/write loop doesn't yield, which can
    // starve the core-0 IDLE0 task long enough to trip the task watchdog
    // mid-transfer; disable it for the duration and re-enable on error
    // (success reboots before onEnd returns, so no need to re-enable there).
    disableCore0WDT();
    g_otaProgress = 0;
    g_otaActive = true; // pause everything else while flash is being written
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    g_otaProgress = (uint8_t)((uint64_t)progress * 100 / total);
  });
  ArduinoOTA.onEnd([]() {
    // No visual needed here — the board reboots immediately after.
  });
  ArduinoOTA.onError([](ota_error_t error) {
    g_otaActive = false;
    enableCore0WDT();
    Serial.printf("OTA error %u\n", error);
  });

  ArduinoOTA.begin();
}

static void printTable(const AircraftStore &s) {
#ifdef BOXRADAR_SERIAL_TABLES
  Serial.printf("---- %d aircraft, heap %u ----\n", s.count,
                esp_get_free_heap_size());
  Serial.println("hex    callsign type   lat      lon     alt   gs trk seen  rssi  rng");
  for (int i = 0; i < s.count; i++) {
    const radar::Aircraft &a = s.list[i];
    Serial.printf("%06lx %-8s %-4s %8.4f %8.4f %5ld %3u %3u %4.1f %5.1f %5.1f\n",
                  (unsigned long)a.hex, a.callsign, a.type, a.lat, a.lon,
                  (long)a.altFt, a.gsKt, a.trackDeg, a.seenS, a.rssi, a.range);
  }
#else
  (void)s;
#endif
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
      int n = radar::loadStore(doc, s_staging, s_prev, HOME_LAT, HOME_LON,
                               g_trailSpacingNm);
#ifdef BOXRADAR_FAKE_ALERT
      // Test hook. Real 7700s are a handful a year, so the banner, the
      // flashing blip and the tier-0 datablock placement would otherwise be
      // unverifiable — and an alert path nobody has ever seen work is an
      // alert path you cannot trust. Stamps the nearest aircraft:
      //   PLATFORMIO_BUILD_FLAGS=-DBOXRADAR_FAKE_ALERT pio run -e ota -t upload
      // Re-flash without the flag to restore normal behaviour.
      if (s_staging.count > 0)
        strncpy(s_staging.list[0].squawk, "7700",
                sizeof(s_staging.list[0].squawk));
#endif
      s_staging.lastFetchMs = millis();
      s_staging.fetchOk = true;
      s_prev = s_staging;
      publishStore(s_staging);
      printTable(s_staging);
      // Heap-margin instrumentation: feed size vs kept (post range-cap) vs
      // free/minimum-ever-free heap, so a slow leak or transient OOM under
      // load shows up in a 45s serial capture without needing the full table.
      Serial.printf("feed=%d kept=%d heap=%u minheap=%u\n",
                    (int)doc["aircraft"].size(), n, esp_get_free_heap_size(),
                    esp_get_minimum_free_heap_size());
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

#ifdef METAR_ENABLED
// Weather is strictly decorative: any failure leaves the previously
// published Metar in place, and a board that has never reached the feed
// simply shows no weather. Nothing here may disturb the aircraft path.
static void pollMetar() {
  static radar::Metar s_metar; // retained across calls, so a failed fetch
                               // keeps the last good reading and its age
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(3000);
  http.useHTTP10(true);
  http.begin(METAR_URL);
  int code = http.GET();
  if (code == HTTP_CODE_OK) {
    JsonDocument doc; // ~300 bytes on the wire; no filter needed
    DeserializationError err = deserializeJson(doc, http.getStream());
    if (!err) {
      if (radar::loadMetar(doc, METAR_STATION, s_metar)) {
        s_metar.lastFetchMs = millis();
        publishMetar(s_metar);
      } else {
        // printf, not literal concatenation: METAR_STATION is now an
        // expression reading the runtime config, not a string literal.
        Serial.printf("metar: station %s not in feed\n", METAR_STATION);
      }
    } else {
      Serial.printf("metar parse error: %s\n", err.c_str());
    }
  } else {
    Serial.printf("metar http error: %d\n", code);
  }
  http.end();
}
#endif

static void netTaskLoop(void *) {
  uint32_t lastPoll = 0;
  for (;;) {
    static bool otaStarted = false;
    if (!otaStarted && WiFi.status() == WL_CONNECTED) {
      setupOta();
      otaStarted = true;
    }
    if (otaStarted) ArduinoOTA.handle();
    if (!g_otaActive && netReady() &&
        millis() - lastPoll >= POLL_INTERVAL_MS) {
      lastPoll = millis();
      poll();
    }
#ifdef GEO_ENABLED
    // Geography is fetched once WiFi is up and then only occasionally: it is a
    // per-site file that changes when you regenerate it, not live data. Same
    // discipline as the weather below — its own cadence and its own `if`, so a
    // slow fetch can never delay traffic or the OTA handler.
    static uint32_t lastGeo = 0;
    if (!g_otaActive && netReady() &&
        (lastGeo == 0 || millis() - lastGeo >= GEO_POLL_INTERVAL_MS)) {
      lastGeo = millis();
      geoStoreRefresh();
    }
#endif
#ifdef METAR_ENABLED
    // Deliberately a separate cadence and a separate `if`, not folded into
    // the aircraft poll: a slow or hanging weather fetch must never delay
    // traffic, which is the thing the display exists to show.
    static uint32_t lastMetar = 0;
    if (!g_otaActive && netReady() &&
        (lastMetar == 0 || millis() - lastMetar >= METAR_POLL_INTERVAL_MS)) {
      lastMetar = millis();
      pollMetar();
    }
#endif
    if (WiFi.status() != WL_CONNECTED)
      statusLedSet(LedStatus::NoWifi);
    else if (!s_prev.fetchOk || millis() - s_prev.lastFetchMs > 10000)
      statusLedSet(LedStatus::NoData);
    else
      statusLedSet(LedStatus::Ok);
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

void startNetTask() {
  // Mounting LittleFS and opening the cached blob does no network work, so it
  // happens before the task starts rather than racing WiFi.
  geoStoreBegin();

  xTaskCreatePinnedToCore(netTaskLoop, "net", 12288, nullptr, 2, nullptr, 0);
}
