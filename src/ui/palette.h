#pragma once
#include <stdint.h>

// The scope sprite is 8-bit (see createScopeSprite in ui_task.cpp), so
// TFT_eSPI quantizes every 16-bit 565 colour down to RGB332 on the way in:
// 3 bits of red, 3 of green, and only 2 of BLUE. Hand-picked 565 constants
// routinely collapse into each other under that.
//
// So don't write 565 literals — build them from the bits that actually
// survive. rgb332() takes the post-quantization values directly, which makes
// two constants distinct on-screen if and only if their arguments differ.
constexpr uint16_t rgb332(uint8_t r3, uint8_t g3, uint8_t b2) {
  return (uint16_t)((uint16_t)(r3 & 7) << 13 | (uint16_t)(g3 & 7) << 8 |
                    (uint16_t)(b2 & 3) << 3);
}

// Altitude bands, low to high. Warm = low, cool = high, which is the
// convention tar1090 uses and reads correctly at a glance without a legend.
constexpr uint16_t ALT_GROUND  = rgb332(5, 5, 2); // grey
constexpr uint16_t ALT_BAND_20 = rgb332(7, 0, 0); // red      <  2000ft
constexpr uint16_t ALT_BAND_50 = rgb332(7, 3, 0); // orange   <  5000ft
constexpr uint16_t ALT_BAND_100 = rgb332(7, 6, 0); // yellow  < 10000ft
constexpr uint16_t ALT_BAND_200 = rgb332(1, 7, 1); // green   < 20000ft
constexpr uint16_t ALT_BAND_300 = rgb332(0, 6, 3); // cyan    < 30000ft
constexpr uint16_t ALT_BAND_TOP = rgb332(3, 2, 3); // violet  >=30000ft

// Datablock text. The type field goes amber when the airframe isn't one of
// the everyday short-haul types — see radar::isCommonType.
constexpr uint16_t BLOCK_TEXT      = rgb332(5, 5, 2);
constexpr uint16_t BLOCK_TEXT_DIM  = rgb332(2, 2, 1);
constexpr uint16_t TYPE_INTERESTING = rgb332(7, 5, 0);
constexpr uint16_t LEADER_LINE     = rgb332(2, 2, 1);

constexpr uint16_t SELECT_RING = rgb332(7, 7, 3); // white
constexpr uint16_t ALERT_RED   = rgb332(7, 0, 0);
constexpr uint16_t ALERT_TEXT  = rgb332(7, 7, 3);
