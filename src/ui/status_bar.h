#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "metar.h"
#include "layout.h"

// Full-width status strip along the bottom of the scope:
//
//   [tick] AC 15 (5) - 10nm - EGSS 22 - 160/05 - BKN012
//
// Named ...Corner historically; kept for callers, though it is a strip now.
//
// Counts are passed in rather than derived from the store: "on screen" is a
// rendering outcome (in range, not stale, not off the edge) that only
// drawScope's first pass knows. Taking them as arguments keeps that
// dependency explicit instead of relying on sx/sy having been filled in.
void drawStatusCorner(TFT_eSprite &spr, const radar::AircraftStore &s,
                      const radar::Metar &metar, int onScreen,
                      int mlatOnScreen, float rangeNm);

// Touch target for the zoom toggle, which is the range readout itself.
//
// Reported back rather than hardcoded because the readout's x position moves
// with whatever the traffic segment printed before it ("AC 15 (5)" against
// "NO UPDATE 123s"), so a fixed rect would drift off it. The zone is much
// taller than the 10px strip: a finger on a resistive panel cannot aim at a
// 10px band, and the space above the strip is cheap.
// Plain aggregate, no default member initialisers: the ESP32 core builds at
// gnu++11, where an NSDMI would make this a non-aggregate and cost it brace
// initialisation. The one instance has static storage and zero-inits anyway.
struct HitRect {
  int x, y, w, h;
  bool contains(int px, int py) const {
    return px >= x && px < x + w && py >= y && py < y + h;
  }
};
HitRect statusRangeHitZone();
