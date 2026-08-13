# Receiver installer design

**Status: design. Nothing implemented.**

One script that provisions a BOXRADAR receiver from a bare Raspberry Pi OS
Lite install: readsb, tar1090, the ADSBExchange and Flightradar24 feeders, and
the `boxradar-site` / `boxradar-config` services. It runs twice — to rebuild
the existing receiver at 192.0.2.10, and on a new Pi at a second site, in
someone else's hands.

## Goal, and the one it is not

The driver is the same one that produced
[the runtime site configuration design](2026-08-08-runtime-site-config-design.md):
**reproducibility for a second unit at a different site.** That work moved
configuration out of compile-time headers into a Pi application. This work
moves the *receiver itself* out of a hand-configured box and into a script.

The receiver documented in [docs/receiver-pi.md](../../receiver-pi.md) is the
counter-example that motivates this. Nothing on it was hand-compiled — every
component came from an upstream installer — yet it has drifted into a state
nobody could reproduce: a desktop stack on a headless receiver, a cron that
reboots every three hours, a volatile journal that makes the reboots
undebuggable, and the receiver position recorded four different ways.

This is **not** a general-purpose Pi provisioning tool, and not a fleet
management system. Two boxes. Anything that does not serve those two boxes is
out of scope.

## The second operator changes everything

The decisive constraint: **Luke's brother runs the installer himself** on his
own hardware, and debugs it himself if it fails. Every design decision below
falls out of that.

It means prompts must make sense to someone who did not write the system. It
means a failure at stage four must not discard stages one to three. It means
"it didn't work" has to be answerable from one log file. And it means the
script cannot assume any aviation knowledge — which is why runway headings
get derived rather than asked for.

## Measured constraints

Taken from the running receiver on 2026-08-13, not from spec sheets. These
numbers set the hardware floor and belong in preflight.

| Measurement | Value | Consequence |
|---|---|---|
| Whole stack, CPU | 0.40 cores of Cortex-A53 @1.2GHz | Any quad A53 is ample |
| readsb alone | 0.23 cores | The dominant consumer |
| Running set, RSS | 182 MB | Fits anything ≥512 MB |
| **Coastline reduction, peak RSS** | **367 MB** | **Sets the 1 GB floor** |
| FR24 `armhf` binary | `Tag_CPU_arch: v7`, Thumb-2 | **ARMv6 boards cannot feed FR24** |

The 367 MB peak is `json.loads` on a 48 MB Overpass extract (~360k nodes
becoming Python dicts, 274 MB) followed by shapely's `unary_union` (367 MB).
`segments_cached()` means an established site never pays it twice — but a
**new site with a different bbox has no reduced cache and must pay it once**,
which is exactly the second-unit case. 367 MB peak plus 182 MB running
exceeds 512 MB, so a Pi Zero 2 W is out while the configuration UI stays
on-box.

**Target hardware for the second unit: Raspberry Pi 4 Model B, 2 GB.** ARMv6
boards are excluded by FR24 regardless of anything else. Non-Pi boards were
considered and rejected: the Armbian community's own guidance for the Orange
Pi Zero 3 is that the current kernel crashes within hours under SDR load,
which is not acceptable on a box in another house.

## Decisions

| Question | Decision |
|---|---|
| Existing Pi | Reflash the **same** card with Raspberry Pi OS Lite 64-bit |
| Rollback | None. Mitigated by a verified backup and a `dd` card image |
| Second unit | Brother runs the whole installer himself |
| Feeders | Both always installed, not optional |
| FR24 key | Luke pre-creates the account; brother pastes the key at a prompt |
| ADSBExchange uuid | Auto-generated; **restored from backup on reinstall** |
| AirHits | Deleted with the card. Not backed up, not reinstalled |
| Runway headings | Derived from OurAirports `runways.csv` |
| OS scope | Hardening, unattended security upgrades, hostname/mDNS, optional static IP |
| Shape | Thin driver plus numbered idempotent stages |

Assumed already true when the installer runs, per Raspberry Pi Imager
pre-seeding: the box is on wifi and reachable over SSH, and the RTL-SDR is
plugged in. The installer verifies both but configures neither.

## Architecture

```
tools/receiver-install/
  install.sh              driver: preflight, wizard, run stages, stamp progress
  receiver.conf.example   tracked; secrets present but empty
  stages/
    10-preflight.sh       arch, RAM, SDR, net, disk, under-voltage
    20-os.sh              hostname/mDNS, journal, ufw, unattended-upgrades
    30-readsb.sh          readsb + tar1090, generate /etc/default/readsb
    40-feeders.sh         ADSBExchange + FR24
    50-boxradar.sh        existing install.sh, datasets, derived config.json
    60-verify.sh          prove the chain end to end
```

