#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

void drawSidePanel(TFT_eSPI &tft, const radar::AircraftStore &s, const UiState &ui);
// "FL350" at/above transition, "4500" below, "GND" on ground
void formatAltitude(char *out, size_t cap, int32_t altFt, bool onGround);
