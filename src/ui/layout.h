#pragma once
#include <stdint.h>

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

constexpr float RANGES_NM[] = {5, 10, 25, 50};
constexpr int N_RANGES = 4;

// Two-line datablocks are only legible while the scope is sparse. Beyond this
// range they degrade to callsign only — see datablock.cpp.
constexpr float TWO_LINE_MAX_NM = 10.0f;

// Scale is height-bound: SCOPE_CX is larger but the ring must fit vertically.
inline float scopePxPerNm(int rangeIdx) {
  return (float)(SCOPE_CY - SCOPE_MARGIN) / RANGES_NM[rangeIdx];
}

static_assert(2 * SCOPE_CY - SCOPE_MARGIN < STATUS_Y,
              "ring would overlap the status strip — lower SCOPE_CY");

struct UiState {
  int rangeIdx = 1;          // default 10 NM
  uint32_t selectedHex = 0;  // 0 = none
  bool detailOpen = false;
};
