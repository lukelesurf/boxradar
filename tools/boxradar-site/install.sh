#!/usr/bin/env bash
# Install the BOXRADAR site application on the RECEIVER Pi (the box running
# readsb/tar1090, NOT the display and NOT the home server).
#
#   sudo ./install.sh
#
# Afterwards the display fetches http://<receiver>:8081/metar/<ICAO> instead
# of the static /metar.json the old timer published.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/local/lib/boxradar-site
CONF_DIR=/etc/boxradar-site
UNIT_DIR=/etc/systemd/system
PORT=8081
CONFIG_PORT=8082
DOCROOT=/var/www/html
# The configuration UI runs as a DynamicUser, which has no stable identity to
# chown anything to. A named group it joins via SupplementaryGroups= is the
# way to let it publish into lighttpd's document root without loosening that
# directory for everyone or giving the service a real account.
PUB_GROUP=boxradar-pub

if [[ $EUID -ne 0 ]]; then
  echo "error: run as root (sudo ./install.sh)" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "error: no systemd on this host" >&2
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)'; then
  echo "error: python3 >= 3.7 required" >&2
  exit 1
fi

# The METAR service is stdlib-only on purpose, so it is installed and started
# regardless. The geography generator additionally needs shapely and yaml, and
# the configuration UI needs Flask on top of those; report rather than fail, so
# a receiver that only wants weather still works.
#
# All three come from apt. Debian's Python is externally managed under PEP 668
# so pip is not an option, but apt is outside PEP 668's scope — which is the
# whole reason these are acceptable dependencies at all.
WANT_CONFIG_UI=0
if python3 -c 'import shapely, yaml' 2>/dev/null; then
  echo "geography generator dependencies present"
  if python3 -c 'import flask' 2>/dev/null; then
    echo "configuration UI dependencies present"
    WANT_CONFIG_UI=1
  else
    echo "note: configuration UI unavailable"
    echo "      to enable: sudo apt install python3-flask"
  fi
else
  echo "note: geography generation unavailable (that is fine for METAR only)"
  echo "      to enable: sudo apt install python3-shapely python3-yaml"
  echo "      the configuration UI additionally needs python3-flask"
fi

# Fail early rather than leaving a unit in a restart loop against whatever
# already owns the port. Skipped when our own service is what holds it, which
# is the normal case when re-running this to upgrade.
check_port() {
  local port=$1 unit=$2 listening
  # Captured first, then matched, not piped straight into grep -q: under
  # this script's `set -euo pipefail`, grep -q closing the pipe the instant
  # it matches can SIGPIPE a still-writing `ss`, which reports as exit 141.
  # `|| return 0` on a piped form would then read "port is free" from a
  # 141 exactly when the port *is* occupied — skipping the abort this
  # function exists to make, unattended, on someone else's hardware.
  listening="$(ss -ltn "sport = :$port" 2>/dev/null || true)"
  grep -q LISTEN <<<"$listening" || return 0
  if systemctl is-active --quiet "$unit"; then
    echo "note: $unit already running on $port, will restart it"
    return 0
  fi
  echo "error: something else is already listening on port $port:" >&2
  ss -ltnp "sport = :$port" >&2
  exit 1
}

check_port "$PORT" boxradar-site.service
if [[ $WANT_CONFIG_UI -eq 1 ]]; then
  check_port "$CONFIG_PORT" boxradar-config.service
  # The UI publishes site.bin into lighttpd's document root. Without it the
  # service starts and then fails only at the moment someone presses Publish,
  # which is the worst time to find out.
  if [[ ! -d $DOCROOT ]]; then
    echo "error: $DOCROOT does not exist — the configuration UI" >&2
    echo "       publishes site.bin there for lighttpd to serve" >&2
    exit 1
  fi
fi

