#include "aircraft.h"
#include <math.h>
#include <string.h>

namespace radar {

void AircraftStore::clear() {
  count = 0;
}

void AircraftStore::insertByRange(const Aircraft &a) {
  int i = 0;
  while (i < count && list[i].range <= a.range) i++;
  if (i >= MAX_AIRCRAFT) return; // farther than everything in a full list
  int moveEnd = (count < MAX_AIRCRAFT) ? count : MAX_AIRCRAFT - 1;
  memmove(&list[i + 1], &list[i], (moveEnd - i) * sizeof(Aircraft));
  list[i] = a;
  if (count < MAX_AIRCRAFT) count++;
}

const Aircraft *AircraftStore::findByHex(uint32_t hex) const {
  for (int i = 0; i < count; i++)
    if (list[i].hex == hex) return &list[i];
  return nullptr;
}

Aircraft *AircraftStore::findByHex(uint32_t hex) {
  return const_cast<Aircraft *>(
      static_cast<const AircraftStore *>(this)->findByHex(hex));
}

static void pushTrailPoint(Aircraft &a) {
  if (a.trailLen > 0) {
    const TrailPoint &last = a.trail[(a.trailHead + TRAIL_LEN - 1) % TRAIL_LEN];
    // ~1e-4 deg =~ 10m: skip stationary aircraft so trails show movement
    if (fabsf(last.lat - a.lat) < 1e-4f && fabsf(last.lon - a.lon) < 1e-4f)
      return;
  }
  a.trail[a.trailHead] = {a.lat, a.lon};
  a.trailHead = (a.trailHead + 1) % TRAIL_LEN;
  if (a.trailLen < TRAIL_LEN) a.trailLen++;
}

void AircraftStore::inheritTrails(const AircraftStore &prev) {
  for (int i = 0; i < count; i++) {
    Aircraft &a = list[i];
    const Aircraft *p = prev.findByHex(a.hex);
    if (p) {
      memcpy(a.trail, p->trail, sizeof(a.trail));
      a.trailLen = p->trailLen;
      a.trailHead = p->trailHead;
    }
    pushTrailPoint(a);
  }
}

} // namespace radar
