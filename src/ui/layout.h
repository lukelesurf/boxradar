#pragma once
#include <stdint.h>

// Full-screen scope: the whole 320x240 panel is the radar. Home sits at the
// true centre and the usable radius is HEIGHT-bound, so widening the scope
// from 240 to 320 does not zoom in — it buys horizontal room. Two things use
// that room: traffic beyond the outer ring to the E/W stays visible, and
// datablocks have somewhere to sit without covering the picture.
constexpr int SCOPE_W = 320, SCOPE_H = 240, SCOPE_CX = 160, SCOPE_CY = 120;
constexpr int SCOPE_MARGIN = 6; // outer ring inset from the top/bottom edge

// The outer ring is 228px across on a 320px panel, leaving the left and right
// corners permanently outside it. Status text lives in that dead space rather
// than in a bar, which would have clipped a chord off the bottom of the ring.
constexpr int STATUS_X = 3, STATUS_Y = 3;

constexpr float RANGES_NM[] = {5, 10, 25, 50};
constexpr int N_RANGES = 4;

// Two-line datablocks are only legible while the scope is sparse. Beyond this
// range they degrade to callsign only — see datablock.cpp.
constexpr float TWO_LINE_MAX_NM = 10.0f;

// Scale is height-bound: SCOPE_CX is larger but the ring must fit vertically.
inline float scopePxPerNm(int rangeIdx) {
  return (float)(SCOPE_CY - SCOPE_MARGIN) / RANGES_NM[rangeIdx];
}

struct UiState {
  int rangeIdx = 1;          // default 10 NM
  uint32_t selectedHex = 0;  // 0 = none
  bool detailOpen = false;
};
