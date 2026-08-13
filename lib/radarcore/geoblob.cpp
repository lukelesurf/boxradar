#include "geoblob.h"
#include "geostream.h"
#include <string.h>

namespace radar {

namespace {

const uint32_t HEADER_LEN = 28;
const uint32_t SECTION_ENTRY_LEN = 12;
const uint32_t CRC_START = 16;

// Every multi-byte read goes through these. Casting a const uint8_t* to a
// float* would be undefined behaviour and, on Xtensa, occasionally wrong in
// practice; memcpy of four bytes compiles to a single load when the address
// is aligned, so this costs nothing.
uint16_t readU16(const uint8_t *p) {
  uint16_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

uint32_t readU32(const uint8_t *p) {
  uint32_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

float readF32(const uint8_t *p) {
  float v;
  memcpy(&v, p, sizeof(v));
  return v;
}

// CRC-32 lives in geostream.cpp now, so the buffer reader and the streaming
// validator cannot drift apart. Having had two copies of an algorithm that
// must agree byte for byte was one bug waiting to happen.

bool nearly(float a, float b) {
  float d = a - b;
  if (d < 0) d = -d;
  return d <= GEO_HOME_TOLERANCE_DEG;
}

} // namespace

const char *geoStatusName(GeoStatus status) {
  switch (status) {
  case GEO_OK: return "ok";
  case GEO_BAD_MAGIC: return "not a geography blob";
  case GEO_BAD_VERSION: return "unsupported blob version";
  case GEO_TRUNCATED: return "blob truncated";
  case GEO_BAD_CRC: return "blob corrupt";
  case GEO_WRONG_HOME: return "blob is for a different location";
  }
  return "unknown";
}

GeoBlob::GeoBlob()
    : m_data(0), m_len(0), m_sectionCount(0), m_homeLat(0.0f),
      m_homeLon(0.0f), m_valid(false) {}

GeoStatus GeoBlob::open(const uint8_t *data, size_t len, float homeLat,
                        float homeLon) {
  m_valid = false;
  m_sectionCount = 0;
  if (!data || len < CRC_START) return GEO_TRUNCATED;
  if (memcmp(data, "BXRG", 4) != 0) return GEO_BAD_MAGIC;

  uint16_t version = readU16(data + 4);
  if (version != 1) return GEO_BAD_VERSION;

  uint32_t crc = readU32(data + 8);
  uint32_t bodyLen = readU32(data + 12);
  if (CRC_START + bodyLen > len) return GEO_TRUNCATED;
  if (geoCrc32(data + CRC_START, bodyLen) != crc) return GEO_BAD_CRC;

  float blobLat = readF32(data + CRC_START);
  float blobLon = readF32(data + CRC_START + 4);
  if (!nearly(blobLat, homeLat) || !nearly(blobLon, homeLon)) {
    return GEO_WRONG_HOME;
  }

  uint16_t count = readU16(data + CRC_START + 8);
  if (count > MAX_SECTIONS) return GEO_TRUNCATED;
  for (uint16_t i = 0; i < count; i++) {
    const uint8_t *entry = data + HEADER_LEN + i * SECTION_ENTRY_LEN;
    if ((size_t)(entry + SECTION_ENTRY_LEN - data) > len) return GEO_TRUNCATED;
    Section s;
    s.kind = readU16(entry);
    s.count = readU16(entry + 2);
    s.offset = readU32(entry + 4);
    s.length = readU32(entry + 8);
    if ((size_t)s.offset + s.length > len) return GEO_TRUNCATED;
    m_sections[m_sectionCount++] = s;
  }

  m_data = data;
  m_len = len;
  m_homeLat = blobLat;
  m_homeLon = blobLon;
  m_valid = true;
  return GEO_OK;
}

const GeoBlob::Section *GeoBlob::find(GeoKind kind) const {
  if (!m_valid) return 0;
  for (int i = 0; i < m_sectionCount; i++) {
    if (m_sections[i].kind == (uint16_t)kind) return &m_sections[i];
  }
  return 0;
}

uint16_t GeoBlob::recordCount(GeoKind kind) const {
  const Section *s = find(kind);
  return s ? s->count : 0;
}

bool GeoBlob::polyline(GeoKind kind, uint16_t index, GeoPolyline &out) const {
  const Section *s = find(kind);
  if (!s || index >= s->count) return false;
  uint32_t pos = s->offset;
  for (uint16_t i = 0; i < s->count; i++) {
    uint16_t n = readU16(m_data + pos);
    if (i == index) {
      out.count = n;
      // Legal only because the writer pads the count field to 4 bytes, so
      // this address is always 4-byte aligned.
      out.pts = (const GeoVertex *)(m_data + pos + 4);
      return true;
    }
    pos += 4 + (uint32_t)n * 8;
    if (pos > s->offset + s->length) return false;
  }
  return false;
}

const GeoNamedPoint *GeoBlob::namedPoints(GeoKind kind) const {
  if (kind != GEO_AIRFIELDS && kind != GEO_WAYPOINTS && kind != GEO_TOWNS) {
    return 0;
  }
  const Section *s = find(kind);
  if (!s) return 0;
  return (const GeoNamedPoint *)(m_data + s->offset);
}

const GeoRunway *GeoBlob::runways() const {
  const Section *s = find(GEO_RUNWAYS);
  if (!s) return 0;
  return (const GeoRunway *)(m_data + s->offset);
}

} // namespace radar
