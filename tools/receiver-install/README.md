# Receiver installer

Provisions a BOXRADAR receiver from a bare Raspberry Pi OS Lite install:
readsb, tar1090, the ADSBExchange and Flightradar24 feeders, and the
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
  `aviationweather.gov` all resolve
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

Restore `ADSBX_UUID` and `FR24_KEY` into `receiver.conf` from the old box.
They carry your statistics and MLAT peer reputation; without them the rebuild
registers as a brand-new receiver on both networks.

On a genuinely new box, leave `ADSBX_UUID` blank — the ADSBExchange installer
generates one, and `install.sh` writes it straight back into `receiver.conf`
for you. Keep that file (or back up the value) and the *next* rebuild already
has it.

## Notes

- `/etc/fr24feed.ini` is created `0640 root:fr24`, not world-readable:
  fr24feed's systemd unit runs as user `fr24`, not root, so nothing wider is
  needed.
- Every generated file (`/etc/default/readsb`, `/etc/default/adsbexchange`,
  `/etc/fr24feed.ini`) is rewritten wholesale on every run. Hand edits to
  them are lost the next time `install.sh` runs — edit `receiver.conf`
  instead.
