#include "scope.h"
#include "status_bar.h"
#include "datablock.h"
#include "palette.h"
#include "format.h"
#include "classify.h"
#include "projection.h"
#include "config.h"
#include "location.h"
#include <Arduino.h>
#include <math.h>
#include <stdio.h>
#include "airspace_data.h"
#ifdef DRAW_COASTLINE
// Guarded so the generated table is not linked in at all when disabled —
// it is ~12KB of flash that a landlocked install has no use for.
#include "coastline_data.h"
#endif
#ifdef OVERHEAD_PREDICTION
#include "overhead_readout.h"
#endif

static constexpr uint32_t ALERT_FLASH_MS = 400;
static constexpr int BANNER_H = 14;

// Airfield and runway tables live in include/location.h — all the geography
// is in one committed file so relocating the scope does not mean hunting
// through render code.
static constexpr float CENTRELINE_NM = 6.5f; // extension beyond each end
static constexpr int DASH_ON = 6, DASH_OFF = 5;

// Dashes are stepped in pixels, not nautical miles: an NM-based dash would
// collapse into an unreadable stipple once the scope is at 50nm.
static void drawDashedLine(TFT_eSprite &spr, float x0, float y0, float x1,
                           float y1, uint16_t col) {
  float dx = x1 - x0, dy = y1 - y0;
  float len = sqrtf(dx * dx + dy * dy);
  if (len < 1.0f) return;
  float ux = dx / len, uy = dy / len;
  for (float d = 0; d < len; d += DASH_ON + DASH_OFF) {
    float e = d + DASH_ON;
    if (e > len) e = len;
    spr.drawLine((int)(x0 + ux * d), (int)(y0 + uy * d),
                 (int)(x0 + ux * e), (int)(y0 + uy * e), col);
  }
}

static void drawCentrelines(TFT_eSprite &spr, float pxPerNm, float lonScale) {
  for (const auto &r : RUNWAYS) {
    radar::Vec2 a = radar::projectWith(lonScale, HOME_LAT, HOME_LON, r.lat0, r.lon0);
    radar::Vec2 b = radar::projectWith(lonScale, HOME_LAT, HOME_LON, r.lat1, r.lon1);
    float dx = b.x - a.x, dy = b.y - a.y;
    float len = sqrtf(dx * dx + dy * dy);
    if (len < 1e-4f) continue; // degenerate entry: skip rather than divide
    float ux = dx / len, uy = dy / len;
    // Extend past BOTH thresholds. The stretch between them is the runway
    // itself, under 2nm long and not the interesting part — the approach
    // paths either side are what make the arrival stream legible.
    float ax = a.x - ux * CENTRELINE_NM, ay = a.y - uy * CENTRELINE_NM;
    float bx = b.x + ux * CENTRELINE_NM, by = b.y + uy * CENTRELINE_NM;
    drawDashedLine(spr, SCOPE_CX + ax * pxPerNm, SCOPE_CY - ay * pxPerNm,
                   SCOPE_CX + bx * pxPerNm, SCOPE_CY - by * pxPerNm,
                   CENTRELINE);
  }
}

#ifdef DRAW_COASTLINE
// ~1900 points, an order of magnitude more than everything else on the map,
// so this is the one layer where the per-point cost actually matters.
//
// Two things keep it cheap. The whole panel is converted to a lat/lon window
// once per frame, letting an entire segment be rejected on four comparisons
// without projecting any of its points — at 10nm inland that discards the
// lot. Survivors then project with a hoisted longitude scale rather than
// recomputing cosf per point.
static void drawCoastline(TFT_eSprite &spr, float pxPerNm, float lonScale) {
  const float invP = 1.0f / pxPerNm;
  const float minLat = HOME_LAT + ((float)(SCOPE_CY - STATUS_Y) * invP) / 60.0f;
  const float maxLat = HOME_LAT + ((float)SCOPE_CY * invP) / 60.0f;
  const float minLon = HOME_LON - ((float)SCOPE_CX * invP) / lonScale;
  const float maxLon =
      HOME_LON + ((float)(SCOPE_W - SCOPE_CX) * invP) / lonScale;

  for (const coastline::Outline &o : coastline::SEGMENTS) {
    if (o.maxLat < minLat || o.minLat > maxLat || o.maxLon < minLon ||
        o.minLon > maxLon)
      continue; // wholly off-panel: no points projected at all
    int prevX = 0, prevY = 0;
    for (uint16_t i = 0; i < o.count; i++) {
      radar::Vec2 p = radar::projectWith(lonScale, HOME_LAT, HOME_LON,
                                         o.pts[i].lat, o.pts[i].lon);
      int x = SCOPE_CX + (int)(p.x * pxPerNm);
      int y = SCOPE_CY - (int)(p.y * pxPerNm);
      if (i > 0) {
        // Per-line trivial reject for the surviving segments: a segment can
        // straddle the window while most of its individual spans do not.
        bool offscreen = (x < 0 && prevX < 0) ||
                         (x >= SCOPE_W && prevX >= SCOPE_W) ||
                         (y < 0 && prevY < 0) ||
                         (y >= STATUS_Y && prevY >= STATUS_Y);
        if (!offscreen) spr.drawLine(prevX, prevY, x, y, COAST_LINE);
      }
      prevX = x;
      prevY = y;
    }
  }
}
#endif // DRAW_COASTLINE

