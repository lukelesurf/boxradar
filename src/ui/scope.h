#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

void drawScope(TFT_eSprite &spr, radar::AircraftStore &s, const UiState &ui);
