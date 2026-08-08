#pragma once

// One indirection so scope.cpp can draw from either the tables compiled into
// flash or the geography blob fetched at runtime, selected by MAP_FROM_BLOB.
//
// Both sources already expose the same shapes — {float lat, lon} vertices,
// a count, and named points with a `name` field — so this needs no casting and
// no copying. The loop bodies in scope.cpp are untouched; only what they
// iterate over changes.
//
// The blob is now the default, enabled by MAP_FROM_BLOB in config.h and
// verified against the compiled tables on the panel (2026-08-08). The tables
// stay in the repo as regenerable output and remain one build flag away, so
// there is still a known-good reference to fall back to.

#include <stdint.h>
// Included here, not left to the caller: a missing config.h would make the
// #ifdef below compile to nothing and silently pick the wrong map source.
#include "config.h"

#ifdef MAP_FROM_BLOB
#include "geo_store.h"

// Minimal iterable view, so a range-for keeps working over a pointer+count.
// C++11: no std::span, and lib/radarcore has to stay free of the STL anyway.
template <typename T> struct MapSpan {
  const T *p;
  uint16_t n;
  const T *begin() const { return p; }
  const T *end() const { return p ? p + n : p; }
};

using MapPolyline = radar::GeoPolyline;
using MapBox = radar::GeoBox;

static inline uint16_t mapAirspaceCount() { return geoMap().airspaceCount(); }
static inline bool mapAirspace(uint16_t i, MapPolyline &out) {
  return geoMap().airspace(i, out);
}
static inline uint16_t mapCoastCount() { return geoMap().coastCount(); }
static inline bool mapCoast(uint16_t i, MapPolyline &out, MapBox &box) {
  return geoMap().coast(i, out, box);
}

#define MAP_AIRFIELDS                                                          \
  (MapSpan<radar::GeoNamedPoint>{geoMap().airfields(),                          \
                                 geoMap().airfieldCount()})
#define MAP_WAYPOINTS                                                          \
  (MapSpan<radar::GeoNamedPoint>{geoMap().waypoints(),                          \
                                 geoMap().waypointCount()})
#define MAP_TOWNS                                                              \
  (MapSpan<radar::GeoNamedPoint>{geoMap().towns(), geoMap().townCount()})
#define MAP_RUNWAYS                                                            \
  (MapSpan<radar::GeoRunway>{geoMap().runways(), geoMap().runwayCount()})

#else // compiled tables

#include "airspace_data.h"
#include "location.h"

struct MapPolyline {
  const airspace::Vertex *pts;
  uint16_t count;
};
struct MapBox {
  float minLat, maxLat, minLon, maxLon;
};

static inline uint16_t mapAirspaceCount() {
  return (uint16_t)(sizeof(airspace::OUTLINES) / sizeof(airspace::OUTLINES[0]));
}
static inline bool mapAirspace(uint16_t i, MapPolyline &out) {
  if (i >= mapAirspaceCount()) return false;
  out.pts = airspace::OUTLINES[i].pts;
  out.count = airspace::OUTLINES[i].count;
  return true;
}

#ifdef DRAW_COASTLINE
#include "coastline_data.h"
static inline uint16_t mapCoastCount() {
  return (uint16_t)(sizeof(coastline::SEGMENTS) /
                    sizeof(coastline::SEGMENTS[0]));
}
static inline bool mapCoast(uint16_t i, MapPolyline &out, MapBox &box) {
  if (i >= mapCoastCount()) return false;
  const coastline::Outline &o = coastline::SEGMENTS[i];
  // Reinterpreting one {float lat, lon} vertex type as the other is safe and
  // avoids a copy: both namespaces declare the identical layout.
  out.pts = (const airspace::Vertex *)o.pts;
  out.count = o.count;
  box.minLat = o.minLat;
  box.maxLat = o.maxLat;
  box.minLon = o.minLon;
  box.maxLon = o.maxLon;
  return true;
}
#else
static inline uint16_t mapCoastCount() { return 0; }
static inline bool mapCoast(uint16_t, MapPolyline &, MapBox &) { return false; }
#endif

#define MAP_AIRFIELDS AIRFIELDS
#define MAP_WAYPOINTS WAYPOINTS
#define MAP_TOWNS TOWNS
#define MAP_RUNWAYS RUNWAYS

#endif
