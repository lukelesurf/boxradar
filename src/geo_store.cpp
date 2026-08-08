#include "geo_store.h"
#include <Arduino.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>
#include "config.h"

using radar::GeoMap;
using radar::GeoStatus;

namespace {

const char *CACHE_PATH = "/site.bin";
const char *ETAG_PATH = "/site.etag";

GeoMap s_map;
uint8_t *s_buf = nullptr;
size_t s_bufLen = 0;
bool s_fsReady = false;
// 96 was too small: the record counts alone truncated the free-heap
// figure, which is the one number worth having here.
char s_status[192] = "not started";

void setStatus(const char *fmt, ...) {
  va_list args;
  va_start(args, fmt);
  vsnprintf(s_status, sizeof(s_status), fmt, args);
  va_end(args);
  Serial.printf("geo: %s\n", s_status);
}

// Replaces the buffer wholesale. The old one cannot be freed until the map has
// been reset off it, which open() does first thing — see GeoMap::open.
bool allocBuffer(size_t len) {
  if (len == 0 || len > GEO_MAX_BLOB_BYTES) {
    setStatus("refusing %u bytes (cap %u)", (unsigned)len,
              (unsigned)GEO_MAX_BLOB_BYTES);
    return false;
  }
  uint8_t *next = (uint8_t *)malloc(len);
  if (!next) {
    setStatus("malloc %u failed, %u heap free", (unsigned)len,
              (unsigned)ESP.getFreeHeap());
    return false;
  }
  if (s_buf) free(s_buf);
  s_buf = next;
  s_bufLen = len;
  return true;
}

// Opens whatever is in the buffer, reporting the record counts so a serial log
// is enough to tell a good load from a plausible-looking bad one.
bool openBuffer(const char *source) {
  GeoStatus st = s_map.open(s_buf, s_bufLen, HOME_LAT, HOME_LON);
  if (st != radar::GEO_OK) {
    setStatus("%s: %s", source, radar::geoStatusName(st));
    return false;
  }
  setStatus("%s: %u bytes, %u airspace, %u coast (%u dropped), %u fields, "
            "%u rwy, %u fix, %u town, heap %u",
            source, (unsigned)s_bufLen, s_map.airspaceCount(),
            s_map.coastCount(), s_map.coastDropped(), s_map.airfieldCount(),
            s_map.runwayCount(), s_map.waypointCount(), s_map.townCount(),
            (unsigned)ESP.getFreeHeap());
  return true;
}

bool loadFromCache() {
  if (!s_fsReady || !LittleFS.exists(CACHE_PATH)) return false;
  File f = LittleFS.open(CACHE_PATH, "r");
  if (!f) return false;
  size_t len = f.size();
  if (!allocBuffer(len)) {
    f.close();
    return false;
  }
  size_t got = f.read(s_buf, len);
  f.close();
  if (got != len) {
    setStatus("cache short read %u of %u", (unsigned)got, (unsigned)len);
    return false;
  }
  return openBuffer("cache");
}

void saveToCache(const String &etag) {
  if (!s_fsReady) return;
  File f = LittleFS.open(CACHE_PATH, "w");
  if (!f) {
    Serial.println("geo: cache open for write failed");
    return;
  }
  size_t wrote = f.write(s_buf, s_bufLen);
  f.close();
  if (wrote != s_bufLen) {
    Serial.printf("geo: cache short write %u of %u\n", (unsigned)wrote,
                  (unsigned)s_bufLen);
    LittleFS.remove(CACHE_PATH);  // a partial cache is worse than none
    return;
  }
  File e = LittleFS.open(ETAG_PATH, "w");
  if (e) {
    e.print(etag);
    e.close();
  }
}

String readEtag() {
  if (!s_fsReady || !LittleFS.exists(ETAG_PATH)) return String();
  File e = LittleFS.open(ETAG_PATH, "r");
  if (!e) return String();
  String v = e.readString();
  e.close();
  return v;
}

} // namespace

bool geoStoreBegin() {
  // Format on failure: a blank or corrupt partition should fix itself once
  // rather than fail on every boot forever.
  s_fsReady = LittleFS.begin(true);
  if (!s_fsReady) {
    setStatus("LittleFS mount failed");
    return false;
  }
  if (loadFromCache()) return true;
  setStatus("no usable cache");
  return false;
}

bool geoStoreRefresh() {
#ifndef GEO_URL
  return s_map.valid();
#else
  if (WiFi.status() != WL_CONNECTED) return s_map.valid();

  HTTPClient http;
  http.setConnectTimeout(2000);
  http.setTimeout(8000);
  http.useHTTP10(true);
  http.begin(GEO_URL);

  String etag = readEtag();
  if (etag.length()) http.addHeader("If-None-Match", etag);
  const char *collect[] = {"ETag"};
  http.collectHeaders(collect, 1);

  int code = http.GET();
  if (code == HTTP_CODE_NOT_MODIFIED) {
    // Logged, because an unlogged 304 is indistinguishable from a fetch that
    // silently did nothing — the same lesson the METAR proxy's upstream
    // logging taught.
    Serial.println("geo: 304 not modified, cache is current");
    http.end();
    return s_map.valid();
  }
  if (code != HTTP_CODE_OK) {
    setStatus("http %d", code);
    http.end();
    return s_map.valid();
  }

  int len = http.getSize();
  if (len <= 0) {
    setStatus("no content-length");
    http.end();
    return s_map.valid();
  }

  // Read into a scratch buffer first. Validating before touching either the
  // live buffer or the cache is the whole safety argument here: a bad deploy
  // must cost nothing.
  if ((size_t)len > GEO_MAX_BLOB_BYTES) {
    setStatus("refusing %d bytes (cap %u)", len,
              (unsigned)GEO_MAX_BLOB_BYTES);
    http.end();
    return s_map.valid();
  }
  uint8_t *scratch = (uint8_t *)malloc((size_t)len);
  if (!scratch) {
    setStatus("malloc %d failed, %u heap free", len,
              (unsigned)ESP.getFreeHeap());
    http.end();
    return s_map.valid();
  }
  size_t got = http.getStream().readBytes(scratch, (size_t)len);
  String newEtag = http.header("ETag");
  http.end();

  if (got != (size_t)len) {
    setStatus("short body %u of %d", (unsigned)got, len);
    free(scratch);
    return s_map.valid();
  }

  // Validate with a GeoBlob, NOT a GeoMap: GeoMap carries a 3KB coast-box
  // array, and this runs on the net task's 12KB stack alongside HTTPClient.
  // Magic, version, CRC and home are all this needs to check anyway.
  radar::GeoBlob probe;
  GeoStatus st = probe.open(scratch, (size_t)len, HOME_LAT, HOME_LON);
  if (st != radar::GEO_OK) {
    setStatus("fetched blob rejected: %s", radar::geoStatusName(st));
    free(scratch);
    return s_map.valid();  // the cache, if any, is untouched
  }

  // Only now is it safe to swap. Reset the live map off the old buffer before
  // freeing it.
  s_map = radar::GeoMap();
  if (s_buf) free(s_buf);
  s_buf = scratch;
  s_bufLen = (size_t)len;
  bool ok = openBuffer("fetch");
  if (ok) saveToCache(newEtag);
  return ok;
#endif
}

const radar::GeoMap &geoMap() { return s_map; }

const char *geoStoreStatus() { return s_status; }
