# Viewport: tap-to-zoom design note

**Status: implemented 2026-08-08.** Design captured first so the reasoning
isn't lost; the code follows it, with the two decisions below resolved and
one refinement noted under *Settled*. The transform lives in
`src/ui/viewport.h` and is covered by `test/test_viewport`.

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

> There is a ninth, and it is the one that fails silently: `drawCoastline`
> derives a lat/lon window from `HOME_LAT/LON` to reject whole segments
> before projecting them. That is the *inverse* transform, and left
> home-centred it rejects exactly the segments an off-centre view needs —
> the coast just vanishes, with nothing to debug.

| state | centre | scale |
|---|---|---|
| **OVERVIEW** | home | 50nm |
| **DETAIL** | wherever you tapped | 10nm (5nm on toggle) |

The scope **boots into DETAIL on home at 10nm**, not into the overview. The
resting state of a device on a shelf should be the working picture; the
overview is somewhere you go. It costs nothing — a home-centred detail view
is `detailCentre = {0,0}`, which keeps its range rings by construction.

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

> This was half right, and the missing half only showed up in use. One tap
> does get you home at 50nm. Getting back to home *at 10nm* means tapping the
> home marker in the overview — and that failed, because the sub-pixel
> tolerance in `homeCentred()` is measured at the detail scale (11 px/nm)
> while the tap is aimed at the overview scale (2.2 px/nm). One pixel of aim
> becomes five pixels of offset, so only a tap on the exact centre pixel
> produced a genuinely home-centred view; every other tap left the range
> rings suppressed and the view a few nm off.
>
> Fixed by snapping: a tap within `HOME_SNAP_PX` (10px, ~4.5nm at overview
> scale) of the home marker sets the centre to exactly `{0,0}`. The cross
> already drawn there is its own affordance, so this still costs no new
> gesture. The trade is that you cannot deliberately centre on a point within
> ~4.5nm of home — worth nothing here, where the traffic of interest is
> further out, but it is the knob to turn if that changes.
>
> The general lesson: the two states were each reasoned about soundly, and
> the bug lived entirely in the *conversion between* them. Worth remembering
> if a third state (follow) is ever added.

## Consequences

**Range rings disappear when the view isn't centred on home.** They mean
"distance from you", so off-centre they'd be confusing arcs. Hiding them is
both the easiest and the most honest answer. A scale bar could replace them
later if the loss is felt.

Tested geometrically (`Viewport::homeCentred()`, sub-pixel tolerance) rather
than off the view state, so a tap that lands on home keeps its rings — which
is correct, not a special case.

**The home marker still draws** — it's just a marker at home's position,
which may now be off-screen. No special handling.

> Wrong in the overview, once the marker became the recenter target (above).
> A control has to be findable, and a 9px cross was not: home sits in the
> busiest part of a 50nm picture, and being drawn with the map furniture it
> was painted over by the airfield squares, town labels and blips clustered
> around it. Reported as "it works if I guess where it is".
>
> Three changes, none of them colour. It moved *after* the blip pass so
> nothing paints over it, it reserves occupancy cells so no datablock covers
> it, and in the overview it is drawn as a reticle whose arms reach exactly
> `HOME_SNAP_PX` — the mark you aim at is the tolerance you get.
>
> Colour was not available. `HOME_MARK` quantizes to `rgb332(0,7,0)` and
> `ALT_BAND_200` is `rgb332(1,7,1)` — the same green on an 8-bit sprite. Home
> is separated from traffic by *shape*, which is why the reticle is arms with
> a gap and never a ring: a green circle is precisely what an MLAT contact at
> FL150 looks like.
>
> Reserving cells contradicts the rule that waypoints don't, on the grounds
> that static furniture shouldn't push live traffic around. That rule still
> holds — in the overview this isn't furniture, and in detail it doesn't
> reserve.

**Datablocks are always two-line in detail**, since detail is always 10nm.
`TWO_LINE_MAX_NM` and the range-dependent trail spacing both become
constants in that state. Overview keeps the degraded single-line form.

> Since this was written the ranges became runtime settings (`ovnm`, `d1nm`,
> `d2nm`, `tlnm` — see `lib/radarcore/view_ranges.h`). The design above is
> unchanged; "detail is always 10nm" is now "detail is always one of the two
> configured levels", and the two-line threshold is only a constant in that
> state while it is set at or above them both.

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

> Implemented one step more general than written here. The rule is not "in
> overview" but "whenever *this block* renders single-line" — because
> `drawDatablock` already degrades 2→1 line under crowding, so a rare
> airframe in a busy stream was losing its amber marker at 10nm too. One
> condition, both cases.
>
> Moving it exposed a collision the two-line form had been hiding. Rarity on
> a *stale* block used to be signalled by drawing the type field brighter
> than its dim neighbours — which works only while it has neighbours. On a
> single-line block the callsign is the whole block, so "brighter than the
> rest" made a stale contact read as live, and in the overview every block is
> single-line. Brightness was carrying two facts at once. Fixed by giving
> rarity the free channel: `TYPE_INTERESTING_DIM`, same amber one rung down,
> so hue means unusual and brightness means old, independently.

**The overhead readout stays as-is.** It predicts passes over *home*, and
the store is home-centred and holds everything within 50nm regardless of
where the viewport is looking, so panning away never starves it. The worry
about it going stale belonged to the free-panning design, which would have
needed a view-centred store.

> If the store is ever changed to sort by view centre, this stops being
> true — the readout would then be predicting from data with home's traffic
> missing, and must be hidden or re-based.

## Resolved: getting to 5nm — option A

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

**Chose A**, on the grounds that exit is the common case and should not
degrade. B is tempting for requiring nothing new.

Rejected: long-press (no feedback during the hold, finicky on resistive)
and double-tap (would force a ~400ms delay onto every exit while waiting to
see if a second tap arrives).

One wrinkle the note didn't anticipate: the range readout's x position moves
with whatever the traffic segment printed before it — `AC 15 (5)` and
`NO UPDATE 123s` are very different widths — so a hardcoded rect would drift
off the text it is meant to be. `drawStatusCorner` therefore reports where it
actually drew the readout (`statusRangeHitZone()`), padded and grown to 24px
tall. The zone is live only in DETAIL; in OVERVIEW that corner is an ordinary
background tap, since there is nothing there to toggle.
