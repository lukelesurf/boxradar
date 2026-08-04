#include "projection.h"
#include <math.h>

namespace radar {

Vec2 project(float homeLat, float homeLon, float lat, float lon) {
  float cosLat = cosf(homeLat * (float)M_PI / 180.0f);
  return {(lon - homeLon) * NM_PER_DEG_LAT * cosLat,
          (lat - homeLat) * NM_PER_DEG_LAT};
}

float rangeNm(const Vec2 &v) { return sqrtf(v.x * v.x + v.y * v.y); }

float bearingDeg(const Vec2 &v) {
  float b = atan2f(v.x, v.y) * 180.0f / (float)M_PI;
  return b < 0 ? b + 360.0f : b;
}

} // namespace radar
