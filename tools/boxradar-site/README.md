# boxradar-site

The Pi-side application for BOXRADAR. Runs on the **receiver** Pi — the box
running readsb/tar1090 — not on the display and not on a separate server.

Three things live here:

- the **display service** (`boxradar_site`) — the contact feed and METAR proxy
  the board polls, on **:8081**
- the **geography generator** (`boxradar_site.geo`) — codegen for the map
- the **configuration UI** (`boxradar_config`) — a browser UI for picking
  geography and publishing the map, on **:8082**

They have deliberately different dependencies — see Dependencies below. The
display service is stdlib-only so it can run on a Debian Pi with no venv; the
generator needs shapely, and the UI needs Flask on top of that.

**Two systemd units, not one.** The display service is what the board polls
about every two seconds, and it should not gain shapely, Flask, or a reason to
restart when the configuration UI is touched. The split costs one extra unit
file and buys a feed that config-UI work cannot break.

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

Re-run it to upgrade; it restarts the services and keeps an existing
`config.json`. The configuration UI is installed and enabled only if Flask,
shapely and yaml are all present — a receiver that only wants weather still
works without them.

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
| display service (`boxradar_site/*.py`) | stdlib only | runs as a systemd unit on a Debian Pi where PEP 668 blocks pip and a venv would be extra machinery |
| geography generator (`boxradar_site/geo/*`) | PyYAML, shapely | polygon union and simplification have no stdlib equivalent |
| configuration UI (`boxradar_config/*`) | Flask, plus the above | a real form-and-table UI over templates, rather than hand-rolled string building |

The rule is **"nothing comes from pip"**, not "nothing but stdlib". Debian's
Python is externally managed under PEP 668, so pip and a venv are both out —
but apt is outside PEP 668's scope, which is why all three of these are
acceptable:

```bash
sudo apt install python3-shapely python3-yaml python3-flask
```

`tests/test_dependency_boundary.py` enforces both halves: that the display
service imports nothing outside the standard library, and that no module
anywhere imports a package that is not on that apt list.

Note the version spread, which is the same shape as the shapely one: bookworm
has Flask 2.2.2 and this repo's devShell has 3.x, so `boxradar_config` stays on
APIs common to both.

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

# the binary blob, which is what the board draws from
python3 -m boxradar_site.geo build --selection $SEL --blob site.bin --coastline

# C headers, the superseded path — kept because they cost nothing and preserve
# a known-good map one build flag away (MAP_FROM_BLOB in config.h)
python3 -m boxradar_site.geo build --selection $SEL \
  --out ../../src/ui/airspace_data.h \
  --coastline-out ../../src/ui/coastline_data.h
