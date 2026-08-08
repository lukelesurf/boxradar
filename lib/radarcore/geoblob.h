#pragma once
#include <stddef.h>
#include <stdint.h>

// Reader for the geography blob written by boxradar_site.geo.
//
// Zero copy by design. open() validates the buffer and records section
// offsets; every accessor then points INTO that buffer, which the caller owns
// and must keep alive for as long as the GeoBlob is used. That is what makes
// this cost one allocation instead of one per record, and it is only legal
// because the writer pads every vertex array to a 4-byte boundary.
//
// Portable on purpose: stdint and string.h only, no Arduino, no TFT_eSPI, so
// it links in [env:native] and is tested off device. It must also compile
// under gnu++11, which is what the ESP32 core uses — no default member
// initialisers in aggregates.

namespace radar {

struct GeoVertex {
  float lat, lon;
};

struct GeoPolyline {
  const GeoVertex *pts;
  uint16_t count;
};

struct GeoNamedPoint {
  char name[8];
  float lat, lon;
};

struct GeoRunway {
  float lat0, lon0, lat1, lon1;
};

enum GeoKind {
  GEO_AIRSPACE = 1,
  GEO_COASTLINE = 2,
  GEO_AIRFIELDS = 3,
  GEO_RUNWAYS = 4,
  GEO_WAYPOINTS = 5,
  GEO_TOWNS = 6,
};

enum GeoStatus {
  GEO_OK = 0,
  GEO_BAD_MAGIC,
  GEO_BAD_VERSION,
  GEO_TRUNCATED,
  GEO_BAD_CRC,
  GEO_WRONG_HOME,
};

const char *geoStatusName(GeoStatus status);

// Home must match to within this, in degrees (~11m). A blob generated for a
// different site would otherwise render the previous area's map with no
// indication, which the README already documents as the trap here.
const float GEO_HOME_TOLERANCE_DEG = 0.0001f;

class GeoBlob {
public:
  GeoBlob();

  GeoStatus open(const uint8_t *data, size_t len, float homeLat,
                 float homeLon);

  bool valid() const { return m_valid; }
  float homeLat() const { return m_homeLat; }
  float homeLon() const { return m_homeLon; }

  uint16_t recordCount(GeoKind kind) const;

  // Walks from the start of the section, so this is O(index). The render
  // passes iterate in order, and an index would be data the file does not
  // need to carry.
  bool polyline(GeoKind kind, uint16_t index, GeoPolyline &out) const;

  const GeoNamedPoint *namedPoints(GeoKind kind) const;
  const GeoRunway *runways() const;

private:
  static const int MAX_SECTIONS = 8;

  struct Section {
    uint16_t kind;
    uint16_t count;
    uint32_t offset;
    uint32_t length;
  };

  const Section *find(GeoKind kind) const;

  const uint8_t *m_data;
  size_t m_len;
  Section m_sections[MAX_SECTIONS];
  int m_sectionCount;
  float m_homeLat;
  float m_homeLon;
  bool m_valid;
};

} // namespace radar
