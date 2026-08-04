#pragma once
#include "aircraft.h"

extern volatile bool g_otaActive;

void sharedStateInit();
void publishStore(const radar::AircraftStore &s);
void snapshotStore(radar::AircraftStore &out);
