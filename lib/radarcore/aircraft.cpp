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

static void pushTrailPoint(Aircraft &a, float minSpacingNm) {
  // A zero or negative spacing would push on every poll, which is the
  // time-gated behaviour this replaced; floor it rather than trust callers.
  if (!(minSpacingNm > 0.001f)) minSpacingNm = 0.001f;
  if (a.trailLen > 0) {
    const Vec2 &last = a.trail[(a.trailHead + TRAIL_LEN - 1) % TRAIL_LEN];
    float dx = a.pos.x - last.x, dy = a.pos.y - last.y;
    // Slow traffic simply skips polls until it has actually travelled far
    // enough, so it needs no more storage than a fast jet — the ring covers
    // the same ground distance either way, just over a longer span of time.
    if (dx * dx + dy * dy < minSpacingNm * minSpacingNm) return;
  }
  a.trail[a.trailHead] = a.pos;
  a.trailHead = (a.trailHead + 1) % TRAIL_LEN;
  if (a.trailLen < TRAIL_LEN) a.trailLen++;
}

void AircraftStore::inheritTrails(const AircraftStore &prev,
                                  float minSpacingNm) {
  for (int i = 0; i < count; i++) {
    Aircraft &a = list[i];
    const Aircraft *p = prev.findByHex(a.hex);
    if (p) {
      memcpy(a.trail, p->trail, sizeof(a.trail));
      a.trailLen = p->trailLen;
      a.trailHead = p->trailHead;
    }
    pushTrailPoint(a, minSpacingNm);
  }
}

} // namespace radar