// Outlines are closed rings (last vertex repeats the first), reprojected
// every frame — ~200 projections, cheaper than caching per range change.
static void drawAirspace(TFT_eSprite &spr, float pxPerNm, float lonScale) {
  for (const airspace::Outline &o : airspace::OUTLINES) {
    int prevX = 0, prevY = 0;
    for (uint16_t i = 0; i < o.count; i++) {
      radar::Vec2 p =
          radar::projectWith(lonScale, HOME_LAT, HOME_LON, o.pts[i].lat, o.pts[i].lon);
      int x = SCOPE_CX + (int)(p.x * pxPerNm);
      int y = SCOPE_CY - (int)(p.y * pxPerNm);
      if (i > 0) spr.drawLine(prevX, prevY, x, y, AIRSPACE_LINE);
      prevX = x;
      prevY = y;
    }
  }
}

// Hollow triangle plus a short label — the chart convention for a reporting
// point, and distinct from the solid squares used for airfields.
//
// Drawn after the rings but before any traffic, so a datablock always wins
// where the two overlap. Waypoints deliberately do NOT reserve occupancy
// grid cells: they are scenery, and blocking label placement over a fixed
// point would push live traffic around to protect static furniture.
// Shape carries the category so the two are tellable apart at 5px without
// reading the label: triangle for a navigation fix, square for a town.
static void drawFixedRefs(TFT_eSprite &spr, float pxPerNm, float lonScale) {
  // Airfields first and a shade brighter than the rest: they are the anchors
  // you orient from, and a hollow marker sitting on its own centreline was
  // all but invisible.
  spr.setTextColor(AIRFIELD_MARK, TFT_BLACK);
  for (const auto &f : AIRFIELDS) {
    radar::Vec2 p =
        radar::projectWith(lonScale, HOME_LAT, HOME_LON, f.lat, f.lon);
    int x = SCOPE_CX + (int)(p.x * pxPerNm);
    int y = SCOPE_CY - (int)(p.y * pxPerNm);
    if (x < -4 || x >= SCOPE_W || y < 4 || y >= STATUS_Y - 4) continue;
    spr.fillRect(x - 2, y - 2, 5, 5, AIRFIELD_MARK); // solid: towns are hollow
    spr.drawString(f.name, x + 5, y - 3, 1);
  }

  spr.setTextColor(AIRSPACE_LINE, TFT_BLACK);
  for (const auto &w : WAYPOINTS) {
    radar::Vec2 p =
        radar::projectWith(lonScale, HOME_LAT, HOME_LON, w.lat, w.lon);
    int x = SCOPE_CX + (int)(p.x * pxPerNm);
    int y = SCOPE_CY - (int)(p.y * pxPerNm);
    if (x < -4 || x >= SCOPE_W || y < 4 || y >= STATUS_Y - 4) continue;
    spr.drawTriangle(x, y - 3, x - 3, y + 2, x + 3, y + 2, AIRSPACE_LINE);
    spr.drawString(w.name, x + 5, y - 3, 1);
  }
  for (const auto &t : TOWNS) {
    radar::Vec2 p =
        radar::projectWith(lonScale, HOME_LAT, HOME_LON, t.lat, t.lon);
    int x = SCOPE_CX + (int)(p.x * pxPerNm);
    int y = SCOPE_CY - (int)(p.y * pxPerNm);
    if (x < -4 || x >= SCOPE_W || y < 4 || y >= STATUS_Y - 4) continue;
    spr.drawRect(x - 2, y - 2, 5, 5, AIRSPACE_LINE); // hollow: airfields are solid
    spr.drawString(t.name, x + 5, y - 3, 1);
  }
}

