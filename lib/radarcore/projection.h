#pragma once

namespace radar {

constexpr float NM_PER_DEG_LAT = 60.0f;

struct Vec2 {
  float x; // NM east of home
  float y; // NM north of home
};

// Equirectangular projection centred on home — fine at scope ranges.
//
// project() recomputes cos(homeLat) on every call, which is fine for the
// handful of points it was written for and wasteful in a loop over
// thousands. For those, hoist the scale out with lonScaleNm() once and call
// projectWith(); the coastline alone was costing ~19k cosf a second.
float lonScaleNm(float homeLat); // NM per degree of longitude at that latitude
Vec2 projectWith(float lonScale, float homeLat, float homeLon, float lat,
                 float lon);
Vec2 project(float homeLat, float homeLon, float lat, float lon);
float rangeNm(const Vec2 &v);
float bearingDeg(const Vec2 &v); // 0 = north, clockwise, [0, 360)

} // namespace radar
