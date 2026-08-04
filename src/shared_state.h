#pragma once
#include "aircraft.h"

extern volatile bool g_otaActive;
extern volatile uint8_t g_otaProgress; // 0-100

void sharedStateInit();
void publishStore(const radar::AircraftStore &s);
void snapshotStore(radar::AircraftStore &out);