static void drawRings(TFT_eSprite &spr, float rangeNmOuter, float pxPerNm) {
  for (int i = 1; i <= 2; i++) { // rings at 1/2 and full range
    int r = (int)(pxPerNm * rangeNmOuter * i / 2.0f);
    spr.drawCircle(SCOPE_CX, SCOPE_CY, r, TFT_DARKGREEN);
  }
  // Range is reported by the status strip, not labelled on the scope.
  // Home marker
  spr.drawLine(SCOPE_CX - 4, SCOPE_CY, SCOPE_CX + 4, SCOPE_CY, TFT_GREEN);
  spr.drawLine(SCOPE_CX, SCOPE_CY - 4, SCOPE_CX, SCOPE_CY + 4, TFT_GREEN);
}

// Warm low, cool high. Bands are in hundreds of feet to match the datablock
// text, so a blip's colour and its printed level never disagree.
static uint16_t altitudeColour(const radar::Aircraft &a) {
  if (a.onGround) return ALT_GROUND;
  int hundreds = (a.altFt + 50) / 100;
  if (hundreds < 20) return ALT_BAND_20;
  if (hundreds < 50) return ALT_BAND_50;
  if (hundreds < 100) return ALT_BAND_100;
  if (hundreds < 200) return ALT_BAND_200;
  if (hundreds < 300) return ALT_BAND_300;
  return ALT_BAND_TOP;
}

static void drawBlip(TFT_eSprite &spr, const radar::Aircraft &a, bool dim,
                     bool selected, bool alert, bool flashOn) {
  // Staleness outranks altitude: a dark grey blip means "this position is old"
  // and must not be mistaken for a low-level band.
  uint16_t col = dim ? TFT_DARKGREY : altitudeColour(a);
  if (alert && flashOn) col = ALERT_RED;
  // Hollow ring for a multilaterated position: the aircraft isn't reporting
  // where it is, we're triangulating it, so it carries a few hundred metres
  // of error that a solid blip would overstate. Altitude colour is kept.
  if (a.isMlat)
    spr.drawCircle(a.sx, a.sy, 3, col);
  else
    spr.fillCircle(a.sx, a.sy, 2, col);
  // Heading vector: 6px + 1px per 30kt, in track direction (north-up scope)
  float rad = a.trackDeg * (float)M_PI / 180.0f;
  int len = 6 + a.gsKt / 30;
  spr.drawLine(a.sx, a.sy, a.sx + (int)(sinf(rad) * len),
               a.sy - (int)(cosf(rad) * len), col);
  if (alert && flashOn) spr.drawCircle(a.sx, a.sy, 5, ALERT_RED);
  // Selection ring is white, not yellow: yellow now belongs to an altitude
  // band, and a selection marker must not read as a level.
  if (selected) spr.drawCircle(a.sx, a.sy, 6, SELECT_RING);
}

static void drawSquawkBanner(TFT_eSprite &spr, const radar::AircraftStore &s) {
  const radar::Aircraft *first = nullptr;
  int n = 0;
  for (int i = 0; i < s.count; i++) { // store is range-sorted: nearest first
    if (!radar::isAlertSquawk(s.list[i].squawk)) continue;
    if (!first) first = &s.list[i];
    n++;
  }
  if (!first) return;
  // Overlays the status corner. An active 7700 outranks the WiFi indicator.
  spr.fillRect(0, 0, SCOPE_W, BANNER_H, ALERT_RED);
  spr.setTextColor(ALERT_TEXT, ALERT_RED);
  char cs[10];
  radar::formatCallsign(cs, sizeof(cs), first->callsign, first->hex);
  char buf[44];
  if (n > 1)
    snprintf(buf, sizeof(buf), "! %s %s  (+%d more)", first->squawk, cs, n - 1);
  else
    snprintf(buf, sizeof(buf), "! %s %s", first->squawk, cs);
  spr.drawString(buf, 4, 3, 1);
}

// Effective age anchors seenS (frozen at parse time) to the wall clock, so a
// receiver that's stopped answering still visibly stales on screen.
static float effectiveAge(const radar::Aircraft &a,
                          const radar::AircraftStore &s) {
  return a.seenS +
         (s.lastFetchMs ? (millis() - s.lastFetchMs) / 1000.0f : 0.0f);
}

