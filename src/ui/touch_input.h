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

// How long the current continuous press has lasted, or 0 if nothing is down.
// Never returns 0 while a finger IS down, because 0 is what HoldGesture reads
// as "released". Valid only after touchInputPoll() or touchInputTapped() has
// run this frame — those are what refresh the underlying state.
//
// Duration is the one interaction axis this panel has left. Position is fully
// spoken for by the table above, and XPT2046 is 4-wire resistive, so there is
// no second finger to detect and `z` is contact force rather than a count.
uint32_t touchInputHeldMs();

// Press-edge only, ignoring position — used while the panel is dark, where a
// tap must wake the display WITHOUT also selecting whatever happened to be
// under the finger.
bool touchInputTapped();
