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
                      int mlatOnScreen, int rangeIdx);