`tools/boxradar-site/install.sh` is **called, not replaced**. It already
handles its own dependency detection, port conflicts, the `boxradar-pub`
group and health polling. Stage 50 wraps it.

### `/etc/boxradar/receiver.conf` — the single source of truth

Mode 0600, root-owned, never in git. Only `receiver.conf.example` is tracked.

```bash
# Identity
HOSTNAME=boxradar               # -> boxradar.local via avahi
# Position — ONE source, fanned out to readsb, ADSBX, MLAT and selection.json
LAT=51.8849826
LON=0.2349914
ALT_FT=348                      # AMSL, required by MLAT
# Radio
GAIN=auto
PPM=0
# Network
STATIC_IP=                      # blank = DHCP
# Weather
METAR_STATION=EGSS
CALM_KT=7
# Feeder identity — restored on reinstall so stats and history survive
ADSBX_USER=example-feeder
ADSBX_UUID=                     # secret
FR24_KEY=                       # secret
```

The wizard writes this once. A re-run reads it back and offers each value for
keep-or-change, so the second run is near-silent. A pre-written file makes the
run non-interactive — guided for the brother, reproducible for Luke, one
script.

**Position unification is a real fix, not tidiness.** The current receiver
records its position four ways, spanning about 15 m:

| Source | Latitude | Longitude |
|---|---|---|
| `/etc/default/readsb` | 51.884911407 | 0.234884137 |
| `/etc/default/adsbexchange` | 51.884982551 | 0.234991408 |
| `selection.json` | 51.8850 | 0.2350 |
| the board's `/contacts` poll | 51.885016 | 0.235027 |

MLAT solves hyperbolae from receiver positions. It is the one consumer for
which the discrepancy is not merely cosmetic.

**Feeder identity is restorable.** `ADSBX_UUID` and `FR24_KEY` tie the
receiver to its existing statistics and MLAT peer reputation. Regenerating
them silently restarts both from zero. Carrying them through the backup into
`receiver.conf` is what makes a reflash a *reinstall* rather than a *new
receiver*, and is a substantive reason the backup step exists.

### Progress stamping

The driver writes `/var/lib/boxradar-install/<stage>.done` on success and
skips stamped stages on re-run. `--force` re-runs everything; `--from 40`
resumes at a chosen stage.

Stamping is an optimisation, not the correctness mechanism. **Every stage is
independently idempotent**: configs are regenerated wholesale rather than
appended to, `apt-get install` converges naturally, and the upstream
installers tolerate re-running. A stamp that lies — a card pulled mid-write —
therefore costs repeated work, never corruption.

## Stages

**10-preflight** refuses before touching anything. `aarch64` required, printing
the FR24 ARMv7 reason so an ARMv6 board gets an explanation rather than a
`SIGILL` three stages later. RAM ≥ 1 GB, quoting the 367 MB peak. An RTL28xx
in `lsusb`. Debian, GitHub and Overpass reachable. ≥ 8 GB free. And
`vcgencmd get_throttled`, warning on under-voltage — a check that exists
because it would have caught the existing box's `0x50005` on day one.

**20-os** sets hostname and mDNS so `boxradar.local` resolves and nobody hunts
a DHCP table; `journald` to `Storage=persistent`; `ufw` allowing
22/80/8081/8082/8754, plus 8504 only if tar1090's second instance is
configured; `unattended-upgrades` restricted to the security pocket; optional
static IP. Wifi power-save is disabled by a
`/etc/NetworkManager/conf.d/` drop-in rather than the existing
`*/5 * * * * iwconfig` cron — NetworkManager owns the interface, so a drop-in
holds the setting instead of stamping on it every five minutes. Conspicuously
absent: any reboot cron.

**30-readsb** runs wiedehopf's installer, which builds from source and takes
roughly 10–15 minutes on a Pi 4; the stage says so before starting. Then
`/etc/default/readsb` is generated from `receiver.conf`. The load-bearing
detail is `--net-bi-port 30004,30104`: without 30104, `mlat-client` has
nowhere to return results and MLAT silently disappears. Stage 60 asserts it.

**40-feeders** runs the ADSBExchange installer, restores `ADSBX_UUID` when
present, and writes `/etc/default/adsbexchange` from the same position as
readsb. FR24 comes from its existing apt repo, with `FR24_KEY` written into
`/etc/fr24feed.ini`. Ordering matters: readsb must exist first, because both
feeder installers detect and reconfigure whatever decoder is already present.

