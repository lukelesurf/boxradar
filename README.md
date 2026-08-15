# BOXRADAR v2

A desk-toy ADS-B radar scope on a £15 ESP32 touchscreen. Pulls decoded
aircraft from a readsb/tar1090 receiver on the LAN and renders a north-up
display in the style of an ATC scope: altitude-coloured blips with two-line
datablocks over a map of coastline, controlled airspace, runway centrelines,
airfields, navigation fixes and towns. Successor to the ESP8266/Nokia 5110
original.

![BOXRADAR in its printed wedge enclosure on a desk, running the 10nm
range: eleven datablocks over the Stansted CTA with airspace outlines,
runway centrelines, coastline and the BKY/HARL/BPK fixes, an "OVHD GZIPI
74s" alert in the top-left corner, and the status strip reading "AC 11
(1) +21 - 10nm - EGSS 04? - 120/03 - CLEAR". The LDR light path is
visible as a small hole in the bezel below the
screen.](docs/boxradar-enclosure.jpg)

## Hardware

- **ESP32-2432S028R** — the "Cheap Yellow Display": ESP32 (dual-core
  240MHz, 520KB SRAM, no PSRAM), 2.8" ILI9341 240×320 TFT, XPT2046
  resistive touch, LDR, RGB LED
- A LAN receiver running readsb/tar1090 (or anything serving
  dump1090-style `aircraft.json`)

No wiring — everything used is on the board. Pin map and board quirks are
in [SPEC.md](SPEC.md).

### Case

`case.scad` is a parametric 30° wedge console enclosure in OpenSCAD: a
wedge body with standoff bosses for the board, plus a screwed-on rear
panel carrying a cable exit notch and vents. It includes a light path
drilled through the bezel for the LDR.

Set `part` at the top of the file to choose what to render —
`body_print`, `panel`, `assembly` or `fit_test`. **Print `fit_test`
first**: it's the bezel face and bosses only, so it checks board fit and
the dimensions tagged `VERIFY` in the source without committing to a full
print. Fixings are 4× M3×6 self-tap (board to bezel bosses) and 4× M3×8
(panel to corner bosses).

## Features

### Traffic

- **Datablocks** in ATC style: callsign on line 1, then level in hundreds
  of feet, a climb/descent arrow and the ICAO type on line 2. Two lines at
  5/10nm, callsign only at 25/50nm. Placed against an occupancy grid with
  per-aircraft memory so labels don't hop about
- **Blip colour encodes altitude** — red below 2000ft through orange,
  yellow, green and cyan to violet above FL300; grey on the ground
- **Rare airframes stand out**: the type field turns amber for anything
  outside the everyday short-haul fleet (A320/737 families, E-jets,
  ATR/Dash 8), so widebodies, bizjets, props, helicopters and military
  are obvious at a glance
- **MLAT positions drawn as hollow rings** — multilaterated by the feed
  network rather than transmitted by the aircraft, so a few hundred metres
  less certain than ADS-B; and in saturated airspace an aircraft not
  sending ADS-B at all is unusual in its own right
- **Squawk watch**: 7500/7600/7700 flash the blip red and raise a banner
- **Trails** are distance-gated, so the dots are evenly spaced whether
  the aircraft is a 90kt Cessna or a 450kt jet, at every range
- **Next-overhead readout** (`ohon`): the aircraft predicted to pass closest
  to overhead soonest, amber when it's an MLAT target or a rare type.
  Manoeuvring aircraft are excluded rather than guessed at — see below. What
  counts as overhead is three settings (`ohrnm`, `ohsec`, `ohturn`)
- **Tap to zoom.** Two view states rather than a cycle of ranges: a 50nm
  overview you choose from, and a 10nm (or 5nm) detail view centred on
  wherever you tapped. One gesture per state — the overview only
  navigates, the detail view only inspects — so nothing is ambiguous on a
  resistive panel. Tapping the home cross in the overview snaps back to a
  true home-centred view. See [viewport-design.md](docs/viewport-design.md)
- Tap a blip in the detail view for a panel: callsign, hex, type, alt, GS,
  track, vertical rate, range/bearing, RSSI, squawk, MLAT. Tapping the
  range readout in the status strip toggles 10nm/5nm
- Aircraft dim after 30s without a message and drop at 60s (`sdim`, `sdrop`) —
  raise both for an antenna with a poor horizon, where the same aircraft
  otherwise flickers out every few polls
