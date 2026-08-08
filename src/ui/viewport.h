#pragma once
#include <math.h>
#include "aircraft.h"
#include "layout.h"
#include "projection.h"

// The one place the NM frame becomes pixels.
//
// Before this existed, every draw site in scope.cpp open-coded
//   SCOPE_CX + (int)(p.x * pxPerNm)
// which silently baked in "the view is centred on home". Routing all of them
// through a Viewport is what makes a view centred anywhere else possible at
// all; the states in UiState are then just a choice of centre and scale.
struct Viewport {
  radar::Vec2 centre; // view centre, NM east/north of home
  float rangeNm;      // outer ring range — this is what sets the scale
  float pxPerNm;

  // Float forms for anything that steps along a line in sub-pixel increments
  // (the dashed centrelines); sx/sy truncate exactly as the old inline
  // expressions did, so blip positions are bit-identical to before.
  float fx(float xNm) const {
    return (float)SCOPE_CX + (xNm - centre.x) * pxPerNm;
  }
  float fy(float yNm) const {
    return (float)SCOPE_CY - (yNm - centre.y) * pxPerNm;
  }
  int sx(float xNm) const {
    return SCOPE_CX + (int)((xNm - centre.x) * pxPerNm);
  }
  int sy(float yNm) const {
    return SCOPE_CY - (int)((yNm - centre.y) * pxPerNm);
  }

  // Inverse: a tap position back into the NM frame. This is what turns a tap
  // on the overview into the centre of the detail view.
  radar::Vec2 toNm(int px, int py) const {
    return {centre.x + (float)(px - SCOPE_CX) / pxPerNm,
            centre.y + (float)(SCOPE_CY - py) / pxPerNm};
  }

  // Range rings mean "distance from you", so they are only honest when the
  // view is on home. Tested geometrically rather than off the view state: a
  // tap that lands on home genuinely is a home-centred view and should keep
  // its rings. Sub-pixel tolerance, since anything closer than a pixel draws
  // in the same place anyway.
  bool homeCentred() const {
    return fabsf(centre.x) * pxPerNm < 1.0f &&
           fabsf(centre.y) * pxPerNm < 1.0f;
  }
};

// How close a tap has to land on the home marker to be read as "home" rather
// than "4nm north-east of home". 10px at the overview scale is ~4.5nm, which
// sounds coarse until you notice the alternative: without a snap, only a tap
// on the exact centre pixel produces a genuinely home-centred view, because
// the sub-pixel tolerance in homeCentred() is measured at the DETAIL scale
// while the tap was aimed at the OVERVIEW scale — 5x coarser. One pixel of
// aim becomes five pixels of offset, and the range rings never come back.
constexpr int HOME_SNAP_PX = 10;

// Where a tap on the overview should put the detail centre. Split out from
// touch handling and kept next to the transform it depends on, because the
// interesting part is the scale conversion above, not the gesture.
inline radar::Vec2 detailCentreForTap(const Viewport &vp, int px, int py) {
  int dx = px - vp.sx(0.0f), dy = py - vp.sy(0.0f);
  if (dx * dx + dy * dy <= HOME_SNAP_PX * HOME_SNAP_PX)
    return {0.0f, 0.0f}; // exactly home: rings return, deterministically
  return vp.toNm(px, py);
}

// Built fresh every frame rather than stored, so a future follow-a-selected-
// aircraft state can make the centre a function of the current store without
// any draw site changing. That is the whole reason the store is a parameter
// here while nothing reads it yet.
inline Viewport viewportFor(const UiState &ui, const radar::AircraftStore &s) {
  (void)s;
  Viewport vp;
  if (ui.view == ViewState::OVERVIEW) {
    vp.centre = {0.0f, 0.0f};
    vp.rangeNm = OVERVIEW_NM;
  } else {
    vp.centre = ui.detailCentre;
    vp.rangeNm = DETAIL_RANGES_NM[ui.detailRangeIdx];
  }
  vp.pxPerNm = scopePxPerNm(vp.rangeNm);
  return vp;
}
