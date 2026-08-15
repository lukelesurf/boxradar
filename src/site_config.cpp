#include "site_config.h"
#include <Arduino.h>
#include <Preferences.h>
#include "config.h"
#include "classify.h"
#include "overhead.h"   // OverheadParams, and SeenAgeing via aircraft.h

using radar::SiteConfig;

namespace {

// NVS keys are capped at 15 characters by the API, so these are abbreviated
// rather than descriptive. Changing one orphans whatever a board already
// stored under the old name, so treat them as a wire format.
const char *NS = "boxradar";

const char *K_SSID = "ssid";
const char *K_PASS = "pass";
const char *K_RECV = "recv";
const char *K_METAR = "metar";
const char *K_STATION = "station";
const char *K_GEO = "geo";
const char *K_OTAHOST = "otahost";
const char *K_OTAPASS = "otapass";
const char *K_NTP = "ntp";
const char *K_TZ = "tz";
const char *K_LAT = "lat";
const char *K_LON = "lon";
const char *K_POLL = "poll";
const char *K_MPOLL = "mpoll";
const char *K_GPOLL = "gpoll";
const char *K_NSTART = "nstart";
const char *K_NEND = "nend";
const char *K_NWAKE = "nwake";
const char *K_NFADE = "nfade";
const char *K_NDUTY = "nduty";
const char *K_TYPES = "types";
const char *K_METARON = "metaron";
const char *K_GEOON = "geoon";
const char *K_OVNM = "ovnm";
const char *K_D1NM = "d1nm";
const char *K_D2NM = "d2nm";
const char *K_TLNM = "tlnm";
const char *K_COASTON = "coaston";
const char *K_OHON = "ohon";
const char *K_NIGHTON = "nighton";
const char *K_NCLKON = "nclkon";
const char *K_OHRNM = "ohrnm";
const char *K_OHSEC = "ohsec";
const char *K_OHTURN = "ohturn";
const char *K_SDIM = "sdim";
const char *K_SDROP = "sdrop";
const char *K_AMIN = "amin";
const char *K_AMAX = "amax";
const char *K_MLATON = "mlaton";
const char *K_WATCH = "watch";

SiteConfig s_cfg;
bool s_fromNvs = false;
char s_summary[160] = "not loaded";

// Compiled defaults. Everything NVS does not override comes from here, which
// is why an empty NVS behaves exactly like the old firmware.
void loadDefaults(SiteConfig &c) {
  memset(&c, 0, sizeof(c));
  radar::cfgSetStr(c.wifiSsid, radar::CFG_SSID_LEN, DEFAULT_WIFI_SSID);
  radar::cfgSetStr(c.wifiPass, radar::CFG_PASS_LEN, DEFAULT_WIFI_PASS);
  radar::cfgSetStr(c.receiverUrl, radar::CFG_URL_LEN, DEFAULT_RECEIVER_URL);
  radar::cfgSetStr(c.otaHostname, radar::CFG_HOST_LEN, DEFAULT_OTA_HOSTNAME);
  radar::cfgSetStr(c.otaPassword, radar::CFG_HOST_LEN, DEFAULT_OTA_PASSWORD);
  radar::cfgSetStr(c.ntpServer, radar::CFG_HOST_LEN, DEFAULT_NTP_SERVER);
  radar::cfgSetStr(c.nightTz, radar::CFG_TZ_LEN, DEFAULT_NIGHT_TZ);
  radar::cfgSetStr(c.commonTypes, radar::CFG_TYPES_LEN,
                   radar::classifyDefaultCommonTypes());
  c.homeLat = DEFAULT_HOME_LAT;
  c.homeLon = DEFAULT_HOME_LON;
  c.pollIntervalMs = DEFAULT_POLL_INTERVAL_MS;
  c.nightStartHour = DEFAULT_NIGHT_START_HOUR;
  c.nightEndHour = DEFAULT_NIGHT_END_HOUR;
  c.nightWakeS = DEFAULT_NIGHT_WAKE_S;
  c.nightFadeMs = DEFAULT_NIGHT_FADE_MS;
  c.nightClockDuty = DEFAULT_NIGHT_CLOCK_DUTY;
  // The scope's own defaults rather than a DEFAULT_ in config.h: these are
  // layout values with the reasoning for them next to them, and duplicating
  // them into config.h would give two places to disagree.
  const radar::ViewRanges &r = radar::viewRangesDefaults();
  c.overviewNm = (uint16_t)r.overviewNm;
  for (int i = 0; i < radar::VIEW_DETAIL_RANGES; i++)
    c.detailNm[i] = (uint16_t)r.detailNm[i];
  c.twoLineMaxNm = (uint16_t)r.twoLineMaxNm;
  // Same argument for these two: the reasoning for 1nm / 150s / 8 deg-per-nm
  // and for 30s / 60s is written beside the values in radarcore, and a
  // DEFAULT_ in config.h would give two places to disagree.
  const radar::OverheadParams &o = radar::overheadParamsDefaults();
  c.overheadRadiusTenthsNm = (uint16_t)(o.radiusNm * 10.0f + 0.5f);
  c.overheadHorizonS = (uint16_t)o.horizonS;
  c.overheadMaxTurnDegPerNm = (uint8_t)o.maxTurnDegPerNm;
  const radar::SeenAgeing &ag = radar::seenAgeingDefaults();
  c.seenDimS = (uint16_t)ag.dimS;
  c.seenDropS = (uint16_t)ag.dropS;
  // The whole band, so the shipped behaviour is "show everything" and nobody
  // has to know the feature exists to get the old picture. Not a DEFAULT_ in
  // config.h: there is no site-specific answer, and a floor is something you
  // discover you want after watching the scope for a week.
  c.altMinFt = 0;
  c.altMaxFt = radar::CFG_ALT_CEILING_FT;
  // On, because the feed is the receiver's business and the display should
  // show what it was given until told otherwise.
  c.mlatEnabled = 1;
  // Default to on wherever the feature is compiled in; the flag exists to let
  // it be turned off without a reflash, not to make it off by default.
  c.metarEnabled = 0;
  c.geoEnabled = 0;
  // These four are compiled in either way, so the #ifdef only picks the
  // default. An existing config.h therefore keeps behaving exactly as it did:
  // `#define DRAW_COASTLINE` still means "draw the coastline", it just means
  // it as a starting value rather than as a build decision.
  c.coastEnabled = 0;
  c.overheadEnabled = 0;
  c.nightEnabled = 0;
  c.nightClockEnabled = 0;
#ifdef DRAW_COASTLINE
  c.coastEnabled = 1;
#endif
#ifdef OVERHEAD_PREDICTION
  c.overheadEnabled = 1;
#endif
#ifdef NIGHT_BLANKING
  c.nightEnabled = 1;
#endif
#ifdef NIGHT_CLOCK
  c.nightClockEnabled = 1;
#endif
#ifdef METAR_ENABLED
  c.metarEnabled = 1;
  radar::cfgSetStr(c.metarUrl, radar::CFG_URL_LEN, DEFAULT_METAR_URL);
  radar::cfgSetStr(c.metarStation, radar::CFG_STATION_LEN,
                   DEFAULT_METAR_STATION);
  c.metarPollIntervalMs = DEFAULT_METAR_POLL_INTERVAL_MS;
#endif
#ifdef GEO_ENABLED
  c.geoEnabled = 1;
  radar::cfgSetStr(c.geoUrl, radar::CFG_URL_LEN, DEFAULT_GEO_URL);
  c.geoPollIntervalMs = DEFAULT_GEO_POLL_INTERVAL_MS;
#endif
}

// Overlays one string key if present. Reports rather than truncates: a value
// too long for the field is a config error worth seeing, not something to
// silently shorten.
bool overlayStr(Preferences &p, const char *key, char *dst, size_t cap) {
  if (!p.isKey(key)) return false;
  char buf[radar::CFG_TYPES_LEN];  // the longest field
  size_t n = p.getString(key, buf, sizeof(buf));
  if (n == 0) return false;
  if (!radar::cfgSetStr(dst, cap, buf)) {
    Serial.printf("cfg: stored %s is too long for its field, ignoring\n", key);
    return false;
  }
  return true;
}

} // namespace

