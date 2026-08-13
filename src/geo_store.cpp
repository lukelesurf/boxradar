#include "geo_store.h"
#include <Arduino.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>
#include "config.h"
#include "geostream.h"
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

using radar::GeoMap;
using radar::GeoStatus;

namespace {

const char *CACHE_PATH = "/site.bin";
const char *ETAG_PATH = "/site.etag";
// The download lands here first and is only promoted once it has validated,
// so a bad or cut-off fetch cannot take the last good map with it.
const char *TMP_PATH = "/site.new";

// 512 bytes on the net task's 12KB stack. The whole point of streaming is that
// this is the only buffer the download needs.
const size_t CHUNK = 512;

SemaphoreHandle_t s_mapMutex = nullptr;

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
  // No free here: the caller has already released the old buffer, which is
  // exactly what makes this allocation reuse that block instead of hunting
  // for a second one.
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

// Frees the live buffer and leaves the map invalid. Brief, and under the lock,
// because the UI task may be holding pointers into what is about to go.
void releaseBuffer() {
  geoStoreLock();
  s_map = radar::GeoMap();
  if (s_buf) free(s_buf);
  s_buf = nullptr;
  s_bufLen = 0;
  geoStoreUnlock();
}

// Reads a validated file into a freshly allocated buffer and makes it live.
//
// Called only after releaseBuffer(), so the allocation is asking for a block
// the same size as the one just handed back — which is what stops this failing
// on a fragmented heap. Holding the old blob while allocating the new wanted
// ~37.5KB in two contiguous pieces, and after a few hours there is no such
// pair: 76KB free and the malloc still fails.
bool loadFile(const char *path, const char *source) {
  if (!s_fsReady || !LittleFS.exists(path)) return false;
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  size_t len = f.size();
  if (!allocBuffer(len)) {
    f.close();
    return false;
  }
  size_t got = f.read(s_buf, len);
  f.close();
  if (got != len) {
    setStatus("%s short read %u of %u", source, (unsigned)got, (unsigned)len);
    return false;
  }
  geoStoreLock();
  bool ok = openBuffer(source);
  geoStoreUnlock();
  return ok;
}

bool loadFromCache() { return loadFile(CACHE_PATH, "cache"); }

// Promotes the validated download to be the cache. A rename, because the blob
// is already on disk — it was streamed there instead of through the heap.
void promoteTmp(const String &etag) {
  if (!s_fsReady) return;
  LittleFS.remove(CACHE_PATH);
  if (!LittleFS.rename(TMP_PATH, CACHE_PATH)) {
    Serial.println("geo: could not promote the download to the cache");
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

void geoStoreLock() {
  if (s_mapMutex) xSemaphoreTake(s_mapMutex, portMAX_DELAY);
}

void geoStoreUnlock() {
  if (s_mapMutex) xSemaphoreGive(s_mapMutex);
}

bool geoStoreBegin() {
  // Created before anything can draw: startNetTask() calls this, and
  // startUiTask() runs after it in main.cpp. The lock/unlock pair is a no-op
  // until it exists, so an ordering change degrades to the old behaviour
  // rather than crashing.
  s_mapMutex = xSemaphoreCreateMutex();
  // A download interrupted by a reset leaves this behind, and it is not the
  // cache, so nothing would ever clean it up.
  // Format on failure: a blank or corrupt partition should fix itself once
  // rather than fail on every boot forever.
  s_fsReady = LittleFS.begin(true);
  if (!s_fsReady) {
    setStatus("LittleFS mount failed");
    return false;
  }
  LittleFS.remove(TMP_PATH);
  if (loadFromCache()) return true;
  setStatus("no usable cache");
  return false;
}

bool geoStoreRefresh() {
#ifndef GEO_ENABLED
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
  if ((size_t)len > GEO_MAX_BLOB_BYTES) {
    setStatus("refusing %d bytes (cap %u)", len, (unsigned)GEO_MAX_BLOB_BYTES);
    http.end();
    return s_map.valid();
  }
  if (!s_fsReady) {
    setStatus("no filesystem to stage the download in");
    http.end();
    return s_map.valid();
  }

  // Streamed to a file, 512 bytes at a time, and validated on the way past.
  // Nothing is allocated: magic, version, CRC and home are all checkable
  // against the bytes as they arrive, which is what removes the second full
  // copy this used to need. See lib/radarcore/geostream.h.
  LittleFS.remove(TMP_PATH);
  File tmp = LittleFS.open(TMP_PATH, "w");
  if (!tmp) {
    setStatus("could not open %s to stage the download", TMP_PATH);
    http.end();
    return s_map.valid();
  }

  radar::GeoStreamCheck check;
  check.begin(HOME_LAT, HOME_LON);
  uint8_t chunk[CHUNK];
  size_t got = 0;
  WiFiClient *stream = http.getStreamPtr();
  while (got < (size_t)len) {
    size_t want = (size_t)len - got;
    if (want > CHUNK) want = CHUNK;
    int n = stream->readBytes(chunk, want);
    if (n <= 0) break;
    if (tmp.write(chunk, (size_t)n) != (size_t)n) {
      setStatus("short write staging the download");
      tmp.close();
      LittleFS.remove(TMP_PATH);
      http.end();
      return s_map.valid();
    }
    check.feed(chunk, (size_t)n);
    got += (size_t)n;
  }
  tmp.close();
  String newEtag = http.header("ETag");
  http.end();

  radar::GeoStatus st = check.finish(got);
  if (st != radar::GEO_OK) {
    // Nothing has been touched: the live map, its buffer and the cache are all
    // exactly as they were. This is the safety property the old code got by
    // validating a scratch buffer, kept without paying for the scratch buffer.
    setStatus("fetched blob rejected: %s", radar::geoStatusName(st));
    LittleFS.remove(TMP_PATH);
    return s_map.valid();
  }

  // Only now is the old blob released — and only now, so that the allocation
  // below is asking for a block the same size as the one just freed rather
  // than for a second one alongside it.
  releaseBuffer();
  if (loadFile(TMP_PATH, "fetch")) {
    promoteTmp(newEtag);
    return true;
  }

  // The download is good but could not be brought in. Put the previous map
  // back rather than leaving the panel with no geography until a reboot.
  LittleFS.remove(TMP_PATH);
  Serial.println("geo: could not load the new blob, restoring the cache");
  loadFromCache();
  return s_map.valid();
#endif
}

const radar::GeoMap &geoMap() { return s_map; }

const char *geoStoreStatus() { return s_status; }
