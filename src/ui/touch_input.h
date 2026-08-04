#pragma once
#include "aircraft.h"
#include "layout.h"

void touchInputInit();
// Applies one tap (if any) to ui: select blip/list row, dismiss detail,
// or cycle range. Needs the current store snapshot for hit-testing.
void touchInputPoll(UiState &ui, const radar::AircraftStore &s);
