#!/usr/bin/env bash
# The BOXRADAR services, plus the reference data the configuration UI needs.
#
# The datasets are fetched here rather than left to the first visit to the UI:
# config.json cannot be derived without runways.csv, and a box that arrives
# with its weather already working is a better starting point than one that
# needs a download before it does anything.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SITE_DIR="$REPO_DIR/tools/boxradar-site"
LIB_DIR=/usr/local/lib/boxradar-site
CACHE=/var/cache/boxradar-config
SELECTION=/var/lib/boxradar-config/selection.json
CONFIG_PORT=8082

echo "installing python dependencies from apt"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-flask python3-shapely python3-yaml lighttpd

# boxradar-site/install.sh is the one place that knows how to detect a port
# conflict, create the boxradar-pub group, and confirm both services are
# actually answering before it returns — duplicating any of that here would
# just be a second, divergent copy to keep in sync.
echo "running the site application installer"
( cd "$SITE_DIR" && ./install.sh )

# boxradar-config.service is DynamicUser=yes with StateDirectory=/CacheDirectory=
# boxradar-config, so systemd redirects those to /var/{lib,cache}/private/... and
# leaves compatibility symlinks at the nominal paths. install.sh above already
# called systemctl restart on it and then polled /healthz until the process was
# actually serving, and directory creation happens before a unit's ExecStart
# runs at all — so by the time install.sh has returned, the private directory
# is guaranteed to exist. (Root could in fact just use the nominal paths and
# follow the symlink — /var/lib/private is 0700 but root bypasses that check —
# this resolves to the same path explicitly rather than depending on that.)
[[ -d /var/cache/private/boxradar-config ]] && CACHE=/var/cache/private/boxradar-config
[[ -d /var/lib/private/boxradar-config ]] && SELECTION=/var/lib/private/boxradar-config/selection.json

# fetch() writes to a .part file beside the target and renames onto it, so a
# download that dies partway (network drop, disk full) never leaves a
# truncated file where age_days() would find it and call it cached — a re-run
# retries exactly the datasets that didn't make it, not all four.
echo "fetching reference datasets (~32MB, one time)"
PYTHONPATH="$LIB_DIR" python3 - "$CACHE" <<'PY'
import sys
from boxradar_config import datasets
cache = sys.argv[1]
for name in datasets.SOURCES:
    if datasets.age_days(name, cache) is None:
        print(f"  fetching {name}", flush=True)
        datasets.fetch(name, cache)
    else:
        print(f"  {name} already cached", flush=True)
    # Written by this (root) shell, so readable-by-others depends on whatever
    # umask it inherited rather than on anything datasets.fetch() itself
    # guarantees. Every other file this stage writes gets an explicit mode
    # (config.json 0644, selection.json 0600); this makes the datasets no
    # different, so the DynamicUser boxradar-config later reads regardless
    # of umask — a mismatch here would otherwise surface only as an
    # unhandled exception the first time someone opens /airfields or /towns.
    datasets.path_for(name, cache).chmod(0o644)
PY

# 0644 above settles who can *read* the datasets, which is all the UI needs to
# use them. It says nothing about who can write the directory holding them,
# and root created that directory by fetching into it. Refreshing a dataset
# writes "<name>.part" alongside the real file and renames it (see
# datasets.fetch — the rename is what makes a half-downloaded 14MB file
# impossible to mistake for a good one), so a refresh needs the *directory*
# writable by the service.
#
# Left alone, the cached copies keep working and only refreshes fail, with
# four lines of
#     airports failed: [Errno 13] Permission denied: '.../airports.csv.part'
# on the /data page — which reads as a download problem and sends you to look
# at the network rather than at ownership.
#
# --reference rather than a literal uid: DynamicUser=yes means systemd picks
# the owner, and it is not ours to choose. Copying it off the CacheDirectory
# systemd made keeps this correct whatever that uid turns out to be.
chown -R --reference="$CACHE" "$CACHE/datasets"

echo "deriving /etc/boxradar-site/config.json for $METAR_STATION"
PYTHONPATH="$LIB_DIR" python3 - "$CACHE" "$METAR_STATION" "$CALM_KT" <<'PY'
import sys
from boxradar_config import headings
cache, icao, calm = sys.argv[1], sys.argv[2], int(sys.argv[3])
doc = headings.write_site_config("/etc/boxradar-site/config.json",
                                 cache, icao, calm)
table = doc["runways"].get(icao.upper(), [])
if table:
    print("  " + ", ".join(f"{d}={h}" for d, h in table))
else:
    print(f"  no runways found for {icao} — the METAR readout still works, "
          f"but no active runway will be recommended")
PY
chmod 0644 /etc/boxradar-site/config.json

# Seed the home position so the configuration UI opens centred on the site
# rather than on whatever the example file says. Only on first install: the
# UI owns this file from here on, and a rebuild must not overwrite whatever
# the operator has since ticked in the airspace/airfields/towns pickers.
if [[ ! -e $SELECTION ]]; then
  echo "seeding $SELECTION with the home position"
  mkdir -p "$(dirname "$SELECTION")"
  cat >"$SELECTION" <<EOF
{
  "home_lat": $LAT,
  "home_lon": $LON,
  "reach_nm": 65.0,
  "airspace": []
}
EOF
  chmod 0600 "$SELECTION"
  # Written by this (root) shell, so it starts out root-owned — unreadable to
  # the DynamicUser boxradar-config runs as. Matching it to the StateDirectory's
  # current owner here is not optional: systemd only recursively re-chowns a
  # StateDirectory's contents on start when the directory's own ownership is
  # already wrong. If the directory already belongs to the UID this restart is
  # about to reuse (the common case — DynamicUser prefers the same UID across
  # restarts of the same unit when it's free), that check passes and our
  # root-owned file is left exactly as we wrote it, unreadable to the service.
  # Not swallowed: a failure here means the file stays root-owned and
  # boxradar-config comes up unable to read its own state, which the healthz
  # check below would otherwise have to explain from a cold start.
  chown --reference="$(dirname "$SELECTION")" "$SELECTION"
fi

systemctl restart boxradar-site boxradar-config

# Confirm the config UI actually came back readable rather than trusting the
# chown above blind: /healthz calls store.load() on selection.json, so a wrong
# owner surfaces here as a failed poll instead of as a 500 the first time
# someone opens the page. `curl ... && break` is safe under set -e the same
# way the readsb JSON wait in 30-readsb.sh is: a command that fails as a
# non-final part of an && list does not trigger errexit, so a slow start just
# runs the loop out rather than aborting early. The check after the loop is
# what actually decides success or failure.
for _ in $(seq 1 15); do
  curl -fsS "http://127.0.0.1:$CONFIG_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$CONFIG_PORT/healthz" >/dev/null 2>&1 || {
  echo "boxradar-config is not answering healthy on $CONFIG_PORT" >&2
  echo "check: journalctl -u boxradar-config -n 40 --no-pager" >&2
  exit 1
}

echo "boxradar: services installed, datasets cached, config.json derived"
