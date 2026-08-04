#pragma once
#include <stdint.h>

constexpr int SCOPE_W = 240, SCOPE_H = 240, SCOPE_CX = 120, SCOPE_CY = 120;
constexpr int LIST_X = 240, LIST_W = 80;
constexpr int LIST_ROW_H = 20, LIST_ROWS = 9;   // rows area: y 0..179
constexpr int STATUS_Y = 196;                    // status strip: y 196..239
constexpr float RANGES_NM[] = {10, 25, 50, 100};
constexpr int N_RANGES = 4;
constexpr int32_t TRANSITION_ALT_FT = 6000;      // UK-ish; FL above, feet below
struct UiState {
  int rangeIdx = 1;          // default 25 NM
  uint32_t selectedHex = 0;  // 0 = none
  bool detailOpen = false;
};
