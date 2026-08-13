#pragma once
#include <stddef.h>
#include <stdint.h>
#include "geoblob.h"

// Validating a geography blob as it arrives, without ever holding it in
// memory.
//
// GeoBlob::open() needs the whole blob in a buffer, which is what forced
// geo_store to allocate a second full copy as scratch while the live one was
// still held — about 37.5KB wanted in two contiguous chunks. After a few hours
// the heap has 76KB free and no block that size, so the map only ever updated
// at boot. The fault was silent: the refresh returned, kept the old map, and
// nothing surfaced it.
//
// The format makes streaming easy. Magic, version, CRC and body length are the
// first sixteen bytes; home is the first eight bytes of the body; and the CRC
// covers exactly [16, 16 + bodyLen). So everything open() checks except the
// section table can be checked on the way past, for the cost of a 24-byte
// buffer. The section table is checked later, by open(), once the blob is in
// memory — by then it is known to be intact and for the right site, which is
// what the download had to establish before anything was freed.
//
// Portable: stdint only, no Arduino, so the arithmetic is tested off device.

namespace radar {

// CRC-32 (IEEE 802.3, reflected), matching Python's zlib.crc32 — the same
// algorithm the one-shot geoCrc32() uses, exposed in three parts so it can be
// fed a socket a chunk at a time.
uint32_t geoCrc32Begin();
uint32_t geoCrc32Update(uint32_t state, const uint8_t *data, size_t len);
uint32_t geoCrc32End(uint32_t state);

// One-shot, for callers with the whole buffer.
uint32_t geoCrc32(const uint8_t *data, size_t len);

class GeoStreamCheck {
public:
  // `homeLat`/`homeLon` are the board's own position: a blob built for
  // somewhere else must be refused, or it would draw another area's map with
  // no indication.
  void begin(float homeLat, float homeLon);

  // Feed the bytes in the order they arrive, in any sized pieces.
  void feed(const uint8_t *data, size_t len);

  // `totalLen` is how many bytes actually arrived. GEO_OK means the blob is
  // intact, the right version, and for this site.
  GeoStatus finish(size_t totalLen);

private:
  static const size_t HEAD_LEN = 24;  // through home lat/lon

  float m_homeLat;
  float m_homeLon;
  uint8_t m_head[HEAD_LEN];
  size_t m_headLen;
  size_t m_seen;
  uint32_t m_crc;
  bool m_crcStarted;
};

} // namespace radar
