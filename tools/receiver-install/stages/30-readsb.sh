#!/usr/bin/env bash
# readsb and tar1090, from wiedehopf's installers.
#
# readsb is a source build and takes 10-15 minutes on a Pi 4 — the box looks
# idle for a long stretch in the middle of this stage, which is normal.
#
# Ordering: this must run before the feeders. Both feeder installers detect
# and reconfigure whatever decoder is already present, so installing them
# first means they configure against nothing.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib/render.sh
# shellcheck disable=SC1091
source "$SRC_DIR/lib/render.sh"

# curl -sL alone has two ways to hide a broken download: without -f it takes
# a GitHub 404 body as "success" and hands it to bash to execute as a script,
# and if the connection fails outright curl emits nothing at all, so
# `bash -c "$(curl ...)"` degrades to `bash -c ""` — exit 0, does nothing.
# Either way the box looks idle for the 10-15 minutes this stage says is
# normal, then fails minutes later at `systemctl restart readsb` with "unit
# not found", which does not say why. Fetching to a variable first turns
# that into an immediate, specific error.
fetch_and_run() {
  local url=$1 label=$2 script
  if ! script="$(curl -sfL "$url")"; then
    echo "failed to download the $label installer from $url" >&2
    echo "check network access to github.com and re-run this stage" >&2
    exit 1
  fi
  bash -c "$script"
}

if ! command -v readsb >/dev/null 2>&1; then
  echo "installing readsb (source build, 10-15 min on a Pi 4)"
  fetch_and_run "https://github.com/wiedehopf/adsb-scripts/raw/master/readsb-install.sh" readsb
else
  echo "readsb already present: $(readsb --version 2>&1 | head -1)"
fi

if [[ ! -d /usr/local/share/tar1090 ]]; then
  echo "installing tar1090"
  fetch_and_run "https://github.com/wiedehopf/tar1090/raw/master/install.sh" tar1090
else
  echo "tar1090 already present"
fi

# --- the aircraft database --------------------------------------------------
# readsb learns nothing about an aircraft from the air beyond its ICAO hex.
# The type designator (A320), the registration (G-EUYB) and the operator are
# all lookups against a table loaded once at startup — --db-file in
# JSON_OPTIONS below. Without it every entry in aircraft.json arrives with no
# "t", "r", "desc" or "ownOp".
#
# That failure is invisible from the map, which is why it survived a whole
# install: tar1090 does its own lookup in the browser from html/db-<hash>/, so
# the map keeps showing types and registrations while the JSON feed BOXRADAR
# reads is bare. Only the display goes blank, and it goes blank twice over —
# no designator to show, and nothing for aircraft_types.py to name.
#
# Nothing else here installs the file, and nothing else keeps it current:
# tar1090's installer clones tar1090-db for the *web* copy only (git-db/db/),
# and upstream's own csv.sh copies to this path guarded by `if [[ -f ... ]]` —
# it refreshes a file, it never creates one. The hand-built receiver has
# carried one since before this installer existed, so copying its config
# across brought the flag and not the 8MB it points at.
#
# Both halves live in files/boxradar-aircraft-db rather than here. The
# installer and the weekly timer run the same script for the same reason the
# renderers are shared: two copies of "fetch, verify, swap in" would drift,
# and the one that drifts is the one nobody watches.
echo "installing the aircraft database updater"
install -m 0755 "$SRC_DIR/files/boxradar-aircraft-db" \
                /usr/local/bin/boxradar-aircraft-db
install -m 0644 "$SRC_DIR/files/boxradar-aircraft-db.service" \
                /etc/systemd/system/boxradar-aircraft-db.service
install -m 0644 "$SRC_DIR/files/boxradar-aircraft-db.timer" \
                /etc/systemd/system/boxradar-aircraft-db.timer
systemctl daemon-reload
systemctl enable --now boxradar-aircraft-db.timer >/dev/null

# --no-restart because readsb is restarted a few lines below anyway, once its
# config is written; letting the script do it here would restart it against
# the previous /etc/default/readsb for nothing. A non-zero exit is the box
# having no database at all, which is worth stopping the install for — the
# display would show callsigns and nothing else.
echo "fetching the aircraft database (8MB)"
/usr/local/bin/boxradar-aircraft-db --no-restart

# Written after the installers, which lay down their own defaults. This is the
# file that unifies the position: the hand-built receiver had readsb and the
# ADSBExchange feeder 15m apart, which MLAT solves hyperbolae from.
echo "writing /etc/default/readsb"
render_readsb >/etc/default/readsb

systemctl restart readsb
systemctl enable readsb >/dev/null

# tar1090 reads readsb's JSON, so it follows readsb here, but its restart and
# enable are not swallowed with `|| true`. tar1090 is the map — the thing an
# operator actually opens in a browser to tell whether the receiver works —
# and a service that is genuinely broken (bad lighttpd config, port clash)
# should fail this stage right here and say so, not report success and leave
# it to whoever next loads the page to guess why there's no map.
systemctl restart tar1090
systemctl enable tar1090 >/dev/null

# Wait for readsb to write its first JSON snapshot. `[[ -e FILE ]] && break`
# is safe under set -e even while the file is absent on every iteration: a
# command that fails as a non-final part of an && list does not trigger
# errexit, so a missing file just lets the loop run out its 30 iterations
# rather than aborting the script early with no message. The explicit check
# below is what actually decides success or failure.
for _ in $(seq 1 30); do
  [[ -e /run/readsb/aircraft.json ]] && break
  sleep 1
done
[[ -e /run/readsb/aircraft.json ]] || {
  echo "readsb is not producing JSON. check: journalctl -u readsb -n 40" >&2
  exit 1
}

echo "readsb: $(readsb --version 2>&1 | head -1)"
