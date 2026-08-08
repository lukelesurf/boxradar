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

# Fail early rather than leaving a unit in a restart loop against whatever
# already owns the port. Skipped when our own service is what holds it, which
# is the normal case when re-running this to upgrade.
if ss -ltn "sport = :$PORT" | grep -q LISTEN; then
  if systemctl is-active --quiet boxradar-site.service; then
    echo "note: boxradar-site already running on $PORT, will restart it"
  else
    echo "error: something else is already listening on port $PORT:" >&2
    ss -ltnp "sport = :$PORT" >&2
    exit 1
  fi
fi

echo "installing package to $LIB_DIR"
install -d -m 0755 "$LIB_DIR"
rm -rf "$LIB_DIR/boxradar_site"
cp -r "$SRC_DIR/boxradar_site" "$LIB_DIR/boxradar_site"
# Drop any __pycache__ carried over from a dev machine: it may hold bytecode
# for a different Python than the Pi's.
find "$LIB_DIR/boxradar_site" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$LIB_DIR/boxradar_site" -type f -exec chmod 0644 {} +
find "$LIB_DIR/boxradar_site" -type d -exec chmod 0755 {} +

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

echo "installing systemd unit"
install -m 0644 "$SRC_DIR/boxradar-site.service" \
                "$UNIT_DIR/boxradar-site.service"
systemctl daemon-reload
systemctl enable boxradar-site.service
systemctl restart boxradar-site.service

sleep 2
if ! curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null; then
  echo "error: service is not answering on port $PORT" >&2
  echo "check: journalctl -u boxradar-site.service -n 30 --no-pager" >&2
  exit 1
fi

echo
echo "OK. verify from another machine:"
echo "  curl http://\$(hostname -I | awk '{print \$1}'):$PORT/metar/EGSS"
echo
systemctl --no-pager status boxradar-site.service | head -n 12
