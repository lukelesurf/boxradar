# Viewport: tap-to-zoom design note

**Status: not implemented.** Design captured 2026-08-08 so the reasoning
isn't lost. Nothing in the codebase does any of this yet.

## Motivation

10nm is the useful working range, but at 10nm the interesting things are
off-screen — Stansted is 7.6nm away and its approach doesn't fit. The
current answer is to zoom out to 25 or 50nm, which shows everything at a
scale where the datablocks degrade to callsign-only and nothing is legible.

Rather than four zoom levels centred on home, use **two view states**: an
overview to choose from, and a fixed detail level to look at.

## The model

Today the projection origin, the view centre and home are the same thing.
Every draw site hardcodes it:

```c
int x = SCOPE_CX + (int)(p.x * pxPerNm);
```

The change is to introduce a viewport — a centre expressed as an NM offset
from home, plus a scale — and route every draw site through one transform.
Roughly eight call sites: coastline, airspace, centrelines, fixed refs,
rings, home marker, blips, trails.

| state | centre | scale |
|---|---|---|
| **OVERVIEW** | home | 50nm |
| **DETAIL** | wherever you tapped | 10nm |

## Interaction

| | tap a blip | tap background |
|---|---|---|
| **OVERVIEW** | *nothing* — selection disabled | zoom to DETAIL centred there |
| **DETAIL** | select + detail panel | return to OVERVIEW |

Selection is **deliberately disabled in overview**. On a resistive panel
with a 20px hit radius, "did you mean select or zoom?" would be ambiguous
exactly in the dense areas you most want to zoom into. Splitting by purpose
— overview navigates, detail inspects — removes the ambiguity entirely and
leaves one gesture per state.

Returning home needs no extra affordance: tapping out of detail lands on the
home-centred overview by construction.

## Consequences

**Range rings disappear when the view isn't centred on home.** They mean
"distance from you", so off-centre they'd be confusing arcs. Hiding them is
both the easiest and the most honest answer. A scale bar could replace them
later if the loss is felt.

**The home marker still draws** — it's just a marker at home's position,
which may now be off-screen. No special handling.

**Datablocks are always two-line in detail**, since detail is always 10nm.
`TWO_LINE_MAX_NM` and the range-dependent trail spacing both become
constants in that state. Overview keeps the degraded single-line form.

## Three problems that solve themselves

These were real objections to a free-scrolling/edge-pan version and simply
do not arise here:

1. **Bounds.** The detail centre comes from a tap inside the overview, so it
   can never land outside the generated coastline/airspace extent. No
   clamping logic needed — the interaction enforces it geometrically.
2. **The 32-aircraft store cap.** Free panning could have wandered to
   traffic the range-sorted store had already dropped. Here detail is always
   a subset of the overview, and at 50nm we see 9–14 aircraft against a cap
   of 32, so everything tappable is in the store by definition. *Caveat: this
   holds only while traffic within 50nm stays well under `MAX_AIRCRAFT`.*
3. **Knowing where you are.** Ten labelled airfields, four fixes and seven
   towns mean something on screen names the area wherever you zoom to. Under
   free panning this would have needed a home-direction arrow and a minimap.

## Designed for later: follow a selected aircraft

Anticipated, not built — but the refactor should not preclude it.

The requirement it imposes: **the viewport centre must be able to be
computed per frame, not stored as a constant.** Following a moving target
means the centre is a function of the current store, evaluated at the top of
each frame. If the transform is built around a fixed `Vec2 centre` set at
tap time, adding follow later means touching every call site again.

So: compute the centre once per frame into a local, and pass that through.
Static states just return the same value each time.

Open sub-questions for that mode, deliberately unanswered here: how it is
entered, and what happens when the followed aircraft ages out or lands.

## Performance

Not a concern. Measured frame cost is R6–15ms of sprite build against a
38ms SPI push and a 100ms budget. Panning changes what is drawn, not how
much — the same reject logic applies with a different window.

## Open questions

- **Is detail fixed at 10nm, or should it still cycle?** Fixing it loses
  5nm entirely, which is the range where a single airport's approach is
  clearest.
- **What does the overhead readout mean when panned away?** It predicts
  passes over *home*, which is arguably still what you want, but it would
  be sitting on a screen showing somewhere else.
- **Should overview draw datablocks at all?** If it exists purely to choose
  a region, bare blips might read better than 20+ callsign labels.
