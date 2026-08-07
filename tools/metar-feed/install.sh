#!/usr/bin/env bash
# Install the METAR feed on the RECEIVER Pi (the box running readsb/tar1090,
# NOT the display and NOT a separate server).
#
#   sudo ./install.sh
#
# Edit STATIONS at the top of metar_feed.py first if you are not near
# Stansted/Luton, then re-run this to update.
#
# Afterwards the display fetches http://<receiver>/metar.json alongside the
# aircraft.json it already polls.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN=/usr/local/bin/metar_feed.py
UNIT_DIR=/etc/systemd/system
WEB_ROOT=/var/www/html

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

if [[ ! -d $WEB_ROOT ]]; then
  echo "note: $WEB_ROOT missing, creating it"
  install -d -m 0755 "$WEB_ROOT"
fi

echo "installing $BIN"
install -m 0755 "$SRC_DIR/metar_feed.py" "$BIN"

echo "installing systemd units"
install -m 0644 "$SRC_DIR/metar-feed.service" "$UNIT_DIR/metar-feed.service"
install -m 0644 "$SRC_DIR/metar-feed.timer" "$UNIT_DIR/metar-feed.timer"

systemctl daemon-reload
systemctl enable --now metar-feed.timer

echo "running once now..."
if systemctl start metar-feed.service; then
  sleep 1
  if [[ -s $WEB_ROOT/metar.json ]]; then
    echo
    echo "OK -> $WEB_ROOT/metar.json"
    head -c 400 "$WEB_ROOT/metar.json"; echo
    echo
    echo "verify over HTTP from another machine:"
    echo "  curl http://\$(hostname -I | awk '{print \$1}')/metar.json"
  else
    echo "warning: unit ran but $WEB_ROOT/metar.json is empty/missing" >&2
    echo "check: journalctl -u metar-feed.service -n 30 --no-pager" >&2
    exit 1
  fi
else
  echo "error: first run failed" >&2
  echo "check: journalctl -u metar-feed.service -n 30 --no-pager" >&2
  exit 1
fi

echo
systemctl list-timers metar-feed.timer --no-pager || true
