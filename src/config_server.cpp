#include "config_server.h"
#include <Arduino.h>
#include <ArduinoJson.h>
#include <WebServer.h>
#include <WiFi.h>
#include "device_config.h"
#include "geo_store.h"
#include "site_config.h"

namespace {

WebServer *s_server = nullptr;
uint32_t s_closeAt = 0;
uint32_t s_restartAt = 0;

// Why the board last restarted, in words. Without serial access this is the
// only way to answer "it reset and I do not know why" — and the answers are
// very different diagnoses: a brownout is the power supply, a panic or a
// watchdog is firmware, and a software reset is an intended restart such as
// the one a settings save performs.
const char *resetReasonName() {
  switch (esp_reset_reason()) {
  case ESP_RST_POWERON: return "power on";
  case ESP_RST_EXT: return "external reset";
  case ESP_RST_SW: return "software restart";
  case ESP_RST_PANIC: return "panic or exception";
  case ESP_RST_INT_WDT: return "interrupt watchdog";
  case ESP_RST_TASK_WDT: return "task watchdog";
  case ESP_RST_WDT: return "other watchdog";
  case ESP_RST_DEEPSLEEP: return "deep sleep wake";
  case ESP_RST_BROWNOUT: return "brownout (power)";
  case ESP_RST_SDIO: return "sdio";
  default: return "unknown";
  }
}

// What the Pi renders its form from. Reporting the SOURCE alongside the value
// is the point of this endpoint: a key sitting in NVS shadows its compiled
// default permanently, so "7, from NVS" and "7, compiled in" are different
// facts even though they are the same number. Without that distinction the
// UI's "use built-in default" control would have nothing to act on.
void handleRead() {
  JsonDocument doc;

  // Health, not configuration. Cheap to gather and it is the only view of the
  // board's condition that does not need a USB cable — minimum-free heap in
  // particular is the number that says whether a reset was memory pressure.
  JsonObject health = doc["health"].to<JsonObject>();
  health["uptime_s"] = millis() / 1000;
  health["reset_reason"] = resetReasonName();
  health["heap_free"] = ESP.getFreeHeap();
  health["heap_min"] = esp_get_minimum_free_heap_size();
  health["rssi"] = WiFi.RSSI();
  // The geography store's own account of its last load. Every way a published
  // map can fail to appear ends here and nowhere else: a rejected CRC, a home
  // that does not match, a malloc that failed because the swap needs the old
  // blob and the new one live at once. Without this the symptom is "I
  // published and nothing changed", with no way to tell which.
  health["geo"] = geoStoreStatus();

  JsonObject fields = doc["fields"].to<JsonObject>();
  for (size_t i = 0; i < radar::DEVICE_FIELD_COUNT; i++) {
    const radar::DeviceField &f = radar::DEVICE_FIELDS[i];
    JsonObject entry = fields[f.key].to<JsonObject>();
    if (f.kind == radar::DEV_STR) {
      const char *v = siteConfigReadStr(f.key);
      entry["value"] = v ? v : "";
    } else {
      uint32_t v = 0;
      siteConfigReadU32(f.key, &v);
      entry["value"] = v;
    }
    entry["source"] = siteConfigHasOverride(f.key) ? "nvs" : "default";
  }
  String body;
  serializeJson(doc, body);
  s_server->send(200, "application/json", body);
}

// Writes are validated here as well as on the Pi. The Pi is not a trusted
// component — it is an unauthenticated service on the same LAN — and a bound
// enforced only in the UI is not enforced at all.
void handleWrite() {
  JsonDocument doc;
  JsonArray problems = doc["problems"].to<JsonArray>();
  int written = 0, cleared = 0;

  for (int i = 0; i < s_server->args(); i++) {
    String name = s_server->argName(i);
    String value = s_server->arg(i);

    if (name == "clear") {
      const radar::DeviceField *f = radar::deviceFieldByKey(value.c_str());
      if (!f) {
        problems.add(String("unknown key: ") + value);
        continue;
      }
      if (siteConfigClearKey(f->key)) cleared++;
      continue;
    }

    const radar::DeviceField *f = radar::deviceFieldByKey(name.c_str());
    if (!f) {
      // Refused rather than ignored. A key the firmware does not know is
      // either a version mismatch or something that should never have been
      // sent, and both are worth seeing.
      problems.add(String("unknown key: ") + name);
      continue;
    }

    uint32_t parsed = 0;
    const char *problem = radar::deviceFieldProblem(*f, value.c_str(), &parsed);
    if (problem) {
      problems.add(String(f->key) + ": " + problem);
      continue;
    }

    bool ok = (f->kind == radar::DEV_STR)
                  ? siteConfigSetString(f->key, value.c_str())
                  : siteConfigSetU32(f->key, parsed);
    if (ok) written++;
    else problems.add(String(f->key) + ": could not be stored");
  }

  doc["written"] = written;
  doc["cleared"] = cleared;
  // Only restart if something actually changed. A save that turned out to be
  // a no-op must not cost the scope five seconds of darkness.
  bool restarting = (written + cleared) > 0;
  doc["restarting"] = restarting;

  String body;
  serializeJson(doc, body);
  s_server->send(200, "application/json", body);
  Serial.printf("cfgsrv: wrote %d, cleared %d, %d problem(s)\n", written,
                cleared, (int)problems.size());

  if (restarting) {
    // Deferred so the response reaches the Pi before the socket dies. Same
    // reason portal.cpp delays before ESP.restart().
    s_restartAt = millis() + 500;
  }
}

// Restarting is the workaround for a map that will not load: a fresh heap is
// unfragmented, so the fetch that failed succeeds on the next boot. Offered
// here as well as by the hold gesture because the Device page is where you
// find out you need it — the geo status above says so in words.
void handleRestart() {
  s_server->send(200, "application/json", "{\"restarting\":true}");
  Serial.println("cfgsrv: restart requested");
  s_restartAt = millis() + 500;  // let the response flush first
}

void handleOther() {
  s_server->send(404, "application/json", "{\"error\":\"not found\"}");
}

void closeServer() {
  if (!s_server) return;
  s_server->stop();
  delete s_server;
  s_server = nullptr;
  Serial.println("cfgsrv: window closed");
}

} // namespace

void configServerOpen() {
  s_closeAt = millis() + CONFIG_SERVER_WINDOW_MS;
  if (s_server) return;  // already up; the line above extended the window
  if (WiFi.status() != WL_CONNECTED) return;

  s_server = new WebServer(80);
  s_server->on("/config", HTTP_GET, handleRead);
  s_server->on("/config", HTTP_POST, handleWrite);
  s_server->on("/restart", HTTP_POST, handleRestart);
  s_server->onNotFound(handleOther);
  s_server->begin();
  Serial.printf("cfgsrv: listening on http://%s/config for %us\n",
                WiFi.localIP().toString().c_str(),
                (unsigned)(CONFIG_SERVER_WINDOW_MS / 1000));
}

void configServerHandle() {
  if (s_restartAt && (int32_t)(millis() - s_restartAt) >= 0) {
    Serial.println("cfgsrv: restarting to apply settings");
    closeServer();
    ESP.restart();
  }
  if (!s_server) return;
  s_server->handleClient();
  // Signed comparison so the 49-day millis() wrap cannot leave the window
  // open forever, which is the failure mode `millis() > s_closeAt` would have.
  if ((int32_t)(millis() - s_closeAt) >= 0) closeServer();
}

bool configServerActive() { return s_server != nullptr; }
