#pragma once
#include <stdint.h>

// The board's settings server, in STA mode, started only when asked.
//
//   GET  /config   what is in force, per key, and whether it came from NVS
//   POST /config   key=value pairs to write, clear=key to erase. Then restart.
//
// **Nothing is allocated until it is wanted.** The server is new'd on demand
// and delete'd when the window closes, which is the same discipline
// portal.cpp uses and for the same reason: the render sprite leaves the heap
// floor around 43KB, and a WebServer sitting there permanently would spend
// several KB of that to serve a page touched twice a year.
//
// The request to open it arrives as an `X-Boxradar-Config` response header on
// the ordinary /contacts poll, which the board is already making every couple
// of seconds. It is a header rather than a payload flag because the contact
// feed is a fixed binary format with no reserved field — a flag byte would
// have meant bumping CONTACT_VERSION, and contact_feed.h rejects an unknown
// version outright, so an updated Pi would blank the scope of a board that
// had not been reflashed yet.

// Open the window (or extend it if already open). Idempotent.
void configServerOpen();

// Pump the server and close the window when it expires. Call from the net
// task loop; does nothing when closed, so it is cheap on the common path.
void configServerHandle();

// True while the server is up. Opening and closing are both logged over
// serial; nothing is drawn on the panel, because ui_task.cpp owns every pixel
// after boot and a settings window is not worth reaching into it for.
bool configServerActive();

// How long the window stays open after being asked. Long enough to read the
// form, change a value and save; short enough that a stray wake does not
// leave it listening all day.
static const uint32_t CONFIG_SERVER_WINDOW_MS = 120000;
