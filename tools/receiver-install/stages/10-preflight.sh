#!/usr/bin/env bash
# Refuse before anything is touched.
#
# Every check here exists because its absence produces a confusing failure
# later. The architecture check in particular: an ARMv6 board installs FR24's
# armhf package cleanly and then dies with SIGILL on first run, because the
# binary is built Tag_CPU_arch v7. Saying so here beats debugging that.
set -euo pipefail

fail() { echo "preflight: $*" >&2; exit 1; }
warn() { echo "preflight: WARNING: $*"; }

arch="$(uname -m)"
[[ $arch == aarch64 ]] || fail \
  "architecture is $arch, needs aarch64.
   Flightradar24's armhf binary is built for ARMv7 (Tag_CPU_arch v7), so
   ARMv6 boards such as the Pi Zero W cannot feed it at all. Use a 64-bit
   Raspberry Pi OS on a Pi 3, Pi 4 or Pi 5."

mem_mb=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 ))
(( mem_mb >= 900 )) || fail \
  "only ${mem_mb}MB RAM, needs 1GB.
   Reducing a fresh coastline peaks at 367MB on top of ~182MB of running
   services, which does not fit in 512MB."
(( mem_mb >= 1800 )) || warn \
  "${mem_mb}MB RAM. Enough, but 2GB is comfortable — the first coastline
   build for a new area peaks at 367MB."

# Captured first, then matched, not `lsusb | grep -qiE ...`: grep -q exits
# the instant it matches, closing the pipe while lsusb may still be writing
# later devices. Under pipefail that SIGPIPE reports as pipeline failure,
# not grep's — so this would fail preflight on a box with *more* USB
# devices attached, precisely when the dongle is present. Reliable today
# only because lsusb's output is short enough to finish before grep -q
# gets a chance to close the pipe; not guaranteed on a box with several USB
# devices on the same hub. `|| true` belongs on the capture — lsusb itself
# is not expected to fail, but a failure there should read as "no SDR
# found", not a raw script abort.
usb_devices="$(lsusb 2>/dev/null || true)"
grep -qiE 'RTL2838|RTL2832|Realtek.*DVB-T' <<<"$usb_devices" || fail \
  "no RTL-SDR found in lsusb. Plug the dongle in and re-run."

hosts=(deb.debian.org github.com overpass-api.de
       www.adsbexchange.com repo-feed.flightradar24.com
       davidmegginson.github.io download.geonames.org
       aviationweather.gov)
# Only when this site actually feeds adsb.lol. Checking them unconditionally
# would fail a perfectly good install for a network the operator never asked
# to use.
[[ -n ${ADSBLOL_USER:-} ]] && hosts+=(feed.adsb.lol re-api.adsb.lol)
for host in "${hosts[@]}"; do
  getent hosts "$host" >/dev/null || fail "cannot resolve $host — no internet?"
done

free_gb=$(( $(df --output=avail -k / | tail -1) / 1024 / 1024 ))
(( free_gb >= 8 )) || fail "only ${free_gb}GB free on /, needs 8GB"

if command -v vcgencmd >/dev/null 2>&1; then
  throttled="$(vcgencmd get_throttled 2>/dev/null || echo throttled=0x0)"
  value="${throttled#throttled=}"
  if (( (value & 0x1) || (value & 0x4) )); then
    warn "the board is under-volting right now ($throttled).
   This is a power supply or cable problem, not a software one. It causes
   dropped samples and unexplained reboots. Fix it before trusting anything
   this receiver reports."
  elif (( value & 0x50000 )); then
    warn "under-voltage has occurred since boot ($throttled). Watch the PSU."
  fi
fi

if systemctl is-active --quiet lightdm 2>/dev/null; then
  warn "a desktop session is running. This is meant for Raspberry Pi OS Lite;
   the desktop costs roughly a third of RAM on a 1GB board."
fi

echo "preflight: ${arch}, ${mem_mb}MB RAM, ${free_gb}GB free, SDR present"
