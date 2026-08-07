#pragma once

// WHICH AIRFIELDS TO DRAW — edit this file to move the scope to a new area.
// See the "Relocating" section of the README for the full checklist; this is
// one of four places that carry location data.
//
// This file is COMMITTED, unlike config.h. Everything here is published AIP
// data about public infrastructure. Your own position (HOME_LAT/HOME_LON)
// deliberately lives in the gitignored config.h instead, so a repo pushed to
// a public mirror never carries your home coordinates.
//
// Threshold coordinates and true headings can be pulled from OurAirports:
//   https://davidmegginson.github.io/ourairports-data/runways.csv
//   grep '"EGxx"' runways.csv
// It has le_/he_ latitude and longitude per runway end, which is what the
// centrelines want.

// Airfield reference points, drawn as small solid squares. Usually the ARP,
// which is also the centre the CTR arcs are struck from.
struct AirfieldRef { float lat, lon; };

// Runway thresholds, for extended centrelines. Give BOTH ends: the axis is
// taken from the two points rather than a published heading, so the drawn
// line is guaranteed to pass through both runway ends and line up with the
// airfield marker. Published headings sometimes disagree with their own
// threshold coordinates by a degree or more.
//
// NOTE these are TRUE positions. Do not try to derive them from the runway
// designator, which is MAGNETIC and rounded to 10 degrees.
struct RunwayAxis { float lat0, lon0, lat1, lon1; };

// ---------------------------------------------------------------- profile
// Current: north Essex, centred between Stansted and Luton.

static constexpr AirfieldRef AIRFIELDS[] = {
    {51.88500f, 0.23500f},   // EGSS Stansted
    {51.87472f, -0.36833f},  // EGGW Luton
};

static constexpr RunwayAxis RUNWAYS[] = {
    {51.875081f, 0.219933f, 51.895166f, 0.250050f},   // EGSS 04/22
    {51.872002f, -0.383550f, 51.877201f, -0.353333f}, // EGGW 07/25
};

// Example alternative profile — Southend-on-Sea, ~25nm south-east. Swap the two
// arrays above for these, and see the README for the matching changes to
// config.h, build_airspace.py and metar_feed.py.
//
// static constexpr AirfieldRef AIRFIELDS[] = {
//     {51.57140f, 0.69560f},   // EGMC Southend
//     {52.12750f, 0.96110f},   // EGUW Wattisham
// };
// static constexpr RunwayAxis RUNWAYS[] = {
//     {51.567200f, 0.686268f, 51.575600f, 0.704996f}, // EGMC 05/23
//     {52.120602f, 0.943800f, 52.134300f, 0.968531f}, // EGUW 05/23
// };
