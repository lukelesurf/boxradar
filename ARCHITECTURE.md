# BOXRADAR: Architecture

A 320×240 ESP32 panel (ESP32-2432S028R, "Cheap Yellow Display") that renders a
live radar scope from a Raspberry Pi ADS-B receiver on the same LAN. The board
does no filtering and holds no aircraft database; the Pi does no drawing and
holds no site position. Everything interesting is in the render loop.

## Shape

```
  Pi (readsb + boxradar_site)        ESP32
  ┌──────────────────────────┐      ┌─────────────────────────────────────┐
  │ /contacts  binary, 2s    │─────▶│ core 0 "net"  poll, decode, project │
  │ /metar     60s           │      │        │ mutex-guarded double buffer │
  │ /site-X.bin geography    │      │        ▼                            │
  │ /type /operator  on tap  │◀─────│ core 1 "ui"   10 Hz render + touch  │
  └──────────────────────────┘      └──────────────┬──────────────────────┘
                                      pushSprite ──▼── ILI9341 over HSPI
```

Core 0 polls `/contacts` and decodes fixed-size records into a 32-slot store,
nearest-first. Core 1 renders. The split of responsibility is the next section.

## What comes from the Pi

`boxradar_site` (`tools/boxradar-site/`) sits in front of readsb. The division
of labour: **the Pi decides which contacts and what they mean; the board
decides where they are and how they look.**

### `/contacts`: traffic, every 2 s

Binary, not JSON. A 12-byte header (`BXAC`, version, record length, count,
total-before-cap) then up to 32 fixed 40-byte records, every field on its
natural alignment so the receive buffer can be cast in place. The board's
payload buffer is `CONTACT_HEADER_LEN + MAX_AIRCRAFT * CONTACT_RECORD_LEN` in
`.bss` and never grows, which was the whole point of the move. Parsing
tar1090's `aircraft.json` made the heap low-water mark a function of how many
aircraft happened to be airborne, because the document held the entire feed
before `MAX_AIRCRAFT` was applied.

The board sends its own parameters on the query string: home lat/lon, count,
altitude band (`amin`/`amax`), MLAT inclusion, and up to 12 watchlist patterns.

- Home rides on the request rather than living in the Pi's config, so the
  board's NVS stays the single authority for where "here" is and the service
  holds no site position it could silently disagree about.
- The band rides with it because the 32-slot cap saturates continuously.
  Filtering behind the cap would spend every slot and then hide most of them,
  so the Pi filters *before* it sorts and caps: the 32 are the nearest 32
  in the band.
- The watchlist rides with it so two boards at one receiver can watch for
  different things.

Fields are packed and saturate rather than wrap: alt/25, vert rate/64,
rssi×2, seen in whole seconds, because a wrapped value is a plausible-looking
lie (a jet at FL350 reading as a descent through the sea floor) where a
saturated one is merely wrong at the edge of a range nothing real occupies.
Three flag bits: on-ground, MLAT, watched. `watched` was a spare bit in a byte
that already had two used, so the watchlist needed no version bump and no
layout change; a board built before it existed simply never sets or reads it.

Two things deliberately absent from the wire:

- Nothing derived: no range, no bearing, no screen position, only raw lat/lon. The board projects them itself, so a Pi configured for a different site
  can pick the wrong contacts but can never *move* the right ones.
- No `alt_known`: the band filter is applied on the Pi, so the board never
  has to tell "0 ft" from "no idea", two states that are the same number once
  `alt_baro` goes missing, and that would make a jet with a dropped altitude
  field vanish the moment anyone set a floor above zero.

A dead receiver answers 503, not an empty 200: a header with no records is
a legitimate answer meaning "quiet sky", and the board would believe it.

### The rest

| Endpoint | Cadence | Carries |
|---|---|---|
| `/contacts` | 2 s | traffic, as above |
| `/metar/<ICAO>` | 60 s | normalised weather, plus the runway the wind implies |
| `/site-<name>.bin` | 10 min, conditional GET | the geography blob |
| `/type/<designator>` | on tap | `PC12` → `PILATUS PC-12` |
| `/operator/<code>` | on tap | `BAW` → British Airways (SPEEDBIRD) |