void siteConfigBegin() {
  loadDefaults(s_cfg);

  Preferences p;
  int applied = 0;
  // Read-only open. A failure here must not be fatal — the defaults are
  // already loaded and they are known to work.
  if (p.begin(NS, true)) {
    applied += overlayStr(p, K_SSID, s_cfg.wifiSsid, radar::CFG_SSID_LEN);
    applied += overlayStr(p, K_PASS, s_cfg.wifiPass, radar::CFG_PASS_LEN);
    applied += overlayStr(p, K_RECV, s_cfg.receiverUrl, radar::CFG_URL_LEN);
    applied += overlayStr(p, K_METAR, s_cfg.metarUrl, radar::CFG_URL_LEN);
    applied += overlayStr(p, K_STATION, s_cfg.metarStation,
                          radar::CFG_STATION_LEN);
    applied += overlayStr(p, K_GEO, s_cfg.geoUrl, radar::CFG_URL_LEN);
    applied += overlayStr(p, K_OTAHOST, s_cfg.otaHostname,
                          radar::CFG_HOST_LEN);
    applied += overlayStr(p, K_OTAPASS, s_cfg.otaPassword,
                          radar::CFG_HOST_LEN);
    applied += overlayStr(p, K_NTP, s_cfg.ntpServer, radar::CFG_HOST_LEN);
    applied += overlayStr(p, K_TZ, s_cfg.nightTz, radar::CFG_TZ_LEN);
    applied += overlayStr(p, K_TYPES, s_cfg.commonTypes,
                          radar::CFG_TYPES_LEN);
    applied += overlayStr(p, K_WATCH, s_cfg.watchList,
                          radar::CFG_WATCH_LEN);
    if (p.isKey(K_LAT)) { s_cfg.homeLat = p.getFloat(K_LAT); applied++; }
    if (p.isKey(K_LON)) { s_cfg.homeLon = p.getFloat(K_LON); applied++; }
    if (p.isKey(K_POLL)) { s_cfg.pollIntervalMs = p.getUInt(K_POLL); applied++; }
    if (p.isKey(K_MPOLL)) { s_cfg.metarPollIntervalMs = p.getUInt(K_MPOLL); applied++; }
    if (p.isKey(K_GPOLL)) { s_cfg.geoPollIntervalMs = p.getUInt(K_GPOLL); applied++; }
    // Every numeric key is stored and read as UInt32, narrowed here. NVS
    // Preferences is TYPED: getUChar() on a key written with putUInt() does
    // not coerce, it returns 0. That cost an hour once — a stored night clock
    // duty came back as 0, which means backlight off, so the symptom was "the
    // night clock is invisible" rather than anything pointing at a type
    // mismatch. One width on both sides removes the whole class of bug.
    if (p.isKey(K_NSTART)) { s_cfg.nightStartHour = (uint8_t)p.getUInt(K_NSTART); applied++; }
    if (p.isKey(K_NEND)) { s_cfg.nightEndHour = (uint8_t)p.getUInt(K_NEND); applied++; }
    if (p.isKey(K_NWAKE)) { s_cfg.nightWakeS = (uint16_t)p.getUInt(K_NWAKE); applied++; }
    if (p.isKey(K_NFADE)) { s_cfg.nightFadeMs = (uint16_t)p.getUInt(K_NFADE); applied++; }
    if (p.isKey(K_NDUTY)) { s_cfg.nightClockDuty = (uint8_t)p.getUInt(K_NDUTY); applied++; }
    if (p.isKey(K_METARON)) { s_cfg.metarEnabled = p.getUInt(K_METARON) ? 1 : 0; applied++; }
    if (p.isKey(K_GEOON)) { s_cfg.geoEnabled = p.getUInt(K_GEOON) ? 1 : 0; applied++; }
    // loadDefaults() and the push to viewRangesSet() both loop to
    // VIEW_DETAIL_RANGES; these two are spelled out because each detail level
    // needs its own NVS key. Raising the count without adding a key would
    // widen the loops and leave the new level silently on its compiled
    // default — a half-applied config rather than a build failure.
    static_assert(radar::VIEW_DETAIL_RANGES == 2,
                  "add an NVS key per detail level");
    if (p.isKey(K_OVNM)) { s_cfg.overviewNm = (uint16_t)p.getUInt(K_OVNM); applied++; }
    if (p.isKey(K_D1NM)) { s_cfg.detailNm[0] = (uint16_t)p.getUInt(K_D1NM); applied++; }
    if (p.isKey(K_D2NM)) { s_cfg.detailNm[1] = (uint16_t)p.getUInt(K_D2NM); applied++; }
    if (p.isKey(K_TLNM)) { s_cfg.twoLineMaxNm = (uint16_t)p.getUInt(K_TLNM); applied++; }
    if (p.isKey(K_COASTON)) { s_cfg.coastEnabled = p.getUInt(K_COASTON) ? 1 : 0; applied++; }
    if (p.isKey(K_OHON)) { s_cfg.overheadEnabled = p.getUInt(K_OHON) ? 1 : 0; applied++; }
    if (p.isKey(K_NIGHTON)) { s_cfg.nightEnabled = p.getUInt(K_NIGHTON) ? 1 : 0; applied++; }
    if (p.isKey(K_NCLKON)) { s_cfg.nightClockEnabled = p.getUInt(K_NCLKON) ? 1 : 0; applied++; }
    if (p.isKey(K_OHRNM)) { s_cfg.overheadRadiusTenthsNm = (uint16_t)p.getUInt(K_OHRNM); applied++; }
    if (p.isKey(K_OHSEC)) { s_cfg.overheadHorizonS = (uint16_t)p.getUInt(K_OHSEC); applied++; }
    if (p.isKey(K_OHTURN)) { s_cfg.overheadMaxTurnDegPerNm = (uint8_t)p.getUInt(K_OHTURN); applied++; }
    if (p.isKey(K_SDIM)) { s_cfg.seenDimS = (uint16_t)p.getUInt(K_SDIM); applied++; }
    if (p.isKey(K_SDROP)) { s_cfg.seenDropS = (uint16_t)p.getUInt(K_SDROP); applied++; }
    if (p.isKey(K_AMIN)) { s_cfg.altMinFt = p.getUInt(K_AMIN); applied++; }
    if (p.isKey(K_AMAX)) { s_cfg.altMaxFt = p.getUInt(K_AMAX); applied++; }
    if (p.isKey(K_MLATON)) { s_cfg.mlatEnabled = p.getUInt(K_MLATON) ? 1 : 0; applied++; }
    p.end();
  }
  s_fromNvs = applied > 0;

  // If the overlay produced something broken, fall all the way back rather
  // than half-applying it. A bad stored value must not cost the board its
  // WiFi, because WiFi is what makes it reflashable over OTA.
  const char *problem = radar::siteConfigProblem(s_cfg);
  if (problem[0] != '\0') {
    Serial.printf("cfg: stored config rejected (%s), using compiled "
                  "defaults\n", problem);
    loadDefaults(s_cfg);
    s_fromNvs = false;
  }

  // The classifier borrows this pointer, and s_cfg is static, so it stays
  // valid for the life of the board.
  radar::classifySetCommonTypes(s_cfg.commonTypes);

  // The scope reads its ranges from radarcore, not from here — layout.h cannot
  // see this file. Pushed after the fallback above, so a config that was
  // rejected wholesale draws at the compiled ranges too.
  radar::ViewRanges ranges;
  ranges.overviewNm = (float)s_cfg.overviewNm;
  for (int i = 0; i < radar::VIEW_DETAIL_RANGES; i++)
    ranges.detailNm[i] = (float)s_cfg.detailNm[i];
  ranges.twoLineMaxNm = (float)s_cfg.twoLineMaxNm;
  radar::viewRangesSet(ranges);

  // Same push, same reason: overhead.cpp and aircraft.cpp are linked into the
  // native tests and cannot see this file. Tenths back to nautical miles here,
  // so nothing downstream of the config layer has to know the encoding.
  radar::OverheadParams overhead;
  overhead.radiusNm = (float)s_cfg.overheadRadiusTenthsNm / 10.0f;
  overhead.horizonS = (float)s_cfg.overheadHorizonS;
  overhead.maxTurnDegPerNm = (float)s_cfg.overheadMaxTurnDegPerNm;
  radar::overheadParamsSet(overhead);

  radar::SeenAgeing ageing;
  ageing.dimS = (float)s_cfg.seenDimS;
  ageing.dropS = (float)s_cfg.seenDropS;
  radar::seenAgeingSet(ageing);

  snprintf(s_summary, sizeof(s_summary),
           "%s, ssid %s, home %.4f,%.4f, recv %s, metar %s, geo %s",
           s_fromNvs ? "NVS overlay" : "compiled defaults",
           s_cfg.wifiSsid, s_cfg.homeLat, s_cfg.homeLon,
           s_cfg.receiverUrl[0] ? "set" : "none",
           s_cfg.metarUrl[0] ? "set" : "none",
           s_cfg.geoUrl[0] ? "set" : "none");
  Serial.printf("cfg: %s\n", s_summary);
}

