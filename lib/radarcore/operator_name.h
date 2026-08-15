#pragma once
#include <ArduinoJson.h>
#include <stddef.h>

namespace radar {

// Callsign prefix to the operator behind it. `RYR4ZQ` is Ryanair; `RRR7241`
// is the RAF, and on the radio it is ASCOT.
//
// Same shape as type_name.h and for the same reason: 6,310 operators at 407KB
// is far past what this flash has spare, so the Pi holds the table and the
// board asks about one code at a time. This is the second user of the
// board-to-Pi lookup channel /type introduced, which is what that channel was
// for — another route rather than another design.

// Longest operator name in tar1090-db's table comfortably fits 48; the radio
// callsign is a single word. Both are truncated at DRAW time rather than in
// transport, because what fits is a property of the panel's width and
// widening the panel later should not need these to change.
enum { OPERATOR_NAME_LEN = 48, OPERATOR_RADIO_LEN = 20 };

// The three-letter airline code at the front of a callsign, or false if this
// callsign does not carry one.
//
// The rule is three letters FOLLOWED BY A DIGIT, and the digit is the whole
// point. An airline callsign is an ICAO code plus a flight number — BAW123,
// RYR4ZQ, EZY85TG — so the fourth character is always a digit. A general
// aviation aircraft uses its registration instead, and feeds strip the dash:
// `GBXYZ` for G-BXYZ. Taking the first three characters of that yields `GBX`,
// which is a perfectly plausible key and may well be a REAL operator — so the
// lookup would not fail, it would confidently return the wrong airline.
//
// Requiring the digit costs nothing real (no airline callsign lacks one) and
// removes the entire class. Same instinct as alt_known on the Pi: the danger
// is not the absent answer, it is the absent answer that looks present.
bool operatorCodeFrom(const char *callsign, char *out, size_t cap);

// Pulls one code's operator out of an /operator response.
//
//   {"operators":[{"id":"BAW","name":"British Airways","radio":"SPEEDBIRD"}]}
//
// Returns true when the code was ANSWERED, which includes being answered with
// nothing — `name` is then empty. That is not a failure and must not be
// retried: the Pi echoes every id it was asked about, so an entry with no name
// means the database has nothing for that code and never will.
//
// `radio` may be empty while `name` is not. Several hundred operators are
// registered with no radio callsign, and that is a partial answer worth
// keeping rather than a reason to discard the name.
//
// Returns false only when the id is missing from the response entirely, i.e.
// the Pi answered something unexpected. That one is worth another go.
bool loadOperatorName(JsonVariantConst root, const char *code, char *name,
                      size_t nameCap, char *radio, size_t radioCap);

// Builds the lookup URL by swapping the receiver URL's last path segment, so
// "http://pi:8081/contacts" becomes "http://pi:8081/operator/BAW". Derived
// rather than configured for the reason typeNameUrl() gives: the endpoints are
// the same process by construction, so a separate setting could only be wrong.
//
// Returns false, writing nothing, if the code is not exactly three letters.
bool operatorUrl(const char *receiverUrl, const char *code, char *out,
                 size_t cap);

} // namespace radar
