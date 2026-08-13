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
