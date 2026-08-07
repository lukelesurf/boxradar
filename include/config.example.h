// Copy to include/config.h and fill in. config.h is git-ignored.
#pragma once

#define WIFI_SSID "your-ssid"
#define WIFI_PASS "your-password"

// readsb/tar1090 receiver. Fallback: "http://<host>:8080/data/aircraft.json"
#define RECEIVER_URL "http://receiver.lan/tar1090/data/aircraft.json"

// Scope centre
#define HOME_LAT 51.5000
#define HOME_LON -0.1000

#define OTA_HOSTNAME "boxradar"
#define OTA_PASSWORD "change-me"

#define POLL_INTERVAL_MS 2000

// Optional weather, published by tools/metar-feed on the receiver Pi.
// Comment out METAR_URL to disable — the status line simply omits the
// weather segments and everything else carries on.
#define METAR_URL "http://receiver.lan/metar.json"
#define METAR_STATION "EGSS"
// METARs are issued half-hourly and the Pi refreshes every 5 minutes, so
// there is nothing to gain from polling this hard.
#define METAR_POLL_INTERVAL_MS 60000
