#pragma once
#include <stddef.h>
#include "aircraft.h"
#include "metar.h"
#include "type_name.h"

extern volatile bool g_otaActive;
extern volatile uint8_t g_otaProgress; // 0-100

// Trail dot spacing in NM, published by the UI task (only it knows px/nm)
// and read by the net task, which is where trail points are appended. A
// plain aligned float rather than mutex-guarded: a torn read is impossible
// on this architecture, and a one-poll-stale value only affects where a
// single dot lands.
extern volatile float g_trailSpacingNm;

void sharedStateInit();
void publishStore(const radar::AircraftStore &s);
void snapshotStore(radar::AircraftStore &out);

// METAR shares the same mutex as the aircraft store rather than taking its
// own. Both are written by the net task and read by the UI task, contention
// is negligible at 10fps against 2s/60s polls, and one lock removes any
// chance of the two orderings deadlocking against each other.
void publishMetar(const radar::Metar &m);
void snapshotMetar(radar::Metar &out);

// ------------------------------------------------------- aircraft type names
// The board holds the designator ("PC12") and the Pi holds the name ("PILATUS
// PC-12"), so a tap has to cross tasks: the UI knows what is selected, only
// the net task may do HTTP, and neither may block the other.
//
// ONE entry, not a table. You look at one aircraft at a time, and the single
// slot means two of the same type on screen cost one lookup between them. It
// also means the answer arrives keyed by designator, so a reply that lands
// after you have tapped something else is matched out rather than shown
// against the wrong aircraft.
//
// Requesting is idempotent and cheap enough to call every frame: an unchanged
// designator does nothing at all. Changing it discards whatever was resolved,
// because the old name belongs to an aircraft you are no longer looking at.
void requestTypeName(const char *designator);

// For the net task: the designator still waiting on an answer, or false if
// there is nothing to do. Applies its own retry spacing, so calling this on
// every pass of a 50ms loop does not become a 20Hz request storm.
bool pendingTypeName(char *out, size_t cap);

// The answer, whether or not it found a name. An empty `name` is a real
// result — the database has nothing for this designator — and marks it
// answered so it is never asked again.
void publishTypeName(const char *designator, const char *name);

// Records that an attempt failed, so the retry timer starts and the attempt
// counter advances. After a few of these the designator is given up on, which
// is what stops an unreachable Pi being retried forever.
void failTypeName(const char *designator);

// For the UI: the name for this designator, or empty until one arrives. Takes
// the designator so a stale answer for a previous selection can never be drawn
// against the current one.
void typeNameFor(const char *designator, char *out, size_t cap);

// ------------------------------------------------------------- operator names
// Identical machinery to the type names above, keyed by the three-letter
// airline code instead of the designator, and deliberately a SECOND slot
// rather than a shared one: a tap wants both answers at once, so one slot
// would have the two lookups evicting each other on every selection.
//
// The code is derived from the callsign by radar::operatorCodeFrom(), which
// refuses anything that is not three letters followed by a digit — so a
// registration never produces a plausible-looking code and a wrong airline.
void requestOperator(const char *code);
bool pendingOperator(char *out, size_t cap);
void publishOperator(const char *code, const char *name, const char *radio);
void failOperator(const char *code);

// For the UI: the operator for this code, or empty until one arrives. `radio`
// may be empty while `name` is not — several hundred operators have no radio
// callsign registered, which is a partial answer rather than a failure.
void operatorFor(const char *code, char *name, size_t nameCap, char *radio,
                 size_t radioCap);
