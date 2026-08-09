#include "portal.h"
#include <Arduino.h>
#include <TFT_eSPI.h>
#include <WebServer.h>
#include <WiFi.h>
#include "site_config.h"

extern TFT_eSPI tft;
void drawStatus(const char *msg, uint16_t colour);

namespace {

WebServer *s_server = nullptr;
bool s_saved = false;
bool s_tried = false;

// Field list, driving both the form and the POST handler so the two cannot
// disagree about names. `key` is the NVS key — see src/site_config.cpp, where
// they are treated as a wire format.
struct Field {
  const char *key;
  const char *label;
  char kind;  // 's' string, 'f' float, 'u' uint32
};

const Field FIELDS[] = {
    {"ssid", "WiFi network", 's'},
    {"pass", "WiFi password", 's'},
    {"recv", "Receiver aircraft.json URL", 's'},
    {"lat", "Home latitude", 'f'},
    {"lon", "Home longitude", 'f'},
    {"metar", "METAR proxy URL (optional)", 's'},
    {"station", "METAR station ICAO (optional)", 's'},
    {"geo", "Geography blob URL (optional)", 's'},
};
const size_t FIELD_COUNT = sizeof(FIELDS) / sizeof(FIELDS[0]);

void announce(const char *line1, const char *line2) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_CYAN, TFT_BLACK);
  tft.drawString("BOXRADAR SETUP", 10, 40, 4);
  tft.setTextColor(TFT_WHITE, TFT_BLACK);
  tft.drawString(line1, 10, 90, 2);
  tft.drawString(line2, 10, 115, 2);
  tft.setTextColor(TFT_DARKGREY, TFT_BLACK);
  tft.drawString("waiting 5 min, then carrying on", 10, 160, 2);
}

String formPage() {
  const radar::SiteConfig &c = siteConfig();
  String h = F("<!doctype html><meta name=viewport "
               "content='width=device-width,initial-scale=1'>"
               "<title>BOXRADAR setup</title>"
               "<style>body{font-family:system-ui;margin:1.5rem;max-width:34rem}"
               "label{display:block;margin:.8rem 0 .2rem;font-size:.9rem}"
               "input{width:100%;padding:.5rem;font-size:1rem;box-sizing:border-box}"
               "button{margin-top:1.2rem;padding:.7rem 1.2rem;font-size:1rem}"
               "p{color:#555;font-size:.85rem}</style>"
               "<h1>BOXRADAR setup</h1>"
               "<p>Each box shows the value currently in force. Fill in only "
               "the ones you want to change — a box left empty is not written "
               "at all, so anything you do not touch keeps working as it "
               "does now.</p>"
               "<form method=POST action=/save>");
  for (size_t i = 0; i < FIELD_COUNT; i++) {
    const Field &f = FIELDS[i];
    h += "<label for=" + String(f.key) + ">" + f.label + "</label>";
    h += "<input id=" + String(f.key) + " name=" + String(f.key);
    // Show what is in force as a PLACEHOLDER, never a value. A prefilled
    // `value` is submitted whether or not it was edited, so one save would
    // write all eight keys to NVS and every compiled default would be shadowed
    // forever — silently, since NVS wins and says nothing. That is exactly the
    // trap that cost a debugging cycle on 2026-08-09. The password is
    // deliberately not echoed at all.
    if (strcmp(f.key, "ssid") == 0) h += " placeholder='" + String(c.wifiSsid) + "'";
    else if (strcmp(f.key, "recv") == 0) h += " placeholder='" + String(c.receiverUrl) + "'";
    else if (strcmp(f.key, "lat") == 0) h += " placeholder='" + String(c.homeLat, 6) + "'";
    else if (strcmp(f.key, "lon") == 0) h += " placeholder='" + String(c.homeLon, 6) + "'";
    else if (strcmp(f.key, "metar") == 0) h += " placeholder='" + String(c.metarUrl) + "'";
    else if (strcmp(f.key, "station") == 0) h += " placeholder='" + String(c.metarStation) + "'";
    else if (strcmp(f.key, "geo") == 0) h += " placeholder='" + String(c.geoUrl) + "'";
    h += ">";
  }
  h += F("<button type=submit>Save and restart</button></form>");
  return h;
}

