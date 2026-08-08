#pragma once
#include <stdint.h>
#include "projection.h"

// Full-screen scope: the whole 320x240 panel is the radar. Home sits at the
// true centre and the usable radius is HEIGHT-bound, so widening the scope
// from 240 to 320 does not zoom in — it buys horizontal room. Two things use
// that room: traffic beyond the outer ring to the E/W stays visible, and
// datablocks have somewhere to sit without covering the picture.
constexpr int SCOPE_W = 320, SCOPE_H = 240, SCOPE_CX = 160;
constexpr int SCOPE_MARGIN = 6; // outer ring inset from the top edge

// Single full-width status strip along the bottom. It replaced a stacked
// corner block: one line reads left-to-right in a glance, and consolidating
// WiFi, traffic count, range and weather into it frees both top corners.
constexpr int STATUS_H = 10;
constexpr int STATUS_Y = SCOPE_H - STATUS_H; // 230
constexpr int STATUS_X = 3;

// Centre sits above true centre so the ring clears the strip. Derived rather
// than hardcoded: ring top is SCOPE_MARGIN, so radius = SCOPE_CY - MARGIN,
// and the ring bottom (2*SCOPE_CY - MARGIN) must stay above STATUS_Y.
constexpr int SCOPE_CY = 116; // ring spans y 6..226, strip starts at 230

// Two view states rather than a cycle of ranges centred on home: an OVERVIEW
// you choose from and a DETAIL level you look at. See docs/viewport-design.md.
//
// 50nm shows every airfield and approach that matters here; it is unreadable
// as a working view, which is precisely why it is only ever the chooser.
constexpr float OVERVIEW_NM = 50.0f;

// Detail scales, in the order the status-strip zoom toggle steps through them.
// Index 0 is what a tap out of the overview lands on.
constexpr float DETAIL_RANGES_NM[] = {10.0f, 5.0f};
constexpr int N_DETAIL_RANGES = 2;

// Two-line datablocks are only legible while the scope is sparse. Beyond this
// range they degrade to callsign only — see datablock.cpp. Every detail range
// is inside it and the overview is outside it, so in practice this now reads
// as "detail gets two lines, overview does not".
constexpr float TWO_LINE_MAX_NM = 10.0f;

// Scale is height-bound: SCOPE_CX is larger but the ring must fit vertically.
inline float scopePxPerNm(float rangeNm) {
  return (float)(SCOPE_CY - SCOPE_MARGIN) / rangeNm;
}

static_assert(2 * SCOPE_CY - SCOPE_MARGIN < STATUS_Y,
              "ring would overlap the status strip — lower SCOPE_CY");

// Target gap between trail dots, in pixels. The world-space spacing is
// derived from this and the current scale, so the dotted line reads the same
// at every range — a fixed NM spacing would still bunch up when zoomed out.
constexpr float TRAIL_PX_SPACING = 5.0f;

inline float trailSpacingNm(float rangeNm) {
  return TRAIL_PX_SPACING / scopePxPerNm(rangeNm);
}

enum class ViewState : uint8_t { OVERVIEW, DETAIL };

struct UiState {
  // Boots into detail on home: the resting state of a device on a shelf is
  // the working 10nm picture, and the overview is somewhere you go.
  ViewState view = ViewState::DETAIL;
  // View centre in detail, as an NM offset from home. Set from wherever the
  // overview was tapped; {0,0} is home itself.
  radar::Vec2 detailCentre = {0.0f, 0.0f};
  int detailRangeIdx = 0;    // index into DETAIL_RANGES_NM
  uint32_t selectedHex = 0;  // 0 = none; always 0 in overview
  bool detailOpen = false;
};
