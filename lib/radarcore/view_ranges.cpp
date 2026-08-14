#include "view_ranges.h"

namespace radar {

namespace {

// 50nm shows every airfield and approach that matters at the original site;
// 10nm is the working picture a tap lands on and 5nm the closer look. The
// two-line threshold sits on the wider detail range, so as shipped it reads as
// "detail gets two lines, the overview does not".
const ViewRanges DEFAULTS = {50.0f, {10.0f, 5.0f}, 10.0f};

ViewRanges s_ranges = DEFAULTS;

} // namespace

const ViewRanges &viewRanges() { return s_ranges; }

const ViewRanges &viewRangesDefaults() { return DEFAULTS; }

void viewRangesSet(const ViewRanges &ranges) {
  if (ranges.overviewNm > 0.0f) s_ranges.overviewNm = ranges.overviewNm;
  for (int i = 0; i < VIEW_DETAIL_RANGES; i++)
    if (ranges.detailNm[i] > 0.0f) s_ranges.detailNm[i] = ranges.detailNm[i];
  // Zero is a legitimate choice here — it means no datablock ever gets a
  // second line — so only a negative is refused.
  if (ranges.twoLineMaxNm >= 0.0f) s_ranges.twoLineMaxNm = ranges.twoLineMaxNm;
}

} // namespace radar
