#pragma once

namespace radar {

// True for the everyday short-haul types that saturate a London-area feed.
// Anything else is worth looking up from the desk — widebodies, bizjets,
// props, helicopters, military.
//
// An empty or unknown type counts as COMMON, deliberately. The type only
// exists if the receiver was started with a --db-file, and that database has
// gaps; treating every lookup miss as "rare" would fire the highlight on
// noise and drown the signal it exists to carry.
bool isCommonType(const char *type);

// 7500 hijack / 7600 radio failure / 7700 general emergency. Compared as
// strings — squawks are four octal digits where leading zeros matter.
bool isAlertSquawk(const char *squawk);

} // namespace radar
