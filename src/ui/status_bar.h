#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

// Status text in the top-left corner. Named ...Corner to stay distinct from
// main.cpp's boot-time drawStatus(), which writes to the bare TFT.
//
// Counts are passed in rather than derived from the store: "on screen" is a
// rendering outcome (in range, not stale, not off the edge) that only
// drawScope's first pass knows. Taking them as arguments keeps that
// dependency explicit instead of relying on sx/sy having been filled in.
void drawStatusCorner(TFT_eSprite &spr, const radar::AircraftStore &s,
                      int onScreen, int mlatOnScreen);
