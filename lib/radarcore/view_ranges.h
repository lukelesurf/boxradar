#pragma once

namespace radar {

// The scope's ranges, in nautical miles.
//
// These were compiled constants in src/ui/layout.h, which made the single most
// site-specific thing about the panel a reflash away: 50/10/5 is a London-area
// choice. A box at a quiet GA field wants a 20nm overview and a 3nm detail; one
// watching an oceanic gateway wants 150.
//
// They live here rather than in layout.h because the value has to be settable
// at runtime and layout.h cannot reach siteConfig() — src/site_config.cpp is
// Arduino/NVS code that the native tests do not link, while everything in
// lib/radarcore is compiled into them. Same reason classifySetCommonTypes()
// exists: the firmware pushes NVS in at boot, and the tests push values in
// directly.
//
// Unlike the type list, this is COPIED rather than borrowed. It is four floats,
// so there is nothing to gain from aliasing the caller's storage and one
// lifetime question fewer to answer.

// Exactly two detail levels. The count is fixed rather than configurable
// because DETAIL_RANGES_NM sizes an array and the zoom toggle steps modulo it;
// making the count runtime would buy a rarely-wanted third level at the price
// of a bounds check on every frame. Two levels and a toggle is also the whole
// interaction — a third would want a different gesture.
constexpr int VIEW_DETAIL_RANGES = 2;

struct ViewRanges {
  // The chooser. Deliberately unreadable as a working view: it exists to show
  // every airfield and approach at once so you can tap the bit you want.
  float overviewNm;

  // Detail scales, in the order the status-strip zoom toggle steps through
  // them. Index 0 is what a tap out of the overview lands on, so it is the
  // resting picture; index 1 is the closer look. Nothing enforces
  // detailNm[0] > detailNm[1] — reversing them just makes the toggle step out
  // before it steps in, which is odd rather than broken.
  float detailNm[VIEW_DETAIL_RANGES];

  // Beyond this range datablocks degrade to callsign only, because two lines
  // are only legible while the scope is sparse. 0 means never two-line.
  float twoLineMaxNm;
};

// The live ranges. Returns the compiled defaults until viewRangesSet() is
// called, which is what keeps the native tests and a board with empty NVS
// behaving identically.
const ViewRanges &viewRanges();

// The compiled defaults, so the configuration UI can say what it would fall
// back to and the tests have something to compare against.
const ViewRanges &viewRangesDefaults();

// Replace the live ranges. A non-positive overview or detail range is IGNORED
// and the previous value kept: scopePxPerNm() divides by the range, so a zero
// that reached here would be a division by zero on every frame rather than a
// bad-looking picture. The bounds in DEVICE_FIELDS should have refused it long
// before, which is exactly why this is a backstop and not the validation.
void viewRangesSet(const ViewRanges &ranges);

} // namespace radar
