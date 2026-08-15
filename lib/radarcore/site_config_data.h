#pragma once
#include <stddef.h>
#include <stdint.h>
#include "view_ranges.h"

// The site's runtime configuration, as plain data.
//
// Portable and free of Arduino, NVS and config.h, so the bounds checking and
// validation below are natively tested. The device side — compiled defaults
// and the NVS overlay — lives in src/site_config.cpp.
//
// Fixed-width char arrays rather than String: this is copied into a static and
// read from two tasks, and a heap-allocating field would be a needless hazard
// on a board with no PSRAM.
//
// Must compile under gnu++11 as well as gnu++17: no default member
// initialisers in aggregates.

namespace radar {

// Bounds. WiFi limits are from the 802.11 spec (32-char SSID, 63-char PSK);
// the rest are generous for a LAN URL and a POSIX TZ rule.
enum {
  CFG_SSID_LEN = 33,
  CFG_PASS_LEN = 65,
  CFG_URL_LEN = 128,
  CFG_STATION_LEN = 5,
  CFG_HOST_LEN = 33,
  CFG_TZ_LEN = 48,
  // Roughly forty ICAO designators at five characters each. The built-in list
  // is 134 characters, so this leaves room to grow one without a reflash.
  CFG_TYPES_LEN = 256,
  // Twelve patterns of up to sixteen characters, plus separators. Shorter than
  // the type list because this one rides on EVERY contact poll, where the type
  // list only ever moves at boot.
  CFG_WATCH_LEN = 96,
};

// Top of the altitude band, in feet, and its shipped ceiling. Above anything
// that reports ADS-B — a record claiming more is better hidden than drawn —
// and mirrored on the Pi as contacts.ALT_BAND_CEILING_FT.
enum { CFG_ALT_CEILING_FT = 70000 };

struct SiteConfig {
  char wifiSsid[CFG_SSID_LEN];
  char wifiPass[CFG_PASS_LEN];
  char receiverUrl[CFG_URL_LEN];
  char metarUrl[CFG_URL_LEN];
  char metarStation[CFG_STATION_LEN];
  char geoUrl[CFG_URL_LEN];
  char otaHostname[CFG_HOST_LEN];
  char otaPassword[CFG_HOST_LEN];
  char ntpServer[CFG_HOST_LEN];
  char nightTz[CFG_TZ_LEN];
  char commonTypes[CFG_TYPES_LEN];
  // Watchlist patterns, comma separated. Like the altitude band this never
  // reaches a draw site directly — it rides on the /contacts request and the
  // Pi does the matching, because a pattern may name a type ("737",
  // "Hercules") and only the Pi holds the names.
  char watchList[CFG_WATCH_LEN];
  float homeLat;
  float homeLon;
  uint32_t pollIntervalMs;
  uint32_t metarPollIntervalMs;
  uint32_t geoPollIntervalMs;
  uint8_t nightStartHour;
  uint8_t nightEndHour;
  uint8_t nightClockDuty;
  uint16_t nightWakeS;
  uint16_t nightFadeMs;
  // Runtime on/off switches. metarEnabled/geoEnabled still have a
  // compile-time #ifdef behind them — a board built without METAR_ENABLED has
  // no METAR code to run — but the four below are compiled unconditionally
  // and their config.h defines now only pick the default. That is the trade
  // the TODO named: a little flash for both paths, in exchange for trying the
  // panel without a coastline, without the overhead readout, or without night
  // blanking, none of which costs a reflash any more.
  uint8_t metarEnabled;
  uint8_t geoEnabled;
  uint8_t coastEnabled;
  uint8_t overheadEnabled;
  uint8_t nightEnabled;
  uint8_t nightClockEnabled;
  // Overhead prediction thresholds. Radius is in TENTHS of a nautical mile
  // because the field machinery carries whole numbers and one nautical mile is
  // far too coarse a step for a miss distance whose shipped value is 1.0 —
  // the same reasoning that kept the scope ranges integral, applied to a
  // quantity an order of magnitude smaller. radar::OverheadParams holds it as
  // the float the maths wants.
  uint16_t overheadRadiusTenthsNm;
  uint16_t overheadHorizonS;
  uint8_t overheadMaxTurnDegPerNm;
  // Contact ageing, whole seconds. See radar::SeenAgeing.
  uint16_t seenDimS;
  uint16_t seenDropS;
  // Altitude band, whole feet. uint32 rather than uint16 because the ceiling
  // is 70000 and would wrap. Unlike everything else here these two never
  // reach a draw site: they ride on the /contacts request and the Pi applies
  // them, because the 32-slot cap saturates continuously and a filter behind
  // the cap would spend all 32 slots and then hide most of them. 0 as a floor
  // means NO floor — barometric altitude reads slightly negative at a low
  // airfield on a high-pressure day.
  uint32_t altMinFt;
  uint32_t altMaxFt;
  // Whether multilaterated positions reach the board at all. Filtered by the
  // Pi with the altitude band and for the same reason — they occupy cap slots
  // — so like those two it never reaches a draw site. Off costs the signal the
  // hollow ring carries: in saturated airspace an airframe not sending ADS-B
  // is unusual in its own right, not merely less precisely located.
  uint8_t mlatEnabled;
  // Scope ranges, whole nautical miles. Held as integers here because that is
  // what NVS and the config form carry; radar::ViewRanges holds them as the
  // floats the projection wants. See view_ranges.h.
  uint16_t overviewNm;
  uint16_t detailNm[VIEW_DETAIL_RANGES];
  uint16_t twoLineMaxNm;
};

// Copies src into a fixed field, refusing rather than truncating when it will
// not fit. A silently shortened SSID or URL fails later and further away than
// a rejected one, and the caller is a config loader that can report.
bool cfgSetStr(char *dst, size_t cap, const char *src);

// True when the config could plausibly work. Deliberately narrow: it rejects
// what is certainly broken, not what is merely unusual, because a site is
// entitled to odd-looking but valid values.
bool siteConfigValid(const SiteConfig &cfg);

// Why siteConfigValid() said no, or "" when it said yes.
const char *siteConfigProblem(const SiteConfig &cfg);

} // namespace radar
