#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "metar.h"
#include "layout.h"
#include "viewport.h"

// The viewport is passed in rather than derived here because touch has to
// hit-test against the same one the frame was drawn with — see ui_task.cpp.
void drawScope(TFT_eSprite &spr, radar::AircraftStore &s,
               const radar::Metar &metar, const UiState &ui,
               const Viewport &vp);
void drawDetailPanel(TFT_eSprite &spr, const radar::AircraftStore &s, const UiState &ui);
