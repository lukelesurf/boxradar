#pragma once
#include <ArduinoJson.h>
#include <stddef.h>

namespace radar {

// Longest name in tar1090-db's table is 47 characters ("NORTH AMERICAN
// ROCKWELL Turbo Commander 690/840"), so this holds any of them whole. The
// panel truncates at draw time instead of the transport truncating here: what
// fits is a property of the panel's width, and widening it later should not
// need the buffer to change too.
enum { TYPE_NAME_LEN = 48 };

// Pulls one designator's name out of a /type response.
//
//   {"types":[{"id":"PC12","name":"PILATUS PC-12"},{"id":"ZZZZ"}]}
//
// Returns true when the designator was ANSWERED, which includes being answered
// with no name at all — `out` is then empty. That is not a failure and must not
// be retried: the Pi echoes every id it was asked about, so an entry with no
// "name" means the database has nothing for it and never will. Roughly 1 in
// 200 designators is stored with an empty name (GLID among them) and a further
// slice are simply absent from a table that covers 2,806 of ICAO's ~10,000.
//
// Returns false only when the id is missing from the response entirely, i.e.
// the Pi answered something unexpected. That one is worth another go.
bool loadTypeName(JsonVariantConst root, const char *designator, char *out,
                  size_t cap);

// Builds the lookup URL from the receiver URL, by swapping the last path
// segment: "http://pi:8081/contacts" becomes "http://pi:8081/type/PC12".
//
// Derived rather than configured because the two endpoints are the same
// process by construction — /type is served by the display service the board
// already polls — so a separate setting could only ever be set wrong, and the
// Device page is crowded enough already.
//
// Returns false, writing nothing, if the designator is not one to four
// alphanumerics. The designator arrives over the wire in the contact feed, and
// a URL is the wrong place to find out that something upstream sent rubbish.
bool typeNameUrl(const char *receiverUrl, const char *designator, char *out,
                 size_t cap);

} // namespace radar