// Datablock placement tiers. Colour already shouts about alert squawks and
// rare airframes; without this the layout contradicted it, and a 7700 forty
// miles out could lose its block to a 738 on short final.
static int placementTier(const radar::Aircraft &a) {
  if (radar::isAlertSquawk(a.squawk)) return 0;
  // MLAT ranks with the rare airframes, and for the same reason: in airspace
  // this saturated, an aircraft not sending ADS-B at all is unusual by
  // definition. It arrives via a wholly separate mechanism from the type
  // lookup, so the two signals corroborate rather than duplicate.
  if (a.isMlat || !radar::isCommonType(a.type)) return 1;
  return 2;
}
static constexpr int N_TIERS = 3;

void drawScope(TFT_eSprite &spr, radar::AircraftStore &s,
               const radar::Metar &metar, const UiState &ui) {
  spr.fillSprite(TFT_BLACK);
  float rangeOuter = RANGES_NM[ui.rangeIdx];
  // Height-bound, not width-bound: the panel is 320 wide but only 240 tall,
  // so the ring is sized off SCOPE_CY. Traffic in the left/right margins is
  // beyond the nominal range and still drawn — that extra E/W coverage is
  // the point of going full-screen.
  float pxPerNm = scopePxPerNm(ui.rangeIdx);
  // One cosf per frame instead of one per projected point.
  float lonScale = radar::lonScaleNm(HOME_LAT);
  bool flashOn = (millis() / ALERT_FLASH_MS) % 2 == 0;

  datablocksBegin();
#ifdef DRAW_COASTLINE
  drawCoastline(spr, pxPerNm, lonScale); // bottom layer
#endif
  drawAirspace(spr, pxPerNm, lonScale);
  drawCentrelines(spr, pxPerNm, lonScale);
  drawRings(spr, rangeOuter, pxPerNm);
  drawFixedRefs(spr, pxPerNm, lonScale);
  // The status strip is off-limits to datablocks.
  datablockReserve(0, STATUS_Y, SCOPE_W, STATUS_H);
#ifdef OVERHEAD_PREDICTION
  // Reserved unconditionally, not only when a prediction exists: a corner
  // that a block occupies half the time would make the readout flicker in
  // and out from behind it.
  datablockReserve(0, 0, 104, 14);
#endif
#ifdef BOXRADAR_FRAME_TIME
  datablockReserve(SCOPE_W - 84, 0, 84, 14); // frame-time overlay, top right
#endif
  datablockReserve(0, SCOPE_H - 14, 46, 14);

  // Pass 1, far -> near so near traffic wins overlapping pixels.
  int onScreen = 0, mlatOnScreen = 0;
  for (int i = s.count - 1; i >= 0; i--) {
    radar::Aircraft &a = s.list[i];
    float ageS = effectiveAge(a, s);
    if (ageS > radar::SEEN_DROP_S) {
      a.sx = a.sy = -1000; // stale: not drawn, not tappable
      continue;
    }
    int sx = SCOPE_CX + (int)(a.pos.x * pxPerNm);
    int sy = SCOPE_CY - (int)(a.pos.y * pxPerNm);
    // Culled at the strip, not the panel edge: the strip is drawn last, so a
    // blip below it would be invisible yet still tappable.
    if (sx < 0 || sx >= SCOPE_W || sy < 0 || sy >= STATUS_Y) {
      a.sx = a.sy = -1000; // off-scope: not tappable
      continue;
    }
    a.sx = (int16_t)sx;
    a.sy = (int16_t)sy;
    onScreen++; // survived the stale and off-edge culls above
    if (a.isMlat) mlatOnScreen++;
    // Trails: oldest->newest as dimming dots behind the blip. Points are
    // already in the NM frame, so this is a scale, not a reprojection —
    // that used to be ~320 project() calls per frame.
    for (int t = 0; t < a.trailLen; t++) {
      int idx = (a.trailHead - a.trailLen + t + 2 * radar::TRAIL_LEN) %
                radar::TRAIL_LEN;
      const radar::Vec2 &tp = a.trail[idx];
      int tx = SCOPE_CX + (int)(tp.x * pxPerNm);
      int ty = SCOPE_CY - (int)(tp.y * pxPerNm);
      if (tx < 0 || tx >= SCOPE_W || ty < 0 || ty >= SCOPE_H) continue;
      // 3 brightness steps oldest->newest
      uint16_t col = t < a.trailLen / 3       ? 0x4208   // very dark grey (0x18E3 quantized to black on 8-bit RGB332)
                     : t < (2 * a.trailLen) / 3 ? TFT_DARKGREY
                                                : 0x8410; // mid grey
      spr.drawPixel(tx, ty, col);
      if (t >= (2 * a.trailLen) / 3) spr.drawPixel(tx + 1, ty, col);
    }
    drawBlip(spr, a, ageS > radar::SEEN_DIM_S,
             ui.selectedHex != 0 && a.hex == ui.selectedHex,
             radar::isAlertSquawk(a.squawk), flashOn);
    datablockReserve(a.sx - 3, a.sy - 3, 7, 7); // blocks never cover a blip
  }

  // Pass 2 places blocks; whoever goes first claims the cells, so this order
  // IS the priority. Selected, then alert squawks, then rare airframes, then
  // nearest-first. Range order carries through inside each tier for free —
  // s.list is already sorted ascending, so a forward sweep is nearest-first.
  // Runs separately from pass 1 because that one has to go far -> near.
  bool twoLine = rangeOuter <= TWO_LINE_MAX_NM;
  const radar::Aircraft *sel =
      ui.selectedHex ? s.findByHex(ui.selectedHex) : nullptr;
  if (sel && sel->sx > -1000) // an explicit tap outranks every heuristic
    drawDatablock(spr, *sel, effectiveAge(*sel, s) > radar::SEEN_DIM_S,
                  twoLine);
  for (int tier = 0; tier < N_TIERS; tier++) {
    for (int i = 0; i < s.count; i++) {
      const radar::Aircraft &a = s.list[i];
      if (a.sx <= -1000 || &a == sel) continue;
      if (placementTier(a) != tier) continue;
      drawDatablock(spr, a, effectiveAge(a, s) > radar::SEEN_DIM_S, twoLine);
    }
  }

#ifdef OVERHEAD_PREDICTION
  // Experimental; delete this block and the include above to remove.
  // Drawn before the banner so a 7700 always wins the top of the screen.
  drawOverheadReadout(
      spr, s, s.lastFetchMs ? (millis() - s.lastFetchMs) / 1000.0f : 0.0f);
#endif
  drawSquawkBanner(spr, s);
  drawStatusCorner(spr, s, metar, onScreen, mlatOnScreen, ui.rangeIdx);
}

