#pragma once
#include "geomap.h"

// Device side of the geography blob: LittleFS cache, conditional HTTP fetch,
// and the single heap buffer the GeoMap points into.
//
// The buffer is owned here and outlives every accessor, because GeoMap and
// GeoBlob are zero-copy views over it — that is what makes the map cost one
// allocation instead of one per record.
//
// Deliberately NOT part of phase 3a: the URL is a compile-time GEO_URL in
// config.h, exactly like METAR_URL. Nothing here touches WiFi bring-up or the
// OTA path, which on this unit is the only practical recovery.

// A wrong URL serving something enormous must not exhaust the heap. This site's
// blob is ~18KB; 64KB is generous and still leaves the render sprite room.
static const size_t GEO_MAX_BLOB_BYTES = 64 * 1024;

// Mount LittleFS and open any cached blob. Safe to call once WiFi is up or
// before; it does no network work.
bool geoStoreBegin();

// Conditional GET. On 200 the body is validated BEFORE the cache is written —
// a bad blob must never overwrite a good one. On 304 nothing happens.
// Returns true if the in-memory map is currently valid.
bool geoStoreRefresh();

// Held by the UI task around any frame that reads geoMap(), and by the
// geography store around the moment it swaps the buffer out.
//
// The store's accessors hand out pointers INTO the blob buffer (geoblob.h is
// zero-copy by design), so freeing that buffer while core 1 is drawing from
// it is a use-after-free. The window was always narrow and the swap always
// rare, but streaming the download makes the free happen before the new blob
// is read in, which widens it — so it gets closed rather than stretched.
//
// The store holds it only for pointer assignments, never across the download
// or the file read, so a frame never waits more than microseconds.
void geoStoreLock();
void geoStoreUnlock();

// Make the next geography poll due immediately, rather than at the end of
// GEO_POLL_INTERVAL_MS. Called when the Pi flags a freshly published map on a
// contact-poll response; the interval poll remains the fallback for a signal
// that was missed. Does no network work itself.
void geoStoreRefreshSoon();

const radar::GeoMap &geoMap();

// One line for the serial log, and later the status strip.
const char *geoStoreStatus();
