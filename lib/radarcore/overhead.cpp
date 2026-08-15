#include "overhead.h"
#include <math.h>

namespace radar {

namespace {

// 1nm because a lateral mile is about what "over the house" means when you
// look up; 150s because a prediction further out than two and a half minutes
// is guessing at an aircraft that has not decided yet; 8 deg/nm because a
// standard-rate turn is ~43 and position noise on straight flight is near
// zero, leaving a wide gap to put the line in.
const OverheadParams DEFAULTS = {1.0f, 150.0f, 8.0f};

OverheadParams s_params = DEFAULTS;

} // namespace

const OverheadParams &overheadParams() { return s_params; }

const OverheadParams &overheadParamsDefaults() { return DEFAULTS; }

void overheadParamsSet(const OverheadParams &p) {
  if (p.radiusNm > 0.0f) s_params.radiusNm = p.radiusNm;
  if (p.horizonS > 0.0f) s_params.horizonS = p.horizonS;
  if (p.maxTurnDegPerNm > 0.0f)
    s_params.maxTurnDegPerNm = p.maxTurnDegPerNm;
}

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
      if (turnPerNm > s_params.maxTurnDegPerNm) return false;
    }
    prevBearing = bearing;
    havePrev = true;
  }
  return havePrev;
}

OverheadPrediction predictOverhead(const AircraftStore &s, float extraAgeS) {
  OverheadPrediction best{};
  best.valid = false;
  float bestT = s_params.horizonS + 1.0f;

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
    if (t > s_params.horizonS) continue;

    float mx = px + vx * t, my = py + vy * t;
    float miss = sqrtf(mx * mx + my * my);
    if (miss > s_params.radiusNm) continue;

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
