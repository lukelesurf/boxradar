#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

// Status text in the top-left corner. Named ...Corner to stay distinct from
// main.cpp's boot-time drawStatus(), which writes to the bare TFT.
void drawStatusCorner(TFT_eSprite &spr, const radar::AircraftStore &s);
