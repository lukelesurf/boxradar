#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "format.h"
#include "layout.h"

void drawSidePanel(TFT_eSPI &tft, const radar::AircraftStore &s, const UiState &ui);
