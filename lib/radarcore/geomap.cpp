#include "geomap.h"

namespace radar {

GeoMap::GeoMap() : m_coastCount(0), m_coastDropped(0) {}

void GeoMap::reset() {
  m_coastCount = 0;
  m_coastDropped = 0;
}

GeoStatus GeoMap::open(const uint8_t *data, size_t len, float homeLat,
                       float homeLon) {
  // Reset first, so a failed refetch cannot leave the previous blob's boxes
  // pointing into a buffer that is about to be freed.
  reset();
  GeoStatus status = m_blob.open(data, len, homeLat, homeLon);
  if (status != GEO_OK) return status;
  buildCoastBoxes();
  return GEO_OK;
}

void GeoMap::buildCoastBoxes() {
  uint16_t total = m_blob.recordCount(GEO_COASTLINE);
  uint16_t keep = total;
  if (keep > MAX_COAST_SEGMENTS) {
    keep = MAX_COAST_SEGMENTS;
    m_coastDropped = total - keep;
  }
  for (uint16_t i = 0; i < keep; i++) {
    GeoPolyline line;
    if (!m_blob.polyline(GEO_COASTLINE, i, line) || line.count == 0) {
      // A malformed record ends the usable run: indices past it would be
      // walked from a bad offset anyway.
      m_coastDropped = total - i;
      m_coastCount = i;
      return;
    }
    GeoBox box;
    box.minLat = box.maxLat = line.pts[0].lat;
    box.minLon = box.maxLon = line.pts[0].lon;
    for (uint16_t j = 1; j < line.count; j++) {
      float lat = line.pts[j].lat;
      float lon = line.pts[j].lon;
      if (lat < box.minLat) box.minLat = lat;
      if (lat > box.maxLat) box.maxLat = lat;
      if (lon < box.minLon) box.minLon = lon;
      if (lon > box.maxLon) box.maxLon = lon;
    }
    m_coastBoxes[i] = box;
  }
  m_coastCount = keep;
}

uint16_t GeoMap::airspaceCount() const {
  return m_blob.recordCount(GEO_AIRSPACE);
}

bool GeoMap::airspace(uint16_t index, GeoPolyline &out) const {
  return m_blob.polyline(GEO_AIRSPACE, index, out);
}

bool GeoMap::coast(uint16_t index, GeoPolyline &out, GeoBox &box) const {
  if (index >= m_coastCount) return false;
  if (!m_blob.polyline(GEO_COASTLINE, index, out)) return false;
  box = m_coastBoxes[index];
  return true;
}

uint16_t GeoMap::airfieldCount() const {
  return m_blob.recordCount(GEO_AIRFIELDS);
}

const GeoNamedPoint *GeoMap::airfields() const {
  return m_blob.namedPoints(GEO_AIRFIELDS);
}

uint16_t GeoMap::runwayCount() const {
  return m_blob.recordCount(GEO_RUNWAYS);
}

const GeoRunway *GeoMap::runways() const { return m_blob.runways(); }

uint16_t GeoMap::waypointCount() const {
  return m_blob.recordCount(GEO_WAYPOINTS);
}

const GeoNamedPoint *GeoMap::waypoints() const {
  return m_blob.namedPoints(GEO_WAYPOINTS);
}

uint16_t GeoMap::townCount() const {
  return m_blob.recordCount(GEO_TOWNS);
}

const GeoNamedPoint *GeoMap::towns() const {
  return m_blob.namedPoints(GEO_TOWNS);
}

} // namespace radar
