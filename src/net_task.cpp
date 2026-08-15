#include "net_task.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <string.h>
#include "config.h"
#include "config_server.h"
#include "contact_feed.h"
#include "geo_store.h"
#include "metar.h"
#include "operator_name.h"
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

// Set when the Pi says a new map has been published, cleared when the geo
// branch runs. The 10-minute poll stays as the fallback: this signal rides one
// response and a board that was rebooting, off, or off-wifi when it went out
// simply never hears it — and a map that never updates, with nothing to say
// so, is worse than one that updates late.
static volatile bool s_geoDue = false;

void geoStoreRefreshSoon() { s_geoDue = true; }

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

// The whole traffic payload, in .bss. Fixed size and never reallocated: the
// point of moving filtering to the Pi was that this allocation stops being a
// function of how many aircraft are airborne, and a heap buffer here would
// hand that property straight back.
static uint8_t s_payload[radar::CONTACT_MAX_PAYLOAD];

// A failed poll leaves the previous store on screen but marks it not-ok, so
// the status strip ages it rather than the scope silently freezing.
static void pollFailed(const char *what, int detail) {
  Serial.printf("contacts: %s (%d)\n", what, detail);
  s_prev.fetchOk = false;
  publishStore(s_prev);
}

static void poll() {
  // Home goes on the request rather than into the Pi's config: NVS is the
  // single authority for where "here" is, so the service holds no site
  // position and cannot silently disagree with the board about it.
  //
  // The altitude band rides here too, for the same reason and one more: the
  // 32-slot cap saturates continuously, so filtering behind it would spend
  // every slot and then hide most of them. The Pi filters before it sorts and
  // caps, which makes the 32 the nearest 32 IN the band.
  //
  // Worst case is 65 characters of query — the +88 is measured against that,
  // not guessed, and the truncation check below is what makes a future field
  // fail loudly instead of silently dropping a filter or mangling n=.
  char url[radar::CFG_URL_LEN + 88];
  int wrote = snprintf(url, sizeof(url),
                       "%s?lat=%.6f&lon=%.6f&n=%d&amin=%u&amax=%u&mlat=%u",
                       RECEIVER_URL, (double)HOME_LAT, (double)HOME_LON,
                       (int)radar::MAX_AIRCRAFT, (unsigned)ALT_MIN_FT,
                       (unsigned)ALT_MAX_FT, (unsigned)(MLAT_ON ? 1 : 0));
  if (wrote < 0 || (size_t)wrote >= sizeof(url)) {
    // snprintf truncates rather than overflowing, so this is not a crash — it
    // is a request missing its tail, which the Pi would answer with a 400 and
    // no explanation the board could act on. Say so once per poll instead.
    pollFailed("request url too long for its buffer", wrote);
    return;
  }

  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(3000);
  // HTTP/1.0 disables chunked transfer, so Content-Length is always present
  // and the body can be read in one go against a known size.
  http.useHTTP10(true);
  http.begin(url);
  // The Pi asks for the settings server on a RESPONSE HEADER of this poll,
  // never in the payload. The contact format is fixed-size with no reserved
  // field, so a flag byte would have meant bumping CONTACT_VERSION — and
  // loadContacts() rejects an unknown version outright, which would blank the
  // scope on any board not reflashed in step with the Pi. An unrecognised
  // header costs old firmware nothing at all.
  //
  // Static, because collectHeaders() keeps the pointer rather than copying.
  static const char *WANTED[] = {"X-Boxradar-Config", "X-Boxradar-Geo"};
  http.collectHeaders(WANTED, 2);
  int code = http.GET();
  // Both checked BEFORE the status check, deliberately. The Pi answers 503
  // when the receiver is unreachable, and a broken readsb must not also cost
  // you the ability to configure the board or to publish it a map — it is
  // still polling and still on the network, which is everything these need.
  if (http.header("X-Boxradar-Config").length() > 0) configServerOpen();
  // Does NOT fetch here. Geography gets its own cadence and its own `if` in
  // the task loop precisely so a slow blob fetch can never delay traffic;
  // reaching into the contact poll to do one would undo that. This only makes
  // the next loop iteration due.
  if (http.header("X-Boxradar-Geo").length() > 0) geoStoreRefreshSoon();
  if (code != HTTP_CODE_OK) {
    pollFailed("http error", code);
    http.end();
    return;
  }

  int size = http.getSize();
  if (size < 0 || size > (int)sizeof(s_payload)) {
    // Refused rather than truncated. An oversized body means the service is
    // sending more than this build's MAX_AIRCRAFT, which is a version
    // mismatch to be reported, not a payload to salvage.
    pollFailed("bad content length", size);
    http.end();
    return;
  }

  size_t got = http.getStreamPtr()->readBytes(s_payload, (size_t)size);
  http.end();
  if (got != (size_t)size) {
    pollFailed("short read", (int)got);
    return;
  }

  radar::ContactStatus status =
      radar::loadContacts(s_payload, got, s_staging, s_prev, HOME_LAT,
                          HOME_LON, g_trailSpacingNm);
  if (status != radar::CONTACT_OK) {
    Serial.printf("contacts: %s\n", radar::contactStatusName(status));
    s_prev.fetchOk = false;
    publishStore(s_prev);
    return;
  }

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
  // Heap-margin instrumentation. `feed` is now what the receiver had before
  // the Pi's cap, so feed>kept is the cap binding — the thing the README
  // called a silent cliff. `bytes` is the whole traffic allocation, which
  // should no longer move with traffic at all.
  Serial.printf("feed=%u kept=%d bytes=%d heap=%u minheap=%u\n",
                s_staging.feedTotal, s_staging.count, size,
                esp_get_free_heap_size(), esp_get_minimum_free_heap_size());
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

// Resolves the selected aircraft's type designator to a name the Pi holds and
// the board cannot: 2,806 entries, far past what this flash has spare. Strictly
// decorative, like the weather — a failure leaves the panel showing the
// designator on its own, which is what it showed before this existed.
//
// Event-driven rather than polled: it runs only while something is selected
// and unanswered. pendingTypeName() owns the retry spacing, so this stays a
// cheap check on a 50ms loop rather than a request storm.
static void pollTypeName() {
  char designator[8];
  if (!pendingTypeName(designator, sizeof(designator))) return;

  char url[160];
  if (!radar::typeNameUrl(RECEIVER_URL, designator, url, sizeof(url))) {
    // Refused rather than failed: a designator that cannot form a URL will
    // never form one, so retrying it would burn all three attempts on a fact
    // already known. Answer it as nameless and move on.
    publishTypeName(designator, "");
    return;
  }

  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(3000);
  http.useHTTP10(true);
  http.begin(url);
  int code = http.GET();
  if (code == HTTP_CODE_OK) {
    JsonDocument doc; // one small object; the response is under 100 bytes
    DeserializationError err = deserializeJson(doc, http.getStream());
    char name[radar::TYPE_NAME_LEN];
    if (!err && radar::loadTypeName(doc, designator, name, sizeof(name))) {
      // Publishes even when `name` is empty. The Pi echoes every id it was
      // asked about, so no name means the database has nothing for this
      // designator — a definitive answer, and asking again would never
      // produce a different one.
      publishTypeName(designator, name);
    } else {
      Serial.printf("type: unexpected answer for %s\n", designator);
      failTypeName(designator);
    }
  } else {
    // Includes the 503 a Pi with no database returns, which is the case that
    // may come good later — hence a retry rather than a nameless answer.
    Serial.printf("type: http error %d for %s\n", code, designator);
    failTypeName(designator);
  }
  http.end();
}

// The operator behind the selected aircraft's callsign. Same machinery and the
// same gating as pollTypeName(), against the second of the two lookup slots —
// a tap wants both answers, so sharing one slot would have them evicting each
// other every time you selected an aircraft.
//
// Two round trips per tap rather than one combined endpoint. At the rate a
// person taps a 320px panel that is free, and keeping them separate means
// /type stays exactly what it was and each answer arrives as soon as it can
// rather than at the speed of the slower lookup.
static void pollOperator() {
  char code[8];
  if (!pendingOperator(code, sizeof(code))) return;

  char url[160];
  if (!radar::operatorUrl(RECEIVER_URL, code, url, sizeof(url))) {
    // A code that cannot form a URL never will, so this is answered as unknown
    // rather than retried — the same reasoning as the designator case.
    publishOperator(code, "", "");
    return;
  }

  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(3000);
  http.useHTTP10(true);
  http.begin(url);
  int code_ = http.GET();
  if (code_ == HTTP_CODE_OK) {
    JsonDocument doc; // one small object; the response is under 120 bytes
    DeserializationError err = deserializeJson(doc, http.getStream());
    char name[radar::OPERATOR_NAME_LEN];
    char radio[radar::OPERATOR_RADIO_LEN];
    if (!err && radar::loadOperatorName(doc, code, name, sizeof(name), radio,
                                        sizeof(radio))) {
      // Published even when empty: the Pi echoes every id it was asked about,
      // so no name means the table has nothing for this code and never will.
      publishOperator(code, name, radio);
    } else {
      Serial.printf("operator: unexpected answer for %s\n", code);
      failOperator(code);
    }
  } else {
    // Includes the 503 a Pi with no database returns, which may come good.
    Serial.printf("operator: http error %d for %s\n", code_, code);
    failOperator(code);
  }
  http.end();
}

static void netTaskLoop(void *) {
  uint32_t lastPoll = 0;
  for (;;) {
    static bool otaStarted = false;
    if (!otaStarted && WiFi.status() == WL_CONNECTED) {
      setupOta();
      otaStarted = true;
    }
    if (otaStarted) ArduinoOTA.handle();
    // Cheap when closed (one null check), and outside the OTA guard on
    // purpose: if a flash is in progress the window should expire rather than
    // sit open behind it.
    configServerHandle();
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
    if (GEO_ON && !g_otaActive && netReady() &&
        (lastGeo == 0 || s_geoDue || millis() - lastGeo >= GEO_POLL_INTERVAL_MS)) {
      lastGeo = millis();
      s_geoDue = false;
      geoStoreRefresh();
    }
#endif
#ifdef METAR_ENABLED
    // Deliberately a separate cadence and a separate `if`, not folded into
    // the aircraft poll: a slow or hanging weather fetch must never delay
    // traffic, which is the thing the display exists to show.
    static uint32_t lastMetar = 0;
    if (METAR_ON && !g_otaActive && netReady() &&
        (lastMetar == 0 || millis() - lastMetar >= METAR_POLL_INTERVAL_MS)) {
      lastMetar = millis();
      pollMetar();
    }
#endif
    // Its own `if` for the same reason as the two above: a slow name lookup
    // must not delay traffic. No cadence of its own, though — this one is
    // driven by what the UI task has selected, and does nothing at all until
    // somebody taps an aircraft.
    if (!g_otaActive && netReady()) pollTypeName();
    if (!g_otaActive && netReady()) pollOperator();
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
