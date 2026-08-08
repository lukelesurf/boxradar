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

// Airfield reference points, drawn as small SOLID squares with an ICAO
// label. Usually the ARP, which is also the centre the CTR arcs are struck
// from. Solid distinguishes them from the hollow squares used for towns.
//
// Markers and centrelines are deliberately separate lists: a marker is
// cheap orientation, whereas an extended centreline is a strong visual
// claim about where traffic is going. Mark plenty; draw centrelines only
// for the fields whose approach paths you actually care about.
struct AirfieldRef { float lat, lon; const char *name; };

// Runway thresholds, for extended centrelines. Give BOTH ends: the axis is
// taken from the two points rather than a published heading, so the drawn
// line is guaranteed to pass through both runway ends and line up with the
// airfield marker. Published headings sometimes disagree with their own
// threshold coordinates by a degree or more.
//
// NOTE these are TRUE positions. Do not try to derive them from the runway
// designator, which is MAGNETIC and rounded to 10 degrees.
struct RunwayAxis { float lat0, lon0, lat1, lon1; };

// Two kinds of fixed reference, distinguished by marker shape so they are
// tellable apart at 5px without reading the label:
//
//   WAYPOINTS — navigation fixes: hollow TRIANGLE (chart convention)
//   TOWNS     — ground references: hollow SQUARE
//
// Both are drawn under the traffic in the airspace grey, so an aircraft
// label always wins where they collide.
//
// Sources. Navaids (3-letter VOR/NDB idents):
//   https://davidmegginson.github.io/ourairports-data/navaids.csv
// Enroute fixes (5-letter, e.g. ABBOT) are NOT in that file — they come from
// the NATS eAIP ENR 4.4 "significant points" table, which publishes them as
// DDMMSS.ssN/DDDMMSS.ssE. Towns: OSM Nominatim, taking the `town` result
// rather than the first hit, which is often a county centroid.
//
// Short labels are better — every character is 6px and competes with
// datablocks at close range — but real 5-letter fix identifiers are kept
// intact rather than mangled into four, since a wrong label costs more than
// six pixels. Neither array may be empty; comment the whole block out
// instead, along with its draw call in scope.cpp.
struct Waypoint { float lat, lon; const char *name; };
struct TownRef { float lat, lon; const char *name; };

// ---------------------------------------------------------------- profile
// Current: north Essex, centred between Stansted and Luton.

static constexpr AirfieldRef AIRFIELDS[] = {
    // Local pair — CTR arc centres, matching the airspace geometry.
    {51.88500f, 0.23500f, "EGSS"},   // Stansted
    {51.87472f, -0.36833f, "EGGW"},  // Luton
    // Civil, further out (ARPs from OurAirports airports.csv).
    {52.20500f, 0.17500f, "EGSC"},   // Cambridge      18.7nm
    {51.50530f, 0.05528f, "EGLC"},   // London City    24.0nm, almost due S
    {51.47075f, -0.45991f, "EGLL"},  // Heathrow       31.8nm
    {51.57056f, 0.69363f, "EGMC"},   // Southend       31.8nm
    {51.14874f, -0.18574f, "EGKK"},  // Gatwick        46.1nm
    // Military — the origin of most of the unusual traffic the amber
    // rare-type highlight exists to catch.
    {52.36190f, 0.48641f, "EGUN"},   // Mildenhall     32.1nm
    {52.40954f, 0.56116f, "EGUL"},   // Lakenheath     36.0nm
    {52.12745f, 0.95619f, "EGUW"},   // Wattisham      36.7nm
};

static constexpr RunwayAxis RUNWAYS[] = {
    {51.875081f, 0.219933f, 51.895166f, 0.250050f},   // EGSS 04/22
    {51.872002f, -0.383550f, 51.877201f, -0.353333f}, // EGGW 07/25
};

// The fixes that actually govern traffic here: the two shared EGSS/EGGW
// holds, the main Stansted SID waypoint, and one VOR for reference.
static constexpr Waypoint WAYPOINTS[] = {
    {51.98970f, 0.06194f, "BKY"},    // Barkway VOR — Stansted SIDs
    {52.01394f, -0.05264f, "LOREL"}, // hold, EGSS/EGGW STARs
    {52.01611f, 0.59958f, "ABBOT"},  // hold, EGSS/EGGW STARs
    {51.74970f, -0.10667f, "BPK"},   // Brookmans Park VOR — reference
};

// Ground references. Nearby ones orient you at 10-25nm; the further ones
// only earn their place at 50nm, where the scope is otherwise mostly empty.
static constexpr TownRef TOWNS[] = {
    {51.90167f, -0.20272f, "STVG"}, // Stevenage
    {51.79574f, -0.07852f, "HRFD"}, // Hertford
    {51.87803f, 0.55365f, "BRAI"},  // Braintree
    {52.08820f, -0.25890f, "BIGG"}, // Biggleswade
    {52.13638f, -0.46750f, "BEDF"}, // Bedford
    {51.73453f, 0.47305f, "CHLM"},  // Chelmsford
    {51.88969f, 0.89947f, "COLC"},  // Colchester
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
