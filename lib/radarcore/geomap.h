#pragma once
#include "geoblob.h"

// What the renderer actually wants, over what the blob actually stores.
//
// One gap to close: coastline bounding boxes. src/ui/coastline_data.h carries
// them because they are most of the per-frame reject cost — "the bounding box
// lets the renderer reject an entire segment with four comparisons instead of
// projecting every one of its points". The blob deliberately does NOT store
// them, because a stored bbox can disagree with its own points and the symptom
// is a coastline that silently fails to draw. So they are computed here, once,
// at open.
//
// Portable: no Arduino, no TFT_eSPI, and must compile under gnu++11 as well as
// gnu++17.

namespace radar {

struct GeoBox {
  float minLat, maxLat, minLon, maxLon;
};

class GeoMap {
public:
  // Fixed cap because the box array is statically allocated: 192 * 16 bytes =
  // 3KB, against 124 segments for the current site. Segments beyond this are
  // dropped and counted, never dropped silently — the README already documents
  // MAX_AIRCRAFT's cliff, where "the count pins at 32 and distant contacts
  // vanish with no other indication", and a half-drawn coastline looks exactly
  // like a correct one.
  static const uint16_t MAX_COAST_SEGMENTS = 192;

  GeoMap();

  GeoStatus open(const uint8_t *data, size_t len, float homeLat,
                 float homeLon);

  bool valid() const { return m_blob.valid(); }

  uint16_t airspaceCount() const;
  bool airspace(uint16_t index, GeoPolyline &out) const;

  uint16_t coastCount() const { return m_coastCount; }
  bool coast(uint16_t index, GeoPolyline &out, GeoBox &box) const;
  uint16_t coastDropped() const { return m_coastDropped; }

  uint16_t airfieldCount() const;
  const GeoNamedPoint *airfields() const;

  uint16_t runwayCount() const;
  const GeoRunway *runways() const;

  uint16_t waypointCount() const;
  const GeoNamedPoint *waypoints() const;

  uint16_t townCount() const;
  const GeoNamedPoint *towns() const;

private:
  void reset();
  void buildCoastBoxes();

  GeoBlob m_blob;
  GeoBox m_coastBoxes[MAX_COAST_SEGMENTS];
  uint16_t m_coastCount;
  uint16_t m_coastDropped;
};

} // namespace radar
