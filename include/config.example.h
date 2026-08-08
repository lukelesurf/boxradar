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

// Draw the OSM coastline under everything else. Comment out to disable and
// drop the generated table (~12KB of flash) from the build entirely — worth
// doing for a landlocked site. Regenerate with tools/build_coastline.py
// after moving, or it will keep drawing the previous area's coast.
#define DRAW_COASTLINE

// EXPERIMENTAL: "OVHD <callsign> <n>s" readout in the top-left corner,
// predicting the next aircraft to pass close to overhead. Comment out to
// disable; see lib/radarcore/overhead.h for how to remove it entirely.
#define OVERHEAD_PREDICTION

// Blank the display overnight, waking on a tap. Comment out NIGHT_BLANKING
// to disable. Needs NTP: the board has no RTC, and until the first sync
// lands it deliberately stays lit rather than sitting dark and looking dead.
#define NIGHT_BLANKING
#define NIGHT_START_HOUR 0
#define NIGHT_END_HOUR 7        // set equal to START to disable the window
#define NIGHT_WAKE_S 30         // how long a tap holds the display up
#define NIGHT_FADE_MS 600       // 0 snaps instead of fading
// Show a dim clock overnight instead of a black screen. Comment out for
// full blanking. The duty is ABSOLUTE (0-255) and bypasses the LDR: at
// these levels the LDR's own floor (BL_MIN_DUTY, 40) is far too bright.
#define NIGHT_CLOCK
#define NIGHT_CLOCK_DUTY 7
#define NTP_SERVER "pool.ntp.org"   // or your router / LAN time server
// POSIX TZ rule, not an offset, so DST transitions are handled for good.
// UK: "GMT0BST,M3.5.0/1,M10.5.0". US Eastern: "EST5EDT,M3.2.0,M11.1.0".
#define NIGHT_TZ "GMT0BST,M3.5.0/1,M10.5.0"
