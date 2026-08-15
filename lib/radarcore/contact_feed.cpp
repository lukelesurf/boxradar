#include "contact_feed.h"
#include <string.h>
#include "projection.h"

namespace radar {

namespace {

const char MAGIC[4] = {'B', 'X', 'A', 'C'};

// Same reasoning as geoblob.cpp: casting a const uint8_t* to a wider type is
// undefined behaviour and, on Xtensa, occasionally wrong in practice. memcpy
// of two or four bytes compiles to a single load at an aligned address, and
// every field in this format is aligned by construction.
uint16_t readU16(const uint8_t *p) {
  uint16_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

int16_t readI16(const uint8_t *p) {
  int16_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

uint32_t readU32(const uint8_t *p) {
  uint32_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

int32_t readI32(const uint8_t *p) {
  int32_t v;
  memcpy(&v, p, sizeof(v));
  return v;
}

// Fixed-width wire text into a NUL-terminated field. The writer pads with NUL
// and does its own trimming, so this only has to guarantee the terminator the
// wire cannot carry when a name fills its field exactly.
void copyText(char *dst, size_t dstCap, const uint8_t *src, size_t width) {
  size_t n = width < dstCap - 1 ? width : dstCap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

} // namespace

const char *contactStatusName(ContactStatus status) {
  switch (status) {
  case CONTACT_OK: return "ok";
  case CONTACT_BAD_MAGIC: return "not a contact feed";
  case CONTACT_BAD_VERSION: return "unsupported feed version";
  case CONTACT_BAD_RECORD_LEN: return "record length mismatch";
  case CONTACT_TRUNCATED: return "truncated payload";
  }
  return "unknown";
}

ContactStatus loadContacts(const uint8_t *data, size_t len, AircraftStore &dst,
                           const AircraftStore &prev, float homeLat,
                           float homeLon, float trailSpacingNm) {
  dst.clear();
  dst.feedTotal = 0;

  if (len < (size_t)CONTACT_HEADER_LEN) return CONTACT_TRUNCATED;
  if (memcmp(data, MAGIC, sizeof(MAGIC)) != 0) return CONTACT_BAD_MAGIC;
  if (readU16(data + 4) != CONTACT_VERSION) return CONTACT_BAD_VERSION;
  // Checked before anything is decoded. A record length we do not recognise
  // means a Pi and a board from different builds, and misparsing that into
  // plausible-looking traffic is far worse than refusing it.
  if (readU16(data + 6) != CONTACT_RECORD_LEN) return CONTACT_BAD_RECORD_LEN;

  uint16_t count = readU16(data + 8);
  uint16_t total = readU16(data + 10);
  if (len < (size_t)CONTACT_HEADER_LEN + (size_t)count * CONTACT_RECORD_LEN)
    return CONTACT_TRUNCATED;

  // One cosf for the whole payload rather than one per contact.
  float lonScale = lonScaleNm(homeLat);

  for (uint16_t i = 0; i < count; i++) {
    const uint8_t *r = data + CONTACT_HEADER_LEN + i * CONTACT_RECORD_LEN;
    Aircraft a;
    memset(&a, 0, sizeof(a));

    a.hex = readU32(r + 0);
    a.lat = (float)readI32(r + 4) / 1e7f;
    a.lon = (float)readI32(r + 8) / 1e7f;
    copyText(a.callsign, sizeof(a.callsign), r + 12, 8);
    copyText(a.type, sizeof(a.type), r + 20, 4);
    copyText(a.squawk, sizeof(a.squawk), r + 24, 4);
    a.altFt = (int32_t)readI16(r + 28) * 25;
    a.gsKt = readU16(r + 30);
    a.trackDeg = readU16(r + 32);
    a.vertRateFpm = (int16_t)(readI16(r + 34) * 64);
    a.seenS = (float)r[36];
    a.rssi = (float)(int8_t)r[37] / 2.0f;

    uint8_t flags = r[38];
    a.onGround = (flags & 0x01) != 0;
    a.isMlat = (flags & 0x02) != 0;
    // Bit 2 was spare, which is why the watchlist needed no CONTACT_VERSION
    // bump: firmware built before it existed reads this byte and ignores the
    // bit, and a Pi built before it existed never sets it.
    a.isWatched = (flags & 0x04) != 0;
    // The wire cannot carry an altitude for an aircraft on the ground, and
    // parse.cpp reported 0 there. Kept identical so the change is transport
    // only — format.cpp renders "GND" off onGround, not off the number.
    if (a.onGround) a.altFt = 0;

    a.pos = projectWith(lonScale, homeLat, homeLon, a.lat, a.lon);
    a.range = rangeNm(a.pos);

    // The payload is already range-sorted, so this appends and memmoves
    // nothing. Going through insertByRange anyway costs a comparison per
    // record and keeps the store's ordering invariant true even if a future
    // sender gets it wrong — everything downstream assumes nearest-first.
    dst.insertByRange(a);
  }

  // Reported by the Pi before its own cap, so it can exceed dst.count. That
  // difference IS the display's "32/58": the README documents the cap as a
  // silent cliff, and this is what stops it being silent.
  dst.feedTotal = total;
  dst.inheritTrails(prev, trailSpacingNm);
  return CONTACT_OK;
}

} // namespace radar
