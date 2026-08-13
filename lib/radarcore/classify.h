#pragma once

namespace radar {

// True for the everyday types that are not worth looking up. The built-in list
// is the short-haul fleet that saturates a London-area feed; it is
// configurable because both the list AND its polarity are regional — this is a
// whitelist of boring, so at a GA field, where the everyday traffic is light
// singles, everything would otherwise read as interesting.
// Anything else is worth looking up from the desk — widebodies, bizjets,
// props, helicopters, military.
//
// An empty or unknown type counts as COMMON, deliberately. The type only
// exists if the receiver was started with a --db-file, and that database has
// gaps; treating every lookup miss as "rare" would fire the highlight on
// noise and drown the signal it exists to carry.
bool isCommonType(const char *type);

// The same question against an explicit comma-separated list, which is the
// testable half. Entries are whole designators, compared case-insensitively
// and ignoring surrounding spaces, because the list is typed by a person while
// the feed sends uppercase.
bool isCommonTypeIn(const char *type, const char *csv);

// Point isCommonType() at a different list. Null or empty restores the
// built-in one — a cleared setting is far more likely to be an accident than a
// deliberate "nothing is boring", which would light up every aircraft at once.
//
// The pointer is BORROWED, not copied: the caller owns the storage and must
// keep it alive. In the firmware that is the SiteConfig struct, which is
// static and outlives everything.
void classifySetCommonTypes(const char *csv);

// The built-in list, so the configuration UI can seed its box with it.
const char *classifyDefaultCommonTypes();

// 7500 hijack / 7600 radio failure / 7700 general emergency. Compared as
// strings — squawks are four octal digits where leading zeros matter.
bool isAlertSquawk(const char *squawk);

} // namespace radar
