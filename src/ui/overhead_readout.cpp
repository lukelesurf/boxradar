#include "overhead_readout.h"
#include "palette.h"
#include "overhead.h"
#include "format.h"
#include "classify.h"
#include <stdio.h>

void drawOverheadReadout(TFT_eSprite &spr, const radar::AircraftStore &s,
                         float extraAgeS) {
  radar::OverheadPrediction p = radar::predictOverhead(s, extraAgeS);
  if (!p.valid) return;
  const radar::Aircraft *a = s.findByHex(p.hex);
  if (!a) return;

  char cs[10];
  radar::formatCallsign(cs, sizeof(cs), a->callsign, a->hex);
  char buf[28];
  snprintf(buf, sizeof(buf), "OVHD %s %us", cs, (unsigned)p.secondsAway);

  // Amber when it is worth getting up for. Living under a downwind leg means
  // something is nearly always about to pass overhead, so the readout being
  // permanently populated is expected — the colour is what separates "another
  // 738" from "a Global Express is about to go over the house".
  bool notable = a->isMlat || !radar::isCommonType(a->type);
  spr.setTextColor(notable ? TYPE_INTERESTING : BLOCK_TEXT, TFT_BLACK);
  spr.drawString(buf, STATUS_X, 3, 1);
}