const radar::SiteConfig &siteConfig() { return s_cfg; }

bool siteConfigSetString(const char *key, const char *value) {
  if (!key || !value) return false;
  // The widest field, as a backstop. Per-field limits are enforced earlier by
  // radar::deviceFieldProblem, which can name the field in its complaint.
  if (strlen(value) >= radar::CFG_TYPES_LEN) return false;
  Preferences p;
  if (!p.begin(NS, false)) return false;
  bool ok = p.putString(key, value) > 0;
  p.end();
  return ok;
}

bool siteConfigSetFloat(const char *key, float value) {
  Preferences p;
  if (!p.begin(NS, false)) return false;
  bool ok = p.putFloat(key, value) > 0;
  p.end();
  return ok;
}

bool siteConfigSetU32(const char *key, uint32_t value) {
  Preferences p;
  if (!p.begin(NS, false)) return false;
  bool ok = p.putUInt(key, value) > 0;
  p.end();
  return ok;
}

void siteConfigClear() {
  Preferences p;
  if (!p.begin(NS, false)) return;
  p.clear();
  p.end();
  Serial.println("cfg: cleared all NVS overrides");
}

bool siteConfigClearKey(const char *key) {
  if (!key || !key[0]) return false;
  Preferences p;
  if (!p.begin(NS, false)) return false;
  bool had = p.isKey(key);
  if (had) p.remove(key);
  p.end();
  if (had) Serial.printf("cfg: cleared override for %s\n", key);
  return had;
}

