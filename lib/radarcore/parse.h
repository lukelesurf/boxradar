#pragma once
#include <ArduinoJson.h>
#include "aircraft.h"

namespace radar {

void buildAircraftFilter(JsonDocument &filter);
int loadStore(JsonVariantConst root, AircraftStore &dst,
              const AircraftStore &prev, float homeLat, float homeLon,
              float trailSpacingNm = TRAIL_SPACING_DEFAULT_NM);

} // namespace radar
