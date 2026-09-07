# Receiver installer

Provisions a BOXRADAR receiver from a bare Raspberry Pi OS Lite install:
readsb, tar1090, the aircraft database and its weekly refresh timer, the
ADSBExchange and Flightradar24 feeders (and adsb.lol and adsb.fi, if you want
them), and the
`boxradar-site` / `boxradar-config` services.

Runs on the **receiver Pi**. Not the display, not a server.

## Requirements

- Raspberry Pi with **64-bit** Raspberry Pi OS Lite (Bookworm), **≥1GB RAM**
  (2GB recommended — the first coastline build for a new area peaks at
  367MB), **≥8GB free disk**
- An RTL-SDR dongle, connected
- Internet access — preflight checks that `deb.debian.org`, `github.com`,
  `overpass-api.de`, `www.adsbexchange.com`, `repo-feed.flightradar24.com`,
  `davidmegginson.github.io`, `download.geonames.org` and
  `aviationweather.gov` all resolve (adsb.lol, if enabled, additionally needs
  `feed.adsb.lol` and `re-api.adsb.lol`; adsb.fi needs `feed.adsb.fi` and
  `opendata.adsb.fi`)
- Wifi already configured and SSH reachable — use Raspberry Pi Imager's
  advanced options to pre-seed both before first boot
- A Flightradar24 sharing key

ARMv6 boards (Pi Zero W, Pi 1) **cannot** be used: FR24's armhf binary is
built for ARMv7 and will not execute. The installer refuses before touching
anything if any of the above isn't met.

## Use

```bash
git clone <repo> && cd boxradar/tools/receiver-install
sudo ./install.sh
```

The first run asks for the site's position, aerial height, nearest METAR
airport and feeder credentials, writes them to `/etc/boxradar/receiver.conf`
(mode 0600 — it carries the FR24 key), then installs everything. Expect
20–30 minutes, most of it readsb compiling from source.

Re-running shows each existing answer in brackets — press enter to keep it,
or type a new value.

| Flag | Effect |
|---|---|
| `--check` | Render every config and diff against what is live. Changes nothing. |
| `--from N` | Resume at stage N |
| `--force` | Re-run stages already marked complete |
| `--no-wizard` | Use `receiver.conf` as-is, prompt for nothing |
| `--help` | Usage text |

(`--check` renders `/etc/fr24feed.ini` too, but doesn't diff it — it's the
one file that carries a live secret.)

If a stage fails, fix the cause and re-run — completed stages keep their
stamp in `/var/lib/boxradar-install/` and are skipped. The failure message
names the stage and exit code. The full log is at
`/var/log/boxradar-install.log`, with secrets redacted; it is the right
thing to send when asking for help.

## After installing

The receiver works immediately, but **the display shows no map** until one is
published. Open `http://<box>:8082/`, choose the controlled airspace that
matters locally, and publish. That step needs local knowledge, so it is not
automated.

## Rebuilding an existing receiver

Restore `ADSBX_UUID`, `ADSBLOL_UUID`, `ADSBFI_UUID` and `FR24_KEY` into
`receiver.conf` from
the old box. They carry your statistics and MLAT peer reputation; without them
the rebuild registers as a brand-new receiver on each network.

On a genuinely new box, leave both uuids blank — the feeder installers generate
them, and `install.sh` writes them straight back into `receiver.conf` for you.
Keep that file (or back up the values) and the *next* rebuild already has them.

## Notes

- `/etc/fr24feed.ini` is created `0640 root:fr24`, not world-readable:
  fr24feed's systemd unit runs as user `fr24`, not root, so nothing wider is
  needed.
- Every generated file (`/etc/default/readsb`, `/etc/default/adsbexchange`,
  `/etc/default/adsblol`, `/etc/fr24feed.ini`) is rewritten wholesale on every
  run. Hand edits to them are lost the next time `install.sh` runs — edit
  `receiver.conf` instead.

## adsb.lol

Off unless `ADSBLOL_USER` is set in `receiver.conf`. Two things to know before
turning it on:

- **It installs chrony, which replaces `systemd-timesyncd`.** Their installer
  would do this silently; stage 40 does it up front instead. chrony is the
  better clock for MLAT, but it is a system-wide change.
- **Feeding grants [re-api](https://re-api.adsb.lol) access** — the whole
  network's unfiltered readsb API, including MLAT-only aircraft your own
  aerial cannot see, and readsb's derived fields (`ias`/`tas`/`mach`, and
  `wd`/`ws` winds aloft). It authorises by the station's **source IP**, not a
  key, so any host sharing the receiver's public address can query it:

  ```
  curl 'https://re-api.adsb.lol/?circle=<lat>,<lon>,<nm>'
  ```

adsb.lol's ports are deliberately clear of ADSBExchange's (31420/31421/31422
against 31003/30154/30157), so both feeders and both MLAT clients run together
on one receiver. Only readsb's `30104` is shared, which is what it is for.

## adsb.fi

Off unless `ADSBFI_USER` is set. The same upstream scripts a third time, so
the same chrony note applies — whichever of adsb.lol and adsb.fi is enabled
installs it, and enabling both installs it once.

- **Feeding opens [`/v2/snapshot`](https://opendata.adsb.fi/api/v2/snapshot)**
  — every aircraft the network can see, refreshed twice a minute, source-IP
  authorised exactly as re-api is:

  ```
  curl 'https://opendata.adsb.fi/api/v2/snapshot'
  ```

  It is rate limited to **one request per 30 seconds**, and a rejected request
  counts against that limit, so do not poll it while waiting for access to
  come up. The public endpoints (1 request/second) need no feed at all:

  ```
  curl 'https://opendata.adsb.fi/api/v2/lat/<lat>/lon/<lon>/dist/<nm>'
  ```

**Their scripts still ship one of ADSBExchange's ports.** adsb.fi forked the
feedclient before upstream's "avoid listen port overlap with ax scripts"
commit, so their `configure.sh` writes `RESULTS3=30157` — which
`adsbexchange-mlat` already listens on. `lib/render.sh` writes `30170`
instead, and that is the one value in `/etc/default/adsbfi` that is not what
upstream would write. Running their wizard by hand would put the collision
back; a bind failure there does not stop the feed, so the box would look
healthy with one MLAT results path dead.
