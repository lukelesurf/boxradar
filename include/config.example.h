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
