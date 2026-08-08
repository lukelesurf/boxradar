#pragma once
#include "aircraft.h"
#include "layout.h"
#include "viewport.h"

void touchInputInit();
// Applies one tap (if any) to ui. One gesture per state, so nothing is ever
// ambiguous:
//
//                 tap a blip            tap background
//   OVERVIEW      (nothing)             zoom to detail, centred there
//   DETAIL        select + panel        back to overview
//
// plus the range readout in the status strip, which toggles the detail scale.
//
// Selection is disabled in overview on purpose: at 50nm with a 20px hit
// radius, "select or zoom?" would be ambiguous exactly in the dense areas you
// most want to zoom into.
//
// Takes the viewport the frame was DRAWN with — the tap has to be inverted
// through the same transform the user was looking at.
// Returns true when a press edge was consumed this frame.
bool touchInputPoll(UiState &ui, const radar::AircraftStore &s,
                    const Viewport &vp);

// Press-edge only, ignoring position — used while the panel is dark, where a
// tap must wake the display WITHOUT also selecting whatever happened to be
// under the finger.
bool touchInputTapped();