void handleRoot() { s_server->send(200, "text/html", formPage()); }

void handleSave() {
  int written = 0;
  String problems;
  for (size_t i = 0; i < FIELD_COUNT; i++) {
    const Field &f = FIELDS[i];
    if (!s_server->hasArg(f.key)) continue;
    String v = s_server->arg(f.key);
    v.trim();
    if (v.length() == 0) continue;  // blank means "keep the default"
    bool ok = false;
    switch (f.kind) {
    case 'f': ok = siteConfigSetFloat(f.key, v.toFloat()); break;
    case 'u': ok = siteConfigSetU32(f.key, (uint32_t)v.toInt()); break;
    default: ok = siteConfigSetString(f.key, v.c_str()); break;
    }
    if (ok) written++;
    else problems += String(f.key) + " ";
  }

  String body = F("<!doctype html><meta name=viewport "
                  "content='width=device-width,initial-scale=1'>"
                  "<style>body{font-family:system-ui;margin:1.5rem}</style>");
  if (problems.length()) {
    // Report rather than silently dropping: cfgSetStr refuses oversized values
    // instead of truncating, and a value that did not stick must not look
    // saved.
    body += "<h1>Partly saved</h1><p>Stored " + String(written) +
            " setting(s). These would not fit and were not stored: <b>" +
            problems + "</b></p><p><a href=/>Back</a></p>";
    s_server->send(200, "text/html", body);
    return;
  }
  body += "<h1>Saved</h1><p>Stored " + String(written) +
          " setting(s). Restarting now — this network will disappear.</p>";
  s_server->send(200, "text/html", body);
  Serial.printf("portal: saved %d setting(s), restarting\n", written);
  s_saved = true;
}

} // namespace

bool portalShouldRun(bool wifiConnected) {
#ifdef PORTAL_FORCE
  (void)wifiConnected;
  if (s_tried) return false;
  Serial.println("portal: forced by PORTAL_FORCE");
  return true;
#else
  // Only when association failed. A working board can never be pushed into the
  // portal by accident, which is what makes this safe to ship enabled.
  if (wifiConnected || s_tried) return false;
  return true;
#endif
}

void portalRun() {
  s_tried = true;
  s_saved = false;

  WiFi.mode(WIFI_AP);
  if (!WiFi.softAP(PORTAL_AP_SSID)) {
    Serial.println("portal: softAP failed, returning to STA");
    WiFi.mode(WIFI_STA);
    return;
  }
  IPAddress ip = WiFi.softAPIP();
  char l1[48], l2[48];
  snprintf(l1, sizeof(l1), "join wifi: %s", PORTAL_AP_SSID);
  snprintf(l2, sizeof(l2), "then open http://%s", ip.toString().c_str());
  announce(l1, l2);
  Serial.printf("portal: AP '%s' up at %s\n", PORTAL_AP_SSID,
                ip.toString().c_str());

  s_server = new WebServer(80);
  s_server->on("/", HTTP_GET, handleRoot);
  s_server->on("/save", HTTP_POST, handleSave);
  // Anything else goes to the form. Not a full captive-portal redirect — that
  // needs a DNS responder — but it means any path on the right host works, and
  // the panel is showing the address anyway.
  s_server->onNotFound(handleRoot);
  s_server->begin();

  uint32_t start = millis();
  while (!s_saved && millis() - start < PORTAL_TIMEOUT_MS) {
    s_server->handleClient();
    delay(10);
  }

  s_server->stop();
  delete s_server;
  s_server = nullptr;

  if (s_saved) {
    delay(500);  // let the response flush before the socket dies
    ESP.restart();
  }

  // Timed out. Tear the AP down and hand back in STA mode so the caller's
  // normal boot continues and the board becomes OTA-reachable again.
  Serial.println("portal: timed out, continuing in STA mode");
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  tft.fillScreen(TFT_BLACK);
}