void drawDetailPanel(TFT_eSprite &spr, const radar::AircraftStore &s,
                     const UiState &ui) {
  if (!ui.detailOpen || ui.selectedHex == 0) return;
  const radar::Aircraft *a = s.findByHex(ui.selectedHex);
  if (!a) return;
  constexpr int W = 150, H = 92, X = 4, Y = SCOPE_H - H - 16;
  spr.fillRect(X, Y, W, H, TFT_BLACK);
  spr.drawRect(X, Y, W, H, TFT_YELLOW);
  spr.setTextColor(TFT_YELLOW, TFT_BLACK);
  char cs[10];
  radar::formatCallsign(cs, sizeof(cs), a->callsign, a->hex);
  char l1[24];
  snprintf(l1, sizeof(l1), "%s  %06lx", cs, (unsigned long)a->hex);
  spr.drawString(l1, X + 4, Y + 4, 2);
  spr.setTextColor(TFT_WHITE, TFT_BLACK);
  char alt[8], line[26];
  radar::formatAltitude(alt, sizeof(alt), a->altFt, a->onGround);
  snprintf(line, sizeof(line), "%-4s  %s  %ukt", a->type[0] ? a->type : "-",
           alt, a->gsKt);
  spr.drawString(line, X + 4, Y + 26, 1);
  snprintf(line, sizeof(line), "trk %u  vs %+d%s", a->trackDeg, a->vertRateFpm,
           a->isMlat ? "  MLAT" : "");
  spr.drawString(line, X + 4, Y + 40, 1);
  snprintf(line, sizeof(line), "%.1fnm brg %.0f", (double)a->range,
           (double)radar::bearingDeg(a->pos));
  spr.drawString(line, X + 4, Y + 54, 1);
  snprintf(line, sizeof(line), "rssi %.1f  sqk %s", (double)a->rssi,
           a->squawk[0] ? a->squawk : "----");
  spr.drawString(line, X + 4, Y + 68, 1);
}