echo "installing packages to $LIB_DIR"
install -d -m 0755 "$LIB_DIR"
for pkg in boxradar_site boxradar_config; do
  rm -rf "${LIB_DIR:?}/$pkg"
  cp -r "$SRC_DIR/$pkg" "$LIB_DIR/$pkg"
  # Drop any __pycache__ carried over from a dev machine: it may hold bytecode
  # for a different Python than the Pi's.
  find "$LIB_DIR/$pkg" -name __pycache__ -type d -prune -exec rm -rf {} +
  find "$LIB_DIR/$pkg" -type f -exec chmod 0644 {} +
  find "$LIB_DIR/$pkg" -type d -exec chmod 0755 {} +
done

install -d -m 0755 "$CONF_DIR"
if [[ -f $CONF_DIR/config.json ]]; then
  echo "keeping existing $CONF_DIR/config.json"
else
  echo "writing default $CONF_DIR/config.json"
  # Runway headings are TRUE, not magnetic. Designators are magnetic and
  # rounded to 10 degrees, so 05 is not 050. These are the three fields the
  # superseded metar_feed.py carried.
  cat > "$CONF_DIR/config.json" <<'JSON'
{
  "runways": {
    "EGSS": [["04", 43], ["22", 223]],
    "EGGW": [["07", 74], ["25", 254]],
    "EGMC": [["05", 54], ["23", 234]]
  },
  "calm_kt": 7
}
JSON
  chmod 0644 "$CONF_DIR/config.json"
fi

if [[ $WANT_CONFIG_UI -eq 1 ]]; then
  if ! getent group "$PUB_GROUP" >/dev/null; then
    echo "creating group $PUB_GROUP"
    groupadd --system "$PUB_GROUP"
  fi
  # setgid, so anything published inherits the group rather than depending on
  # whichever dynamic user happened to write it.
  chgrp "$PUB_GROUP" "$DOCROOT"
  chmod 2775 "$DOCROOT"
  echo "$DOCROOT is writable by $PUB_GROUP"
fi

echo "installing systemd units"
install -m 0644 "$SRC_DIR/boxradar-site.service" \
                "$UNIT_DIR/boxradar-site.service"
if [[ $WANT_CONFIG_UI -eq 1 ]]; then
  install -m 0644 "$SRC_DIR/boxradar-config.service" \
                  "$UNIT_DIR/boxradar-config.service"
fi
systemctl daemon-reload
systemctl enable boxradar-site.service
systemctl restart boxradar-site.service
if [[ $WANT_CONFIG_UI -eq 1 ]]; then
  systemctl enable boxradar-config.service
  systemctl restart boxradar-config.service
fi

# Poll rather than sleep-once. The configuration UI imports Flask and shapely
# before it binds, which takes about four seconds on a Pi — a flat `sleep 2`
# reported a failure for a service that was starting perfectly well.
wait_for_health() {
  local port=$1 unit=$2 i
  for i in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$port/healthz" >/dev/null 2>&1; then
      return 0
    fi
    if ! systemctl is-active --quiet "$unit"; then
      break  # died rather than still starting; no point waiting out the loop
    fi
    sleep 1
  done
  echo "error: $unit is not answering on port $port" >&2
  echo "check: journalctl -u $unit -n 30 --no-pager" >&2
  exit 1
}

wait_for_health "$PORT" boxradar-site.service
if [[ $WANT_CONFIG_UI -eq 1 ]]; then
  wait_for_health "$CONFIG_PORT" boxradar-config.service
fi

HOST_IP=$(hostname -I | awk '{print $1}')
echo
echo "OK. verify from another machine:"
echo "  curl http://$HOST_IP:$PORT/metar/EGSS"
if [[ $WANT_CONFIG_UI -eq 1 ]]; then
  echo "  open http://$HOST_IP:$CONFIG_PORT/"
fi
echo
# Captured first, then trimmed with a herestring, not piped straight into
# head: this is the script's last command, so under `set -euo pipefail` a
# `head -n 12` that hits its line limit before `systemctl status` is done
# writing can SIGPIPE it — the resulting 141 becomes *this script's* exit
# status, and 50-boxradar.sh (which runs this as a stage) reports that as a
# stage failure after everything actually succeeded.
status_output="$(systemctl --no-pager status boxradar-site.service || true)"
head -n 12 <<<"$status_output"