bool siteConfigHasOverride(const char *key) {
  if (!key || !key[0]) return false;
  Preferences p;
  if (!p.begin(NS, true)) return false;  // no namespace yet: nothing stored
  bool has = p.isKey(key);
  p.end();
  return has;
}

// The two by-name readers below exist only for the config server's read-back.
// Deliberately a switch over the same keys rather than a generic map: the key
// list is a wire format (see the note at the top of this file) and a table
// that drifted from the struct would report one field while writing another.
bool siteConfigReadU32(const char *key, uint32_t *out) {
  if (!key || !out) return false;
  if (strcmp(key, K_POLL) == 0) { *out = s_cfg.pollIntervalMs; return true; }
  if (strcmp(key, K_MPOLL) == 0) { *out = s_cfg.metarPollIntervalMs; return true; }
  if (strcmp(key, K_GPOLL) == 0) { *out = s_cfg.geoPollIntervalMs; return true; }
  if (strcmp(key, K_NSTART) == 0) { *out = s_cfg.nightStartHour; return true; }
  if (strcmp(key, K_NEND) == 0) { *out = s_cfg.nightEndHour; return true; }
  if (strcmp(key, K_NWAKE) == 0) { *out = s_cfg.nightWakeS; return true; }
  if (strcmp(key, K_NFADE) == 0) { *out = s_cfg.nightFadeMs; return true; }
  if (strcmp(key, K_NDUTY) == 0) { *out = s_cfg.nightClockDuty; return true; }
  if (strcmp(key, K_METARON) == 0) { *out = s_cfg.metarEnabled; return true; }
  if (strcmp(key, K_GEOON) == 0) { *out = s_cfg.geoEnabled; return true; }
  if (strcmp(key, K_OVNM) == 0) { *out = s_cfg.overviewNm; return true; }
  if (strcmp(key, K_D1NM) == 0) { *out = s_cfg.detailNm[0]; return true; }
  if (strcmp(key, K_D2NM) == 0) { *out = s_cfg.detailNm[1]; return true; }
  if (strcmp(key, K_TLNM) == 0) { *out = s_cfg.twoLineMaxNm; return true; }
  if (strcmp(key, K_COASTON) == 0) { *out = s_cfg.coastEnabled; return true; }
  if (strcmp(key, K_OHON) == 0) { *out = s_cfg.overheadEnabled; return true; }
  if (strcmp(key, K_NIGHTON) == 0) { *out = s_cfg.nightEnabled; return true; }
  if (strcmp(key, K_NCLKON) == 0) { *out = s_cfg.nightClockEnabled; return true; }
  if (strcmp(key, K_OHRNM) == 0) { *out = s_cfg.overheadRadiusTenthsNm; return true; }
  if (strcmp(key, K_OHSEC) == 0) { *out = s_cfg.overheadHorizonS; return true; }
  if (strcmp(key, K_OHTURN) == 0) { *out = s_cfg.overheadMaxTurnDegPerNm; return true; }
  if (strcmp(key, K_SDIM) == 0) { *out = s_cfg.seenDimS; return true; }
  if (strcmp(key, K_SDROP) == 0) { *out = s_cfg.seenDropS; return true; }
  if (strcmp(key, K_AMIN) == 0) { *out = s_cfg.altMinFt; return true; }
  if (strcmp(key, K_AMAX) == 0) { *out = s_cfg.altMaxFt; return true; }
  if (strcmp(key, K_MLATON) == 0) { *out = s_cfg.mlatEnabled; return true; }
  return false;
}

const char *siteConfigReadStr(const char *key) {
  if (!key) return nullptr;
  if (strcmp(key, K_NTP) == 0) return s_cfg.ntpServer;
  if (strcmp(key, K_TZ) == 0) return s_cfg.nightTz;
  if (strcmp(key, K_TYPES) == 0) return s_cfg.commonTypes;
  if (strcmp(key, K_WATCH) == 0) return s_cfg.watchList;
  return nullptr;
}

bool siteConfigFromNvs() { return s_fromNvs; }

const char *siteConfigSummary() { return s_summary; }
