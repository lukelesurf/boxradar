#include "overhead.h"
#include <math.h>

namespace radar {

// Trail points are a ring buffer; this walks them oldest -> newest.
static Vec2 trailAt(const Aircraft &a, int i) {
  int idx = (a.trailHead - a.trailLen + i + 2 * TRAIL_LEN) % TRAIL_LEN;
  return a.trail[idx];
}

// Signed smallest angle between two bearings, in degrees.
static float angleDelta(float a, float b) {
  float d = fmodf(b - a + 540.0f, 360.0f) - 180.0f;
  return d;
}

bool isTrackSteady(const Aircraft &a) {
  if (a.trailLen < OVERHEAD_MIN_TRAIL) return false;

  float prevBearing = 0.0f;
  bool havePrev = false;
  for (int i = 1; i < a.trailLen; i++) {
    Vec2 p0 = trailAt(a, i - 1), p1 = trailAt(a, i);
    float dx = p1.x - p0.x, dy = p1.y - p0.y;
    float len = sqrtf(dx * dx + dy * dy);
    if (len < 1e-4f) continue; // duplicate point: no bearing to derive
    float bearing = atan2f(dx, dy) * 180.0f / (float)M_PI;
    if (havePrev) {
      // Normalise by distance so the threshold is curvature, independent of
      // both groundspeed and the current trail spacing.
      float turnPerNm = fabsf(angleDelta(prevBearing, bearing)) / len;
      if (turnPerNm > OVERHEAD_MAX_TURN_DEG_PER_NM) return false;
    }
    prevBearing = bearing;
    havePrev = true;
  }
  return havePrev;
}

OverheadPrediction predictOverhead(const AircraftStore &s, float extraAgeS) {
  OverheadPrediction best{};
  best.valid = false;
  float bestT = OVERHEAD_HORIZON_S + 1.0f;

  for (int i = 0; i < s.count; i++) {
    const Aircraft &a = s.list[i];
    if (a.onGround || a.gsKt < OVERHEAD_MIN_GS_KT) continue;
    if (!isTrackSteady(a)) continue;

    // Velocity in NM/s. Track is degrees true, clockwise from north, so it
    // maps to (sin, cos) rather than the usual (cos, sin).
    float rad = a.trackDeg * (float)M_PI / 180.0f;
    float speed = a.gsKt / 3600.0f;
    float vx = sinf(rad) * speed, vy = cosf(rad) * speed;
    float vv = vx * vx + vy * vy;
    if (vv < 1e-12f) continue;

    // Advance the reported position to now: it was already `seenS` old when
    // parsed, and the poll itself is up to a couple of seconds behind.
    float age = a.seenS + extraAgeS;
    float px = a.pos.x + vx * age, py = a.pos.y + vy * age;

    // Home is the origin in this frame, so closest approach is just the
    // projection of -p onto v.
    float t = -(px * vx + py * vy) / vv;
    if (t < 0.0f) continue;            // already past its closest point
    if (t > OVERHEAD_HORIZON_S) continue;

    float mx = px + vx * t, my = py + vy * t;
    float miss = sqrtf(mx * mx + my * my);
    if (miss > OVERHEAD_RADIUS_NM) continue;

    if (t < bestT) {
      bestT = t;
      best.hex = a.hex;
      best.secondsAway = (uint16_t)(t + 0.5f);
      best.missNm = miss;
      best.valid = true;
    }
  }
  return best;
}

} // namespace radar