**50-boxradar** apt-installs `python3-flask`, `python3-shapely` and
`python3-yaml`, calls `tools/boxradar-site/install.sh` unchanged, then fetches
the OurAirports datasets by calling `datasets.fetch()` directly — there is no
CLI, but it is a clean function. With the datasets present it derives
`/etc/boxradar-site/config.json` from `METAR_STATION`, and seeds
`selection.json` with the home position so the configuration UI opens centred
on the site.

**60-verify** proves the chain rather than announcing success: readsb messages
climbing and `total.position_count_by_type` non-zero; `/healthz` on both
services; `/metar/<station>` returning a real observation; FR24
`feed_status: connected`; ADSBExchange connected. MLAT warns rather than
fails, because peers take minutes to synchronise. It closes by printing the
URLs.

> `aircraft_count_by_type` is absent from this readsb build and reads as
> `None`. `total.position_count_by_type` is cumulative since start and is the
> only field that answers "is this working".

## Deriving runway headings

`/etc/boxradar-site/config.json` currently carries hand-written designator and
**true** heading pairs, consumed by `metar.pick_runway()` to choose the active
runway from wind direction. Sourcing those for an unfamiliar airport means
reading the AIP, and confusing magnetic for true yields a wrong answer with no
visible error. That is not a reasonable thing to ask of a second operator.

`datasets.runways(cache_dir, idents)` already returns exactly what is needed:
filtered by ICAO, closed runways excluded, both threshold coordinates, and
`le_ident`/`he_ident` designators. The heading is the bearing between
thresholds; the reciprocal is the other end.

This follows a rule the codebase already committed to. From that function's
docstring:

> the axis is taken from the two points rather than from a published heading,
> because location.h records that published headings sometimes disagree with
> their own threshold coordinates by more than a degree.

The hand-written `config.json` is the last place still trusting published
headings. Deriving it is consistency, not scope creep — and the existing
hand-entered values for EGSS, EGGW and EGMC become a regression test with a
known-good answer.

This is the one change outside `tools/receiver-install/`.

## Failure handling

Stages run under `set -euo pipefail` with an `ERR` trap reporting stage, line
and failing command, exiting without stamping.

```
stage 40 (feeders) failed at line 62: fr24feed --validate-config
stages 10-30 are complete and will be skipped.
fix, then re-run:  sudo ./install.sh
full log:          /var/log/boxradar-install.log
```

Everything is `tee`d to `/var/log/boxradar-install.log` with secrets redacted.
When the answer to "it didn't work" is a file rather than a recollection,
supporting a box in another house becomes tractable.

## Testing

Three layers; one needs hardware.

**Unit tests** in the existing `tools/boxradar-site/tests/`, pytest as
elsewhere. Runway derivation asserts EGSS, EGGW and EGMC against the values
already in `config.json`.

**Config rendering tests.** Each stage's config generation is a pure function
of `receiver.conf`. Given a fixture, rendering `/etc/default/readsb`,
`/etc/default/adsbexchange` and `/etc/fr24feed.ini` and asserting on the
output needs no Pi. `shellcheck` covers every stage script.

**`--check` mode** runs preflight and the wizard, renders every config to a
temporary directory, and **diffs against what is live on the box**. Run on the
current receiver *before* wiping it, this proves the generation logic against
a known-good system while that system still exists — which is how a decision
with no rollback becomes a checkable one.

End to end is only provable on hardware. The reflash is that test, and
`60-verify.sh` is what makes it a test rather than a hope.

## Order of work

1. Runway derivation plus its regression test, on the current box. Independent
   of everything else and verifiable immediately.
2. The driver, `receiver.conf`, the wizard and `--check`.
3. Stages, in numeric order.
4. Run `--check` against the live receiver and reconcile every difference.
5. Back up: `receiver.conf` values, `ADSBX_UUID`, `FR24_KEY`, `selection.json`,
   `site.bin`, plus a full `dd` image of the card to ZFS. **Verify the backup
   restores before erasing anything.**
6. Reflash and rebuild the existing receiver.
7. Second unit on the Pi 4 2 GB.

## Out of scope

Map authoring — the installer leaves the configuration UI running and empty,
because which controlled airspace matters locally is a human judgement and
guessing it in an unattended script would be worse than leaving it blank. The
ESP32 display. Anything on the home server. And the backup in step 5 is a documented
manual step: a script that erases things should not also be the script trusted
to safeguard them.