`pick_runway` returns no runway for an empty table and flags low confidence
below the calm threshold, rather than asserting a runway the airfield is not
using. For `/type` and `/operator` the contract is that every requested id is
echoed, and `name` is present only when there is one: an id with no name is
a definitive answer the board can cache and stop asking about, where a 404 or a
503 would have it retry forever for a designator that will never resolve. The
board keeps one single-slot mailbox per lookup, keyed by what was asked, so a
late reply is matched out rather than drawn against whatever you tapped next.

### The back channel

There is no inbound connection to the board. Instead, `/contacts` responses can
carry `X-Boxradar-Config` ("open your config server") and `X-Boxradar-Geo`
("refresh your map now"), riding a poll the board already makes. Both are
hints with interval fallbacks: a board that was rebooting or off-wifi when the
header went out never hears it, and a map that updates late beats one that
never updates with nothing to say so. The headers are attached to the route,
not the success path: a receiver that is down must not also cost you the
ability to configure the board.


## The frame

`ui_task.cpp:uiTaskLoop` runs at `UI_FRAME_MS = 100` (10 fps). Each frame:
snapshot the store under the mutex → build a `Viewport` → take `geoStoreLock()`
→ `drawScope()` → poll touch → `drawDetailPanel()` → `pushSprite(0,0)`.

Measured with `-DBOXRADAR_FRAME_TIME`: 6–15 ms of sprite build against a
38 ms SPI push, inside a 100 ms budget (`docs/viewport-design.md`). The
push is a fixed 153.6 KB transfer and responds to nothing we can optimise, so
the overlay reports `R` and `P` separately: conflating them is how you end up
optimising the half that was never the problem.

## Rendering

### One sprite, eight bits

The whole panel is a single 8-bit `TFT_eSprite`: 76,800 B, allocated once at
task start. 16-bit would want 153.6 KB and this board's largest contiguous
block measured 110,580 B, so there is no 16-bit path and no banded fallback,
because a second render path with 33 KB of headroom would be dead code.
Failure to allocate is fatal and says so on the panel.

Eight bits means TFT_eSPI quantizes every colour to RGB332: 3 bits red, 3
green, 2 blue. Hand-picked 565 literals routinely collapse into each other
under that, so `src/ui/palette.h` never writes one: `rgb332(r3,g3,b2)` takes
the post-quantization components directly, which makes two constants distinct
on screen iff their arguments differ. The entire dark-grey range is three
rungs (`rgb332(1,1,0)` up), and the map layers use all three: coast, then
airspace/centrelines, then airfield marks.

### Colour is spent, so everything else uses a different channel

Hue means altitude, everywhere, warm-low to cool-high. That budget is fully
committed, so every other signal had to find its own channel:

| Signal | Channel |
|---|---|
| altitude band | hue |
| position age | brightness (`BLOCK_TEXT` → `BLOCK_TEXT_DIM`) |
| rare airframe | hue on the type field only (amber), dimmed in parallel |
| MLAT position | shape: hollow ring, not a filled blip |
| watchlist / alert / selected | rings at r=4 / 5 / 6, so all three can be true at once |
| home | shape: the only cross on the scope |

`HOME_MARK` is one rung from `ALT_BAND_200` and indistinguishable after
quantization; the palette says so in a comment and forbids a circular home
marker, because a green ring would read as an MLAT contact at FL150.

### The viewport is the only NM→pixel path

`src/ui/viewport.h` owns the transform. Before it existed every draw site
open-coded `SCOPE_CX + p.x * pxPerNm`, silently baking in "the view is centred
on home"; routing them all through one struct is what makes an off-centre view
possible at all. It is built fresh each frame from `UiState` rather than
stored, so a future follow-the-selected-aircraft mode becomes a function of the
store without touching a single draw site.

