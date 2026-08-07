#pragma once
#include <TFT_eSPI.h>
#include "aircraft.h"
#include "layout.h"

// Two-line ATC-style datablocks with automatic anti-overlap placement.
//
//   line 1:  callsign            (or last 4 of hex when the feed has none)
//   line 2:  350^ A320           level in hundreds of feet, climb/descent
//                                arrow, ICAO type
//
// Call datablocksBegin() once per frame, reserve the blips, then place blocks
// nearest-first so close traffic wins the contested screen space.
void datablocksBegin();

// Mark a rectangle as taken so no block can be placed over it.
void datablockReserve(int x, int y, int w, int h);

// Places and draws one block, or degrades (two lines -> one line -> nothing)
// when the surrounding screen is full. Returns false if nothing was drawn.
bool drawDatablock(TFT_eSprite &spr, const radar::Aircraft &a, bool dim,
                   bool twoLine);
