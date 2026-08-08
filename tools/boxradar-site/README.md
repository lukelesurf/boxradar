# boxradar-site

The Pi-side application for BOXRADAR. Runs on the **receiver** Pi — the box
running readsb/tar1090 — not on the display and not on a separate server.

Two things live here: the **METAR proxy**, a long-running service the display
polls, and the **geography generator**, offline codegen you run when relocating
or picking up a new AIRAC cycle. A later phase adds the site configuration UI;
see `docs/superpowers/specs/2026-08-08-runtime-site-config-design.md`.

They have deliberately different dependencies — see Dependencies below. The
service is stdlib-only so it can run on a Debian Pi with no venv; only the
generator needs shapely.

## Why a proxy

Its job is terminating TLS off the device. An ESP32 TLS handshake wants ~40KB
of heap against a board whose floor is ~43KB with the render sprite live, so
`https://aviationweather.gov` is not reachable from the firmware at all.

The proxy replaces a systemd timer that fetched three hardcoded stations
every 5 minutes and wrote `/var/www/html/metar.json`. Any ICAO can now be
asked for, and the station list stops being configuration on both sides.

## Endpoints

| route | returns |
|---|---|
| `GET /metar/EGSS` | one station |
| `GET /metar/EGSS,EGGW` | several, in one upstream call |
| `GET /healthz` | `{"ok":true,"version":"..."}` |

`400` for anything that is not one to eight four-letter ICAO codes. `503`
when there is no observation cached and none available upstream — the
firmware keeps its last good reading on a non-200, whereas an empty
`stations` array would look like a successful publish with no weather in it.

Note that a well-formed but non-existent code (`ZZZZ`) gets a `503`, not a
`400`: the shape was fine, there is simply nothing to report.

## Caching

The timer this replaced bounded upstream load at one call per 5 minutes no
matter what the board did. The cache reproduces that bound: a 300s TTL per
station, so a board polling every 60s produces 12 upstream calls an hour
rather than 60. A 60s backoff after a failure stops a polling board turning a
broken upstream into a retry storm. Stale observations are served rather than
withheld and are flagged with `"stale":1`; `t` stays the wall-clock time of
the upstream fetch, so it never falsely refreshes.

Every real upstream call logs a line, because request logs alone cannot tell
you whether the cache is working:

```
upstream: fetched EGSS -> 1 obs in 214ms
```

TTL and backoff are measured on `time.monotonic()`, not the wall clock. A Pi
has no RTC, so it boots with a wildly wrong time and NTP then steps it — a
wall-clock TTL would either flush the whole cache on that step or freeze it
until the clock caught up. The wall clock is recorded only for the envelope's
`t`, which has to be a real timestamp.

## Install

```bash
ssh pi@<receiver>
cd /path/to/boxradar/tools/boxradar-site
sudo ./install.sh
```

Re-run it to upgrade; it restarts the service and keeps an existing
`config.json`.

Runway headings live in `/etc/boxradar-site/config.json` and are **TRUE, not
magnetic** — designators are magnetic and rounded to 10 degrees, so 05 is not
050. A station with no runway table still returns wind, cloud and visibility;
it just gets `"rwy":""` and `"conf":0`.

```json
{
  "runways": {
    "EGSS": [["04", 43], ["22", 223]]
  },
  "calm_kt": 7
}
```

A malformed entry is dropped rather than failing the file, so a typo in one
airfield does not cost the others their runway recommendation.

## Tests

From the repo root:

```bash
python3 -m unittest discover -s tools/boxradar-site/tests -t tools/boxradar-site -v
```

stdlib only — no venv, no pip. Debian's Python is externally managed
(PEP 668) and this must stay installable on a receiver box without either.
`upstream.py` is the only module that opens a socket, which is what lets the
cache be tested against a fake fetcher and a fake clock.

## Dependencies

Two profiles in one package, and the split is enforced by
`tests/test_dependency_boundary.py`:

| part | needs | why |
|---|---|---|
| METAR service (`boxradar_site/*.py`) | stdlib only | runs as a systemd unit on a Debian Pi where PEP 668 blocks pip and a venv would be extra machinery |
| geography generator (`boxradar_site/geo/*`) | PyYAML, shapely | polygon union and simplification have no stdlib equivalent |

Install the generator's dependencies from apt, which is outside PEP 668's
scope:

```bash
sudo apt install python3-shapely python3-yaml
```

The boundary is checked by source inspection rather than by import, because
importing proves nothing on a dev machine that already has shapely.

The Pi has shapely 1.8, this repo's devShell has 2.x. Different GEOS, so
generated vertices can differ in the last decimal and occasionally in count.
Geometry tests compare with tolerance for exactly that reason.

## Geography

Airspace, coastline and point references for one site. From this directory:

```bash
SEL=boxradar_site/geo/selection.example.json

python3 -m boxradar_site.geo list    --selection $SEL           # what's in reach
python3 -m boxradar_site.geo list    --selection $SEL --kind CTR
python3 -m boxradar_site.geo suggest --selection $SEL           # a starting set

# C headers, which is what the firmware currently reads
python3 -m boxradar_site.geo build --selection $SEL \
  --out ../../src/ui/airspace_data.h \
  --coastline-out ../../src/ui/coastline_data.h

# the binary blob, which nothing reads yet
python3 -m boxradar_site.geo build --selection $SEL --blob site.bin --coastline
```

`list` prints every airspace feature whose geometry intersects the box, with
its on-screen size at the 50nm overview, distance from home and vertex count —
so you never need to know your local CTRs by their YAIXM names. `suggest` ticks
what the four measured rules would pick and says why it rejected the rest.
Those rules only ever suggest; `$SEL` is what gets drawn.

Airspace is selected by rule-assisted picking. **Point references are not** —
airfields, runway centrelines, fixes and towns are curated by hand in the
selection file, because a marker is cheap orientation while a centreline is a
strong claim about where traffic goes. The bounding box is a search scope, not
a selection. Pickers over OurAirports and GeoNames are a later phase.

Adding `--fetch` pulls the latest YAIXM release first. A selected feature name
that no longer exists in the dataset is reported as a warning rather than
silently dropped, so an AIRAC cycle that renames something is visible.

The blob format is specified in `SPEC.md`. It is written and tested but not yet
consumed on device — the firmware still reads the generated C headers.
