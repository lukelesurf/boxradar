#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

// Draws "OVHD <callsign> <n>s" in the top-left corner, which the full-width
// status strip freed. Nothing is drawn when no aircraft qualifies, so an
// empty corner means "nothing predictable is coming", not a failure.
void drawOverheadReadout(TFT_eSprite &spr, const radar::AircraftStore &s,
                         float extraAgeS);
