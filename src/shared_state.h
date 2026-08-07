#pragma once
#include "aircraft.h"
#include "metar.h"

extern volatile bool g_otaActive;
extern volatile uint8_t g_otaProgress; // 0-100

void sharedStateInit();
void publishStore(const radar::AircraftStore &s);
void snapshotStore(radar::AircraftStore &out);

// METAR shares the same mutex as the aircraft store rather than taking its
// own. Both are written by the net task and read by the UI task, contention
// is negligible at 10fps against 2s/60s polls, and one lock removes any
// chance of the two orderings deadlocking against each other.
void publishMetar(const radar::Metar &m);
void snapshotMetar(radar::Metar &out);
