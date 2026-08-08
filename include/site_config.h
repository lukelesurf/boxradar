#pragma once
#include "site_config_data.h"

// Runtime site configuration, and the accessor macros that let every existing
// use site keep its spelling.
//
// config.h now holds DEFAULT_* values. This header aliases the old names to
// the live struct, so `HOME_LAT` and `METAR_URL` still read as they always did
// while resolving to whatever NVS supplied. That kept the migration to a
// handful of files instead of forty-five call sites.
//
// NVS is an OVERLAY, never a replacement: siteConfigBegin() starts from the
// compiled defaults and applies only the keys that are present. A wiped or
// never-written NVS therefore behaves exactly as the firmware did before,
// which is what keeps the board on WiFi and reachable over OTA no matter what
// the config layer does. That property is the whole safety argument — do not
// invert it by making NVS authoritative.

// Loads defaults, overlays NVS, and logs what it ended up with. Call once,
// before WiFi or anything that reads config.
void siteConfigBegin();

const radar::SiteConfig &siteConfig();

// Persist one field to NVS. Returns false if the value does not fit, in which
// case nothing is written. The portal (phase 3a-2) is the intended caller.
bool siteConfigSetString(const char *key, const char *value);
bool siteConfigSetFloat(const char *key, float value);
bool siteConfigSetU32(const char *key, uint32_t value);

// Forget every stored override, so the next boot uses the compiled defaults.
void siteConfigClear();

// True when any NVS override was applied at boot.
bool siteConfigFromNvs();

// One line for the serial log.
const char *siteConfigSummary();

// ---------------------------------------------------------------- accessors
// Deliberately macros rather than inline functions: they have to substitute
// for what were #defines in expressions all over the UI and net tasks.
#define WIFI_SSID (siteConfig().wifiSsid)
#define WIFI_PASS (siteConfig().wifiPass)
#define RECEIVER_URL (siteConfig().receiverUrl)
#define HOME_LAT (siteConfig().homeLat)
#define HOME_LON (siteConfig().homeLon)
#define OTA_HOSTNAME (siteConfig().otaHostname)
#define OTA_PASSWORD (siteConfig().otaPassword)
#define POLL_INTERVAL_MS (siteConfig().pollIntervalMs)
#define METAR_URL (siteConfig().metarUrl)
#define METAR_STATION (siteConfig().metarStation)
#define METAR_POLL_INTERVAL_MS (siteConfig().metarPollIntervalMs)
#define GEO_URL (siteConfig().geoUrl)
#define GEO_POLL_INTERVAL_MS (siteConfig().geoPollIntervalMs)
#define NTP_SERVER (siteConfig().ntpServer)
#define NIGHT_TZ (siteConfig().nightTz)
#define NIGHT_START_HOUR (siteConfig().nightStartHour)
#define NIGHT_END_HOUR (siteConfig().nightEndHour)
#define NIGHT_WAKE_S (siteConfig().nightWakeS)
#define NIGHT_FADE_MS (siteConfig().nightFadeMs)
#define NIGHT_CLOCK_DUTY (siteConfig().nightClockDuty)