It also carries the inverse (`toNm`), which is what turns a tap on the 50 nm
overview into the centre of the detail view, and `homeCentred()`, tested
*geometrically* rather than off the view state, so range rings appear exactly
when "distance from you" is an honest reading of them.

### Layer order

`fillSprite` → coastline → airspace → extended centrelines → range rings (home
only) → airfields/waypoints/towns → blips → home marker → datablocks →
overhead readout → squawk banner → status strip → detail panel.

Furniture never reserves label space: waypoints are scenery, and blocking a
label over a fixed point would push live traffic around to protect something
static. The one exception is the home marker in overview, where it stops being
scenery and becomes the tap target that snaps back to a home-centred view.

### Two passes, opposite orderings

Blips draw far→near so close traffic wins overlapping pixels. Datablocks
place near→far so close traffic wins the contested *space*. Same rule, two
directions, because one is a painter's overwrite and the other is a first-come
allocation. The store is already range-sorted, so each is a single sweep.

Block priority is the pass-2 loop order: selected (an explicit tap outranks
every heuristic), then alert squawks, then watchlist hits, then rare airframes
and MLAT, then nearest. Without the tiers the layout contradicted the colours:
a 7700 forty miles out could lose its block to a 738 on short final.

### Placement: occupancy grid plus hysteresis

`datablock.cpp` keeps an 8 px occupancy grid: 1200 cells as a 150-byte
bitfield in `.bss`, no allocation. Each aircraft tries 8 candidate slots (four
diagonals near, the same four on a longer leader), two lines then one, taking
the first that is fully on-screen with every covered cell free.

The part that matters is `Placement`: the winning slot is remembered per
aircraft, keyed by ICAO hex so it survives the store re-sorting by range, and
retried first next frame. Without it the placer recomputes a fresh global
layout every frame and one blip crossing a cell boundary cascades into every
other block moving, which reads as the whole screen twitching.

### Staying inside the budget

- Coastline is ~1900 points, an order of magnitude more than the rest of
  the map. The panel is inverted into a lat/lon window once per frame and each
  segment's bounding box is tested against it. At 10 nm inland that rejects
  the lot without projecting a point. The window is derived from the viewport,
  so it moves with the centre; a home-centred window against an off-centre view
  would reject exactly the segments now on screen.
- `cosf` hoisting: `lonScaleNm(HOME_LAT)` is computed once per frame and
  passed to `projectWith()`. The naive `project()` recomputes it per call,
  which cost ~19k `cosf` per second across the map layers.
- Trails are stored in the NM frame, so drawing them is a scale, not a
  reprojection, previously ~320 `project()` calls per frame.
- Dashes step in pixels, not nautical miles; an NM dash collapses into
  stipple at 50 nm.

## Around the renderer

Geography is a blob fetched over conditional GET and cached in LittleFS
(`src/geo_store.h`). `GeoMap` is a zero-copy view into one heap buffer, so
every outline and label drawn is a pointer into memory the net task may be
about to free, hence `geoStoreLock()` held across the frame that reads it.
The store holds it only for pointer assignments, so a frame waits microseconds.
Compiled tables remain one build flag away as a known-good reference.

Name lookups cross tasks on a tap: the UI knows what is selected, only the
net task may do HTTP, and neither may block the other. Two single-slot
mailboxes in `shared_state.h`, one per lookup; requesting is idempotent, so the
UI can simply ask every frame what the current selection needs rather than
detect the several ways a selection can change.

Configuration is NVS as an overlay on compiled defaults, applied before
anything reads config, so a bad stored value cannot make the board
unreachable. Ranges, ageing thresholds and layer switches are runtime settings;
`MAX_AIRCRAFT` and `TRAIL_LEN` stay compiled because they size `.bss`.

## Testing

`lib/radarcore/` is Arduino-free and STL-free, and `src/ui/viewport.h` and
`layout.h` are kept clean of TFT includes on purpose: the projection and
placement maths is the part worth testing, and staying natively linkable is
what makes that possible. `pio test -e native` covers projection, the contact
feed, the geo blob, the viewport, classification and config.
