#pragma once
#include "aircraft.h"
#include "layout.h"

void touchInputInit();
// Applies one tap (if any) to ui: select blip/list row, dismiss detail,
// or cycle range. Needs the current store snapshot for hit-testing.
// Returns true when a press edge was consumed this frame.
bool touchInputPoll(UiState &ui, const radar::AircraftStore &s);

// Press-edge only, ignoring position — used while the panel is dark, where a
// tap must wake the display WITHOUT also selecting whatever happened to be
// under the finger.
bool touchInputTapped();
