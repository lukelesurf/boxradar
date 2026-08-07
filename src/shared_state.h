#pragma once
#include "aircraft.h"
#include "metar.h"

extern volatile bool g_otaActive;
extern volatile uint8_t g_otaProgress; // 0-100

// Trail dot spacing in NM, published by the UI task (only it knows px/nm)
// and read by the net task, which is where trail points are appended. A
// plain aligned float rather than mutex-guarded: a torn read is impossible
// on this architecture, and a one-poll-stale value only affects where a
// single dot lands.
extern volatile float g_trailSpacingNm;

void sharedStateInit();
void publishStore(const radar::AircraftStore &s);
void snapshotStore(radar::AircraftStore &out);

// METAR shares the same mutex as the aircraft store rather than taking its
// own. Both are written by the net task and read by the UI task, contention
// is negligible at 10fps against 2s/60s polls, and one lock removes any
// chance of the two orderings deadlocking against each other.
void publishMetar(const radar::Metar &m);
void snapshotMetar(radar::Metar &out);