- **Feed filters**, applied by the Pi rather than the board — see below.
  `amin`/`amax` hide anything outside an altitude floor and ceiling in feet,
  so a site under an airway can drop the overflights and keep the circuit, or
  vice versa. `mlaton` hides multilaterated traffic entirely, which frees cap
  slots for positions the aircraft transmitted itself — at the cost of the
  signal the hollow ring carries

### Map

Three marker shapes, so categories are tellable apart at 5px without
reading the label: **solid square** = airfield, **hollow square** = town,
**triangle** = navigation fix. All drawn under the traffic — a datablock
always wins where they collide.

Everything on the map arrives in one binary blob the board fetches from the Pi
and caches to LittleFS, so relocating is a publish rather than a reflash. The
generated C headers are still in the repo and still one build flag away — see
Relocating.

- **OSM coastline** as the bottom layer (`coaston`), generated offline and
  filtered to features ≥2km. The expensive layer by an order of magnitude, so
  it is the one worth being able to switch off
- **Controlled airspace** — CTR outlines and CTR+CTA envelopes, chosen per
  site by a selection file. Generated offline from the
  [ahsparrow/airspace](https://github.com/ahsparrow/airspace) UK dataset
- **Extended runway centrelines**, dashed, 6.5nm beyond each threshold —
  deliberately only for the fields whose approaches matter locally
- **Airfields, fixes and towns**, also from the selection

### Chrome and behaviour

- **Full-width status strip**: WiFi tick/cross, aircraft **on screen** with
  the MLAT subset in brackets, range, and — with the optional METAR feed —
  active runway, wind, cloud and restricted visibility. A stale feed
  replaces the count with a warning rather than adding a line
- **Night mode** (`nighton`): between `nstart` and `nend` the panel fades to a
  dim red 7-segment clock, or to black with `nclkon` off. A tap wakes the radar
  for 30s and then returns. Time comes from NTP — there is no RTC — and shows
  `--:--` rather than guessing before the first sync. DST is handled by a POSIX
  TZ rule, not a fixed offset
- LDR-driven backlight dimming, RGB LED status (red no-WiFi / amber
  no-data), OTA updates with on-screen progress
- **Twenty-nine settings live on the board's NVS and are editable from the
  Pi** — ranges, the feed filters, layers, thresholds, ageing, night
  blanking, poll intervals, the ordinary-type list — none of which costs a reflash. NVS is an *overlay*: an
  empty one behaves exactly like the compiled defaults, which is what keeps a
  board on WiFi and reachable over OTA no matter what the config layer does.
  See Site application, below

## Architecture

Core 0 polls the receiver's `/contacts` endpoint every 2s and decodes
fixed-size binary records into a 32-slot store (nearest-first). The Pi has
already filtered, range-sorted and capped, so the board's traffic allocation
is a constant rather than a function of how busy the sky is — the JSON
document it used to build was the largest thing on the heap and grew with
traffic. Core 1 renders the scope into a single 320×240 8-bit sprite and
handles touch. The two share a mutex-guarded double buffer. Positions arrive
as raw lat/lon and project on the board through a home-centred
equirectangular approximation, deliberately: the board's own home is the only
thing that decides where traffic is drawn. `lib/radarcore` holds the portable
decode/projection/format/classification/prediction logic and is unit-tested
natively.

Rendering runs in two passes with deliberately opposite orderings. Blips
draw far→near so close traffic wins overlapping pixels; datablocks place
near→far so close traffic wins the contested *space*. Blocks are placed
against an 8px occupancy grid and remember their slot per aircraft
between frames — without that memory, one blip crossing a cell boundary
cascades into every other block moving. Placement priority is: selected,
then alert squawks, then rare airframes and MLAT targets, then nearest
first.

The coastline is an order of magnitude more geometry than everything else
on the map, so it carries per-segment bounding boxes and the panel is
converted to a lat/lon window once per frame. At 10nm inland that rejects
all of it without projecting a single point. `project()` also has a
hoisted form — the naive one recomputes `cos(homeLat)` per call, which was
costing ~19k `cosf` a second across every map layer.

Predicting an overhead pass is easy; knowing when *not* to answer is the
hard part. Straight-line extrapolation is good for arrivals on a stable
leg and worthless for departures turning onto a SID, so steadiness is
measured as **curvature** — degrees of track change per nautical mile —
which needs no timestamps and holds at any speed.

MLAT requires the receiver to be feeding a network that returns results —
here an `mlat-client` feeding ADSBExchange with
`--results beast,connect,127.0.0.1:30104`, which readsb ingests via
`--net-bi-port`. Without that the `type` field is `adsb_icao` throughout
and no blip is ever hollow. Note `type` (position source) and `t`
(airframe type designator) are unrelated fields that collide confusingly
in the dump1090 schema.

The sprite is 8-bit, so TFT_eSPI quantizes colours to RGB332 — 3 bits
red, 3 green, 2 blue. `src/ui/palette.h` builds its constants from those
surviving components rather than from 565 literals, which makes two
colours distinct on-screen if and only if their arguments differ. The
entire dark-grey range is three rungs, and the map layers use all of them.

Design notes live in [docs/](docs/) — see
[viewport-design.md](docs/viewport-design.md) for the reasoning behind the
tap-to-zoom model and the objections it sidesteps.

## Building

Toolchain is PlatformIO via the Nix devShell (`direnv allow` or
`nix develop`). Then:

```bash
cp include/config.example.h include/config.h   # fill in WiFi, receiver URL, home lat/lon
pio run -e southend-usb -t upload               # first flash over serial
pio run -e southend     -t upload               # thereafter; needs BOXRADAR_OTA_PASS in env
pio test -e native                             # unit tests, no hardware needed
```

**There is no site-less env.** Each board gets a pair of envs — `<site>` over
the air and `<site>-usb` over serial — carrying both its `-DBOXRADAR_SITE_*`
flag and its upload address, and `config.h` `#error`s without one. The pairing
is deliberate: a board rejects any blob not built for its own home
(`GEO_HOME_TOLERANCE_DEG`, ~11m, in `lib/radarcore/geoblob.h`), and it does so
*silently* — it keeps drawing its cached map. Flashing one board with the
other's firmware would otherwise look fine for hours. Adding a board is one
`#elif` in `config.h` and one env pair in `platformio.ini`.

Partitions are `min_spiffs.csv`: both OTA slots kept, 1.875 MiB each,
with the extra space taken from a SPIFFS partition this project never
uses. Changing the partition scheme **cannot be done over OTA** — see
SPEC.md.

If the display shows wrong/inverted colours, it's the CYD panel-batch
lottery — see Known Quirks in SPEC.md.

### Debug build flags

Compile out entirely unless requested:

```bash
PLATFORMIO_BUILD_FLAGS=-DBOXRADAR_FRAME_TIME pio run -e southend -t upload
```

- `BOXRADAR_FRAME_TIME` — frame cost in the top-right: `R` is building the
  sprite, `P` is the SPI push. Splits the two halves that get conflated
  when guessing about performance
- `BOXRADAR_FAKE_ALERT` — stamps 7700 on the nearest aircraft, so the
  emergency path can be exercised without waiting years for a real one
- `BOXRADAR_SERIAL_TABLES` — per-poll aircraft table over serial

### Aircraft type

The type field — shown in the datablock and used to decide whether an
airframe is worth highlighting — relies on the receiver embedding types
in `aircraft.json`: point readsb at a database with
`--db-file=/usr/local/share/tar1090/aircraft.csv.gz` (file from the
[tar1090-db](https://github.com/wiedehopf/tar1090-db) `csv` branch).
Without it the type shows as `-`, and an unknown type is deliberately
treated as ordinary rather than rare — flagging every database miss
would drown the signal the highlight exists to carry.

### Regenerating airspace

Normally you don't: the config UI on the Pi picks the airspace and publishes a
blob, and the board reloads it in about half a second. This is the offline
path, and `--out` writes the **superseded** compiled table rather than
anything the board reads by default. From `tools/boxradar-site/` inside the
devShell:

```bash
SEL=boxradar_site/geo/selection.example.json
python3 -m boxradar_site.geo build --selection $SEL --fetch \
  --blob /var/www/html/site.bin          # what the board actually fetches
python3 -m boxradar_site.geo build --selection $SEL \
  --out ../../src/ui/airspace_data.h     # the compiled-table fallback
```

Which airspace is drawn is the selection file, not a rule. Each entry is a
group: `primary` is the feature drawn on its own as `<NAME>_CTR`, and
`envelope` lists features merged *with* it into `<NAME>_ENV`. The envelope is
often empty, because not every field has a CTA of its own — Heathrow's zone is
`LONDON CTR` sitting directly under the TMA, so it is a primary with nothing
grouped to it.

Multi-volume features are merged, and genuinely disjoint ones (the two
Stansted TMZ lobes) are emitted separately rather than unioned into airspace
that doesn't exist. Self-intersecting or degenerate rings are reported as
problems and abort the build.

Use `geo list` and `geo suggest` (see Relocating, below) to find what is near
you rather than looking feature names up by hand. `suggest` will not offer the
London TMA: it is the wrong kind *and*, at 151nm across, far wider than the
109nm the overview panel covers — an outline larger than the panel cannot read
as an enclosure, it reads as an arbitrary line across the display. Six enroute
CTAs (Daventry, Clacton, Cotswold, Portsmouth, Worthing, North Sea) are
excluded on width alone, and Daventry is wider than the TMA.

### Regenerating the coastline

The coastline rides in the blob with everything else, so normally there is
nothing to regenerate by hand — publishing from the config UI does it. The
standalone `tools/build_coastline.py` this section used to describe is gone;
the same job is now two flags on `geo build`:

```bash
# inside the devShell, from tools/boxradar-site/
SEL=boxradar_site/geo/selection.example.json
python3 -m boxradar_site.geo build --selection $SEL --coastline \
  --blob /var/www/html/site.bin                 # into the blob
python3 -m boxradar_site.geo build --selection $SEL \
  --coastline-out ../../src/ui/coastline_data.h # the compiled-table path
```

The bounding box comes from the selection's `home_lat`/`home_lon` and reach,
not from `config.h`, and the Overpass response is cached per box — so it
refetches when you move and not otherwise.

Size is controlled by `MIN_FEATURE_KM`, not by `SIMPLIFY_M`. Simplification
cannot reduce a two-point line, and estuaries contain thousands of tiny
saltmarsh rings, so tightening the tolerance alone barely helps: filtering
to features ≥2km is what takes 143KB down to 12KB, and it discards exactly
the detail that is sub-pixel at every range.

**Overpass has one endpoint here and no retry**, and it is only reached on a
cache miss — that is, precisely when relocating. A mirror once answered an
English bounding box with a valid, empty, 272-byte result, which would have
cached a coastline-free blob at a coastal site with nothing to show for it.
Any retry logic added here has to check the element count, not just that the
response parses.

### Site application (receiver-side, required)

`tools/boxradar-site/` installs on the **receiver Pi**, not the display and
not a separate server. Two services:

**The display service, `:8081`** — stdlib-only, so it needs no venv and no pip
on a Debian Pi:

- `GET /contacts?lat=&lon=&n=` — the traffic feed, as fixed-size binary
  records already filtered, range-sorted and capped. **Required**: the display
  has no JSON fallback, by design. It reads `aircraft.json` over the loopback,
  so readsb and tar1090 are untouched. Optional `&amin=&amax=` restrict it to
  an altitude band and `&mlat=0` drops multilaterated positions; absent means
  no filtering, so an older board is unaffected.
- `GET /metar/<ICAO>` — weather, fetched from aviationweather.gov on demand
  and cached per station for 5 minutes. Optional; the strip simply omits it.
- `GET /type/<designator>` — the full aircraft type name, from the tar1090-db
  table already on the Pi, so the board can show `AEROSPATIALE AS-350
  Ecureuil` under the `AS50` it keeps. A general board-to-Pi lookup channel:
  the next thing the board cannot hold is another route rather than another
  design.
- `GET /operator/<code>` — who is behind a callsign, and what they are called
  on the radio. `BAW` is British Airways and SPEEDBIRD; `RRR` is the RAF and
  ASCOT. 6,310 codes, from the operator table tar1090-db ships beside the type
  one, so again there is nothing new to download. The board derives the code
  from the callsign it already holds — but only when that callsign is three
  letters followed by a digit, because a registration like `GBXYZ` would
  otherwise yield `GBX` and resolve confidently to somebody else's airline.
- `GET /board`, `POST /board/wake`, `POST /board/reload-geo` — where the board
  is, ask it to open its settings server, and tell it a new map is up. The
  board announces itself on every contact poll, so no address is ever typed
  in anywhere.

**The configuration UI, `:8082`** — needs Flask, shapely and PyYAML; the
installer reports rather than fails if they are missing, and the display
service runs without them. A six-step wizard for choosing what the map shows,
a publish that lands a new blob and tells the board to reload it in about half
a second, and a **Device page** that reads the board's own NVS, offers the
twenty-six settings as a form, and pushes back only what differs. Nothing
about the board's configuration is stored on the Pi — its NVS stays the single
authority, and a copy here would invert the overlay property the whole design
rests on.

**The Pi has no git checkout.** Deploy from the machine that does:

```bash
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' \
  tools/boxradar-site/ pi@<receiver>:/tmp/boxradar-site-staging/
ssh pi@<receiver> 'cd /tmp/boxradar-site-staging && sudo ./install.sh'
```

Re-running `install.sh` is the upgrade path: it keeps `config.json`, the
selection and the published blob. Worth running the suite on the Pi first —
it has older Flask and shapely than the devShell:

```bash
ssh pi@<receiver> 'cd /tmp/boxradar-site-staging && \
  python3 -m unittest discover -s tests -t .'
# test_receiver_* fail there: they test tools/receiver-install, which the
# staging directory does not contain
```

Any ICAO can be asked for — there is no station list to configure. The one
thing the Pi still needs per airfield is runway **true** headings, in
`/etc/boxradar-site/config.json`, because that is published data the request
cannot carry. A station with no entry there still returns wind, cloud and
visibility; it just reports no active runway.

Keeping it on the receiver means the whole system stays two devices —
receiver for data, ESP32 for display — which is what makes it portable to
another location. It also avoids TLS on the ESP32: a handshake wants
~40KB of heap against a board whose floor is ~46KB with the render sprite
live.

The Pi normalises the upstream API's loose types (`visib` can be the
string `"6+"`, `wdir` can be `"VRB"`, `wgst` can be null) into fixed
always-present integers, and derives the likely active runway from the
wind. `conf` is 0 below `calm_kt` (7) — at that point wind isn't choosing
the runway and the value is a guess, which the display marks with a `?`.

Cloud shows as `CLEAR` when no layers are reported: upstream reports NCD,
NSC, SKC and CAVOK identically, so the broader word is the honest one.

The cache is what makes an on-demand endpoint safe. The timer this replaced
guaranteed at most one upstream call every 5 minutes; a 300s per-station TTL
reproduces that bound, so the board's 60s poll produces 12 upstream calls an
hour rather than 60. After an upstream failure the proxy backs off for 60s and
serves the last good observation flagged `"stale":1`, because a stale METAR is
far better than none.

Set `DEFAULT_METAR_URL` and `DEFAULT_METAR_STATION` in `config.h` to consume
it. They must agree — the URL's last path segment names the station the
firmware then picks out of the response. Comment out `METAR_ENABLED` and the
whole feature compiles out; the `metaron` setting turns it off at runtime
without a reflash, which is what makes "display problem or feed problem?"
answerable in ten seconds.

### Provisioning a receiver from scratch

`tools/receiver-install/` builds a complete receiver — readsb, tar1090, both
feeders, `boxradar-site` above and the airspace/config UI it shares a Pi
with — from a bare Raspberry Pi OS Lite install:

```bash
cd tools/receiver-install && sudo ./install.sh
```

See [tools/receiver-install/README.md](tools/receiver-install/README.md).
An as-built inventory of the current receiver is in
[docs/receiver-pi.md](docs/receiver-pi.md).

## Relocating

**Three files carry location data**, and one of them has to agree with another
to four decimal places or nothing works at all.

| file | what | in git? |
|---|---|---|
| `include/config.h` | `DEFAULT_HOME_LAT`/`_LON`, `DEFAULT_METAR_STATION`, receiver/METAR/geo URLs, OTA hostname | **no** — gitignored |
| `tools/boxradar-site/boxradar_site/geo/selection.<site>.json` | `home_lat`/`home_lon`, reach, and everything drawn: airspace, airfields, runways, fixes, towns | yes |
| `/etc/boxradar-site/config.json` (on the Pi) | `runways` — stations and runway **true** headings, for the METAR active-runway guess | no — lives on the receiver |

**What gates a relocation is the blob's home, not any header.** A board refuses
any blob whose home differs from its own by more than `GEO_HOME_TOLERANCE_DEG`
(0.0001°, about 11m) — and then has *no map at all*, silently. So the
selection's `home_lat`/`home_lon` must match `config.h` to 4dp. Three decimal
places is 111m, and every fetch the board ever makes is rejected forever, with
nothing to show for it but a line on the status row.

`include/location.h`, `src/ui/airspace_data.h` and `src/ui/coastline_data.h`
are the **superseded** compiled-tables path. Under `MAP_FROM_BLOB` — the
default — `src/ui/map_source.h` compiles them out of the build entirely, so
editing `location.h` changes nothing. They stay in the repo as regenerable
output and a known-good reference one build flag away, and that flag is
deliberately not a runtime setting: carrying both map paths costs ~20KB of
flash for a fallback used once.

Home coordinates stay in the gitignored `config.h` on purpose: airfield data
is published AIP material, but your own position is not, and this repo may be
mirrored somewhere public. The selection file is committed, so it carries the
site's home too — which is a deliberate trade for a repo that is mirrored but
not public, and the reason to think before making it so.

You no longer need to know your local airspace by its YAIXM name. From
`tools/boxradar-site/`:

```bash
SEL=boxradar_site/geo/selection.example.json
python3 -m boxradar_site.geo list    --selection $SEL   # everything in reach
python3 -m boxradar_site.geo suggest --selection $SEL   # a sane starting set
python3 -m boxradar_site.geo build   --selection $SEL --out ../../src/ui/airspace_data.h
```

`list` prints every feature within reach with its on-screen size at the
overview scale, distance and vertex count. `suggest` ticks what the four
default rules would pick and explains what it rejected and why — "DAVENTRY
CTA: 151nm wide, over the 50nm limit". Those rules only ever *suggest*; the
selection file is what gets drawn.

### Worked example: Southend-on-Sea

A second board was built to this recipe — see `selection.southend.json` and the
`southend` env pair in `platformio.ini`.

```c
// include/config.h — a new #elif block beside the existing site
#elif defined(BOXRADAR_SITE_SOUTHEND)
#define DEFAULT_HOME_LAT      51.5714   // 4dp, and it must match the
#define DEFAULT_HOME_LON      0.6956    // selection's home_lat/home_lon
#define DEFAULT_METAR_STATION "EGMC"    // on the field — civil, so the
                                        // inferred runway means something
#define DEFAULT_METAR_URL     "http://receiver.lan:8081/metar/EGMC"
#define DEFAULT_GEO_URL       "http://receiver.lan/site-southend.bin"
#define DEFAULT_OTA_HOSTNAME  "boxradar-southend"
```

```json
// /etc/boxradar-site/config.json on the receiver Pi (headings are TRUE)
{"runways": {"EGMC": [["05", 54], ["23", 234]]}}
```

Then pick the airspace with `geo suggest` rather than typing feature names —
they have to match the source YAML exactly, and the listing is where you find
out what they are. A selected name that no longer exists in the dataset is
reported as a warning rather than silently dropped, so an AIRAC cycle that
renames something is visible. `suggest` refused `CLACTON CTA` for this site:
it is an enroute CTA 126nm wide, well over the 50nm limit, which is the rule
behaving exactly as documented rather than a gap in the data.

Everything else — airfields, runways, fixes, towns — goes in the selection
file and reaches the board in the blob. The two sites are served side by side
from the same Pi as `site.bin` and `site-southend.bin`, so a second board needs
no second receiver.

### Where the coordinates come from

Three different datasets, and the gaps between them are the trap:

- **Airfield ARPs and runway thresholds** —
  [OurAirports](https://davidmegginson.github.io/ourairports-data/)
  `airports.csv` and `runways.csv`. The latter gives both threshold
  coordinates per runway, which is what the centrelines want
- **3-letter VOR/NDB idents** — OurAirports `navaids.csv`
- **5-letter enroute fixes** (ABBOT, LOREL) — *not in OurAirports at all.*
  They come from the NATS eAIP ENR 4.4 significant points table, published
  as `DDMMSS.ssN/DDDMMSS.ssE` and needing conversion
- **Towns** — OSM Nominatim. Take the `town` result, not the first hit:
  querying "Bedford" returns the county centroid, 4nm from the town

### Gotchas

- **Runway headings are TRUE, designators are MAGNETIC.** Don't derive `05`
  into `50`.
- **`MAX_AIRCRAFT` is 32** (`lib/radarcore/aircraft.h`) and the farthest
  contacts beyond that are dropped — by the Pi now, not the board. No longer
  silent: the feed carries the pre-cap total, so the status strip shows a dim
  `+N` whenever the cap is binding, and `feed=` vs `kept=` on the serial log
  says the same thing. Raising it costs 624 bytes of DRAM a slot across four
  stores, so check `minheap=` before you do.
- **The cap saturates continuously** — a real feed runs 54-65 aircraft against
  those 32 slots — which is why the feed filters (`amin`, `amax`, `mlaton`)
  are applied on the Pi, before the sort and the cap, rather than at draw time
  on the board. Behind the cap they would spend all 32 slots and then hide
  most of them, emptying the scope exactly when the sky is busiest. Anything
  else that filters traffic belongs on the same side of the cap.
- **An altitude floor of 0 means no floor.** Barometric altitude reads
  slightly negative at a low airfield on a high-pressure day, so a literal 0
  would hide ground traffic at the shipped setting. The ceiling is literal by
  contrast; the asymmetry is deliberate and documented in `contacts.py`.
- **The scope's ranges are Device-page settings**, not compiled constants —
  `ovnm`, `d1nm`, `d2nm`, `tlnm`, whole nautical miles. The shipped `50` and
  `{10,5}` suit a busy TMA; somewhere rural wants both higher, a GA field
  wants both lower. The compiled defaults live in
  `lib/radarcore/view_ranges.cpp`, not `src/ui/layout.h`, because they have to
  be settable and `layout.h` cannot reach `siteConfig()`. Keeping the overview
  above `tlnm` and every detail range at or below it is what makes the
  datablock degradation match the two view states — nothing enforces it, so a
  configuration that breaks it gets callsign-only datablocks everywhere.
  There are exactly **two** detail levels: the count sizes an array and the
  zoom toggle steps modulo it, so only the values are configurable.
- **`isCommonType()`** (`lib/radarcore/classify.cpp`) is tuned to a London
  short-haul mix. Somewhere with heavy GA or offshore helicopter traffic will
  want a different "ordinary" list, or the amber highlight loses meaning.
- **The airspace dataset is UK-only.** `ahsparrow/airspace` covers Britain;
  the generator will not work abroad.
- **NVS beats `config.h`, permanently and silently.** Once a key has been
  written from the Device page, changing its `DEFAULT_` and reflashing does
  nothing at all. The "use built-in default" tick box on that page is what
  removes the override; `siteConfigClear()` is the blunt alternative and takes
  the WiFi credentials with it.
- **The remaining feature guards need `config.h` in scope.** A missing include
  makes an `#ifdef` compile to nothing — the build succeeds and the feature
  silently doesn't exist, which is worse than a link error. Fewer of these
  than there were: `DRAW_COASTLINE`, `OVERHEAD_PREDICTION`, `NIGHT_BLANKING`
  and `NIGHT_CLOCK` are now settings, and only choose a default. Never write
  `#ifdef COAST_ON` — those names are accessors, and an `#ifdef` on one would
  quietly evaluate false.
- **Per-unit, not per-location:** `LDR_DARK` is calibrated to one board and
  will differ on another — and again once it's behind a case bezel. So is the
  night clock brightness, which at least is a setting (`nduty`) rather than a
  reflash. Panel driver flags in `platformio.ini` are a batch lottery; see
  Known Quirks in SPEC.md.

## Layout

```
include/        config.h (gitignored) — per-board defaults; site_config.h —
                the NVS overlay and the accessors every use site reads
                through; location.h — superseded compiled tables
src/            net task (core 0), UI task (core 1), shared store, night
                mode, status LED, geo store, config server, setup portal
src/ui/         scope, datablocks, palette, status strip, overhead
                readout, touch, layout, map source, generated tables
lib/radarcore/  portable domain logic, unit-tested natively: parse,
                projection, formatting, classification, METAR, overhead
                prediction, geography blob reader, and the runtime holders
                the config layer pushes into (view_ranges, overhead params,
                contact ageing)
test/           native Unity tests for radarcore — 210 cases
tools/          boxradar-site (display service, geography codegen and the
                config UI), receiver-install (provisions a receiver Pi from
                bare OS), metar-feed
docs/           design notes; receiver-pi.md is the as-built inventory
TODO.md         where the work got to, and what is unverified
case.scad       parametric OpenSCAD enclosure (see Case, above)
```
