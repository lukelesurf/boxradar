#pragma once

namespace radar {

constexpr float NM_PER_DEG_LAT = 60.0f;

struct Vec2 {
  float x; // NM east of home
  float y; // NM north of home
};

// Equirectangular projection centred on home — fine at scope ranges.
Vec2 project(float homeLat, float homeLon, float lat, float lon);
float rangeNm(const Vec2 &v);
float bearingDeg(const Vec2 &v); // 0 = north, clockwise, [0, 360)

} // namespace radar
