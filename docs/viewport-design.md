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

## Settled

**Overview keeps its labels.** Identifying which aircraft is the target is
the whole point of choosing where to zoom, so bare blips are not enough.

**But the rarity signal has to move.** Overview shows callsign-only
datablocks, and the amber "not an everyday airframe" marker currently lives
on the *type* field on line 2 — which does not render at 50nm. So the cue is
invisible in precisely the mode that exists to choose what is worth looking
at. Fix: in overview, colour the **callsign** amber instead. Same glyphs,
same ink, signal delivered where the decision is made.

**The overhead readout stays as-is.** It predicts passes over *home*, and
the store is home-centred and holds everything within 50nm regardless of
where the viewport is looking, so panning away never starves it. The worry
about it going stale belonged to the free-panning design, which would have
needed a view-centred store.

> If the store is ever changed to sort by view centre, this stops being
> true — the readout would then be predicting from data with home's traffic
> missing, and must be hidden or re-based.

## Open question: getting to 5nm

5nm is wanted — it is the range where a single airport's approach is
clearest, and centring on Stansted is much of the point. The problem is the
gesture budget: detail mode already spends both taps (blip selects,
background exits).

Two credible options:

**A. Dedicated hit zone.** The `10nm` readout in the status strip becomes
the zoom toggle. No timing, no ambiguity, and exit stays a single tap. The
drawn strip is 10px but the hit zone need not match it — a ~24px band at
the bottom-left would be usable with a finger on a resistive panel.

**B. Extend the cycle.** Background tap goes OVERVIEW → 10nm → 5nm →
OVERVIEW. Needs no new interface at all and is entirely predictable, but
exiting from 10nm means passing through 5nm, so the most frequent action
gets slower.

Leaning A, on the grounds that exit is the common case and should not
degrade. B is tempting for requiring nothing new.

Rejected: long-press (no feedback during the hold, finicky on resistive)
and double-tap (would force a ~400ms delay onto every exit while waiting to
see if a second tap arrives).