```

`list` prints every airspace feature whose geometry intersects the box, with
its on-screen size at the 50nm overview, distance from home and vertex count —
so you never need to know your local CTRs by their YAIXM names. `suggest` ticks
what the four measured rules would pick and says why it rejected the rest.
Those rules only ever suggest; `$SEL` is what gets drawn.

Airspace is selected by rule-assisted picking, and **point references are
still picked rather than filtered** — the configuration UI offers what is in
the box and you choose, because a marker is cheap orientation while a
centreline is a strong claim about where traffic goes. The bounding box is a
search scope, not a selection.

Adding `--fetch` pulls the latest YAIXM release first. A selected feature name
that no longer exists in the dataset is reported as a warning rather than
silently dropped, so an AIRAC cycle that renames something is visible.

The blob format is specified in `SPEC.md`.

## Configuration UI

`boxradar_config` is the browser front end for all of the above, so picking
airspace no longer means editing a JSON file by hand. On the Pi it is
`boxradar-config.service` on **:8082**; run it locally with:

```bash
BOXRADAR_CONFIG_SELECTION=/tmp/site/selection.json \
BOXRADAR_CONFIG_CACHE=~/.cache/boxradar-airspace \
BOXRADAR_CONFIG_BLOB=/tmp/site/site.bin \
python3 -m boxradar_config --host 127.0.0.1 --port 8099
```

| page | does |
|---|---|
| `/site` | home latitude/longitude and the search reach |
| `/airspace` | the catalog as a table, tick to select, Suggest, Publish |
| `/airfields` | search by ICAO, name or town; centrelines per runway |
| `/fixes` | navaids and enroute fixes in one list, plus eAIP import |
| `/towns` | a map to click, ranked by population, with editable labels |
| `/datasets` | what is downloaded and how old it is |
| `/healthz` | selection, source, blob and dataset ages |

### Where the point references come from

| picker | source | note |
|---|---|---|
| airfields | OurAirports `airports.csv` | large and medium by default; small on request. A field with no ICAO cannot be drawn, since the label *is* the ICAO |
| centrelines | OurAirports `runways.csv` | both thresholds or nothing — the axis is the two points, never a published heading, which is magnetic and rounded to ten degrees |
| fixes | OurAirports `navaids.csv` + eAIP ENR 4.4 | 3-letter navaids download; the ~1000 5-letter RNAV points ship, extracted by `tools_import_eaip_fixes.py` |
| towns | GeoNames `GB.txt` | population ranks and never gates; the label is yours to choose |

Everything is scoped to the search box before it is offered, which is a
correctness requirement rather than a convenience: OurAirports idents are not
globally unique. `BKY` is Barkway in Hertfordshire **and** Bouaké in Côte
d'Ivoire, so an unscoped search by ident can put a West African VOR on an
Essex map.

Regenerating the enroute fix table:

```bash
python3 tools_import_eaip_fixes.py            # current AIRAC cycle
python3 tools_import_eaip_fixes.py --check    # verify, write nothing
```

It refuses to write unless LOREL and ABBOT come out matching the values
curated by hand in `include/location.h`, and refuses on a suspiciously short
table. A layout change on the published page should fail loudly, not quietly
produce a shorter map.

Four paths, all overridable by environment variable so the systemd unit is the
one place they are stated:

| variable | default | what |
|---|---|---|
| `BOXRADAR_CONFIG_SELECTION` | `/var/lib/boxradar-config/selection.json` | the selection the UI owns |
| `BOXRADAR_CONFIG_CACHE` | `/var/cache/boxradar-config` | YAIXM checkout and coastline |
| `BOXRADAR_CONFIG_BLOB` | `/var/www/html/site.bin` | where lighttpd serves it from |
| `BOXRADAR_CONFIG_PORT` | `8082` | |

The selection lives under `/var/lib` rather than `/etc` because it stopped
being a file a human edits the moment this UI existed. `StateDirectory=` and
`CacheDirectory=` in the unit give the `DynamicUser` service writable
directories without a chown in the installer; `/var/www/html` is the one path
outside them it is allowed to write.

Three things worth knowing:

- **Suggest never saves.** It pre-ticks what the rules would pick and prints
  the reason it rejected everything else. Nothing is stored until Save.
- **A selection naming a feature that no longer exists publishes nothing.**
  It would otherwise produce a perfectly valid blob with a hole in it, and
  neither the CRC nor the board could tell that from a site with no airspace
  there. Publish is disabled and the names are listed.
- **Saving a tick rewrites the whole file**, so it carries the curated
  airfields, runway centrelines, fixes and towns through untouched. Envelope
  grouping is preserved too — a tick on a feature that is not already in a
  group makes it a group of its own, and envelopes are still edited in the
  file.

There is no authentication, deliberately. Nothing else on this Pi has any —
the display service and tar1090 are both open on the LAN — so adding it here
alone would be security theatre. Revisit if the Pi ever faces the internet.

Flask's own development server is what runs it. This is a single-user tool on
a LAN, touched when a site is set up and otherwise idle; gunicorn would be a
second dependency and a second thing to configure for no benefit.

### Publishing permissions

The service runs as a `DynamicUser`, which has no stable identity to chown
anything to, and it has to write `site.bin` into a document root owned by
root and read by lighttpd as `www-data`. Three separate things have to line
up, and each one fails differently:

- `ReadWritePaths=/var/www/html` in the unit lifts systemd's read-only mount.
  It does **not** change POSIX ownership, which is a distinction easy to miss:
  the service still gets `EACCES` without the next line.
- `install.sh` creates a system group `boxradar-pub`, gives the document root
  `2775` and that group, and the unit joins it with `SupplementaryGroups=`.
  The setgid bit means published files inherit the group rather than depending
  on whichever dynamic UID happened to write them.
- The blob is written `0644` explicitly. `tempfile.mkstemp` creates at `0600`,
  so an atomic write that did not chmod would publish a file lighttpd cannot
  read — the board would get a 403 on its geography fetch and fall back to its
  cache, with nothing in the Pi's logs to say why.

### First deployment at a site that already has a map

The UI starts from an empty selection. If a `site.bin` is already published,
seed the selection that built it before touching any picker, or the first
Publish replaces a working map with an empty one:

```bash
sudo systemctl stop boxradar-config
sudo install -m 0644 boxradar_site/geo/selection.example.json \
  /var/lib/private/boxradar-config/selection.json
sudo chown -R "$(sudo stat -c %u /var/lib/private/boxradar-config)" \
  /var/lib/private/boxradar-config
sudo systemctl start boxradar-config
```
