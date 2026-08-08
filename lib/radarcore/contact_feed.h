#pragma once
#include <stddef.h>
#include <stdint.h>
#include "aircraft.h"

// Reader for the binary contact feed served by boxradar_site.contacts.
//
// This replaces parsing tar1090's aircraft.json on the board. The JSON path
// made the heap low-water mark a function of how many aircraft happened to be
// airborne — the document held the whole feed before MAX_AIRCRAFT was applied.
// Here the Pi has already filtered, range-sorted and capped, so what arrives
// is at most MAX_AIRCRAFT fixed-size records and the allocation is a constant.
//
// Format: docs/superpowers/specs/2026-08-08-contact-feed.md.
//
// Portable on purpose: stdint and string.h only, no Arduino and no
// ArduinoJson, so it links in [env:native] and is tested off device. It must
// also compile under gnu++11, which is what the ESP32 core uses.

namespace radar {

enum {
  CONTACT_HEADER_LEN = 12,
  CONTACT_RECORD_LEN = 40,
  CONTACT_VERSION = 1,
};

enum ContactStatus {
  CONTACT_OK = 0,
  CONTACT_BAD_MAGIC,
  CONTACT_BAD_VERSION,
  CONTACT_BAD_RECORD_LEN,
  CONTACT_TRUNCATED,
};

const char *contactStatusName(ContactStatus status);

// Longest payload the board can be sent, so callers can size a static buffer
// without duplicating the arithmetic.
enum {
  CONTACT_MAX_PAYLOAD = CONTACT_HEADER_LEN + MAX_AIRCRAFT * CONTACT_RECORD_LEN
};

// Fill `dst` from a /contacts payload, carrying trails over from `prev`.
//
// Positions arrive as raw lat/lon and are projected here, deliberately: the
// board's own home is the only thing that decides where traffic is drawn, so
// a Pi configured for a different site can pick the wrong contacts but can
// never move the right ones. See the spec's "lat/lon, not projected x/y".
//
// On any status other than CONTACT_OK, `dst` is left cleared rather than
// half-filled — a partially decoded store would render as traffic vanishing
// for one poll with no other indication.
ContactStatus loadContacts(const uint8_t *data, size_t len, AircraftStore &dst,
                           const AircraftStore &prev, float homeLat,
                           float homeLon,
                           float trailSpacingNm = TRAIL_SPACING_DEFAULT_NM);

} // namespace radar
