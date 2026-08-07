#include "projection.h"
#include <math.h>

namespace radar {

float lonScaleNm(float homeLat) {
  return NM_PER_DEG_LAT * cosf(homeLat * (float)M_PI / 180.0f);
}

Vec2 projectWith(float lonScale, float homeLat, float homeLon, float lat,
                 float lon) {
  return {(lon - homeLon) * lonScale, (lat - homeLat) * NM_PER_DEG_LAT};
}

// Single-shot form. Defined in terms of the hoisted pair so there is only
// one projection implementation to keep correct.
Vec2 project(float homeLat, float homeLon, float lat, float lon) {
  return projectWith(lonScaleNm(homeLat), homeLat, homeLon, lat, lon);
}

float rangeNm(const Vec2 &v) { return sqrtf(v.x * v.x + v.y * v.y); }

float bearingDeg(const Vec2 &v) {
  float b = atan2f(v.x, v.y) * 180.0f / (float)M_PI;
  return b < 0 ? b + 360.0f : b;
}

} // namespace radar
