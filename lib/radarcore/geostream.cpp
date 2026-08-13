#include "geostream.h"
#include <string.h>

namespace radar {

namespace {

const size_t CRC_START = 16;   // matches geoblob.cpp
const size_t HEAD_LEN = 24;    // through home lat/lon

uint16_t readU16(const uint8_t *p) {
  return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
uint32_t readU32(const uint8_t *p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
         ((uint32_t)p[3] << 24);
}
float readF32(const uint8_t *p) {
  float v;
  memcpy(&v, p, 4);
  return v;
}

bool nearly(float a, float b) {
  float d = a - b;
  if (d < 0) d = -d;
  return d <= GEO_HOME_TOLERANCE_DEG;
}

} // namespace

uint32_t geoCrc32Begin() { return 0xFFFFFFFFu; }

uint32_t geoCrc32Update(uint32_t state, const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; i++) {
    state ^= data[i];
    for (int b = 0; b < 8; b++) {
      // Branchless mask, as in geoblob.cpp: (~(crc & 1) + 1) is 0xFFFFFFFF
      // when the low bit is set and 0 when it is not.
      state = (state >> 1) ^ (0xEDB88320u & (~(state & 1u) + 1u));
    }
  }
  return state;
}

uint32_t geoCrc32End(uint32_t state) { return ~state; }

uint32_t geoCrc32(const uint8_t *data, size_t len) {
  return geoCrc32End(geoCrc32Update(geoCrc32Begin(), data, len));
}

void GeoStreamCheck::begin(float homeLat, float homeLon) {
  m_homeLat = homeLat;
  m_homeLon = homeLon;
  m_headLen = 0;
  m_seen = 0;
  m_crc = geoCrc32Begin();
  m_crcStarted = false;
  memset(m_head, 0, sizeof(m_head));
}

void GeoStreamCheck::feed(const uint8_t *data, size_t len) {
  for (size_t i = 0; i < len; i++) {
    // The first 24 bytes are kept, because the header spans chunk boundaries
    // when the body arrives 512 bytes at a time and the fields have to be
    // read whole.
    if (m_headLen < HEAD_LEN) m_head[m_headLen++] = data[i];
    // Everything from CRC_START on is covered by the checksum, including the
    // home bytes that are also part of the header.
    if (m_seen >= CRC_START) {
      m_crc = geoCrc32Update(m_crc, data + i, 1);
      m_crcStarted = true;
    }
    m_seen++;
  }
}

GeoStatus GeoStreamCheck::finish(size_t totalLen) {
  if (m_headLen < HEAD_LEN || totalLen < HEAD_LEN) return GEO_TRUNCATED;
  if (memcmp(m_head, "BXRG", 4) != 0) return GEO_BAD_MAGIC;
  if (readU16(m_head + 4) != 1) return GEO_BAD_VERSION;

  uint32_t want = readU32(m_head + 8);
  uint32_t bodyLen = readU32(m_head + 12);
  // The body has to have actually arrived. Declaring more than was sent is
  // how a truncated download presents, and it must never reach the CRC
  // comparison — a short read that happened to checksum would be worse.
  if (CRC_START + bodyLen > totalLen) return GEO_TRUNCATED;
  if (!m_crcStarted) return GEO_TRUNCATED;

  // The CRC covers exactly bodyLen bytes from CRC_START. Anything after that
  // is not part of the checksummed region, so a blob with trailing bytes is
  // refused rather than quietly accepted on a partial match.
  if (m_seen != CRC_START + bodyLen) return GEO_TRUNCATED;
  if (geoCrc32End(m_crc) != want) return GEO_BAD_CRC;

  if (!nearly(readF32(m_head + 16), m_homeLat) ||
      !nearly(readF32(m_head + 20), m_homeLon)) {
    return GEO_WRONG_HOME;
  }
  return GEO_OK;
}

} // namespace radar
