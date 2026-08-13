#!/usr/bin/env bash
# Provision a BOXRADAR receiver from a bare Raspberry Pi OS Lite install.
#
#   sudo ./install.sh              collect config if needed, then run stages
#   sudo ./install.sh --check      render configs and diff, change nothing
#   sudo ./install.sh --from 40    resume at a stage
#   sudo ./install.sh --force      re-run stages already marked done
#
# Stamping is an optimisation. Every stage is independently idempotent, so
# --force is always safe and a stamp that lies costs repeated work rather than
# a broken box.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE_DIR="${BOXRADAR_STAGE_DIR:-$SRC_DIR/stages}"
STAMP_DIR="${BOXRADAR_STAMP_DIR:-/var/lib/boxradar-install}"
LOG="${BOXRADAR_LOG:-/var/log/boxradar-install.log}"
CONF="${BOXRADAR_CONF:-/etc/boxradar/receiver.conf}"

# shellcheck source=lib/conf.sh
# shellcheck disable=SC1091
source "$SRC_DIR/lib/conf.sh"
# shellcheck source=lib/render.sh
# shellcheck disable=SC1091
source "$SRC_DIR/lib/render.sh"

CHECK=0 FORCE=0 FROM=0 WIZARD=1

# ask VAR "prompt" "default" — used only by run_wizard, defined here (and
# run_wizard/check_mode below) ahead of argument parsing because bash must
# have a function's body before the point it's called from the main body.
ask() {
  local var=$1 prompt=$2 default=${3:-} reply
  local current="${!var:-$default}"
  if [[ -n $current ]]; then
    read -r -p "$prompt [$current]: " reply || true
    printf -v "$var" '%s' "${reply:-$current}"
  else
    while :; do
      read -r -p "$prompt: " reply || true
      [[ -n $reply ]] && break
      echo "  (required)"
    done
    printf -v "$var" '%s' "$reply"
  fi
}

run_wizard() {
  cat <<'EOF'

Setting up a BOXRADAR receiver. Existing answers are shown in brackets —
press enter to keep one, or type a new value.

EOF
  ask HOSTNAME     "Hostname (reachable as <name>.local)" "boxradar"
  ask LAT          "Aerial latitude, decimal degrees"
  ask LON          "Aerial longitude, decimal degrees"
  ask ALT_FT       "Aerial height above sea level, whole feet"
  ask GAIN         "Tuner gain ('auto' or a number)" "auto"
  ask PPM          "Tuner frequency correction, ppm" "0"
  ask STATIC_IP    "Static IP (blank for DHCP)" " "
  ask METAR_STATION "Nearest airport with a METAR, 4-letter ICAO"
  ask CALM_KT      "Below this windspeed, recommend no runway" "7"
  ask ADSBX_USER   "ADSBExchange feeder name"
  ask ADSBX_UUID   "ADSBExchange uuid (blank on a new box)" " "
  ask FR24_KEY     "Flightradar24 sharing key"
  STATIC_IP="${STATIC_IP// /}"
  ADSBX_UUID="${ADSBX_UUID// /}"
  conf_write "$CONF"
  echo "wrote $CONF (0600)"
}

check_mode() {
  echo "--- rendered /etc/default/readsb"
  render_readsb
  echo "--- rendered /etc/default/adsbexchange"
  render_adsbexchange
  echo "--- rendered /etc/fr24feed.ini (key redacted above)"
  render_fr24
  for pair in "/etc/default/readsb:render_readsb" \
              "/etc/default/adsbexchange:render_adsbexchange"; do
    local live="${pair%%:*}" fn="${pair##*:}"
    if [[ -r $live ]]; then
      echo "--- diff against live $live"
      diff <("$fn") "$live" || true
    fi
  done
}

usage() {
  cat <<'EOF'
usage: sudo ./install.sh [options]

  --check      render every config file and diff against what is live.
               Changes nothing. Run this before rebuilding a working box.
  --from N     resume at stage N (e.g. --from 40)
  --force      re-run stages already marked complete
  --no-wizard  use /etc/boxradar/receiver.conf as-is, prompt for nothing
  --help       this text
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --check) CHECK=1 ;;
    --force) FORCE=1 ;;
    --from) FROM="$2"; shift ;;
    --no-wizard) WIZARD=0 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ ${BOXRADAR_SKIP_ROOT_CHECK:-0} != 1 && $EUID -ne 0 ]]; then
  echo "error: run as root (sudo ./install.sh)" >&2
  exit 1
fi

# Redact before anything is teed. The log is the artefact the second operator
# sends back when something fails, so it must never carry their FR24 key.
redact() {
  local patterns=()
  [[ -n ${FR24_KEY:-} ]] && patterns+=(-e "s|${FR24_KEY}|<FR24_KEY>|g")
  [[ -n ${ADSBX_UUID:-} ]] && patterns+=(-e "s|${ADSBX_UUID}|<ADSBX_UUID>|g")
  if [[ ${#patterns[@]} -eq 0 ]]; then cat; else sed "${patterns[@]}"; fi
}

[[ -r $CONF ]] && conf_load "$CONF"

# The wizard runs BEFORE logging starts, and the order matters. `read -r`
# echoes what is typed, and the FR24 key is typed at a prompt — if the log
# were already capturing this stream, the key would be written to it before
# redact() had any way of knowing the value to redact.
if [[ $WIZARD -eq 1 ]]; then
  run_wizard
  conf_load "$CONF"
fi

mkdir -p "$(dirname "$LOG")" "$STAMP_DIR"
exec > >(redact | tee -a "$LOG") 2>&1

echo "=== boxradar receiver install: $(date -Is) ==="

# Unconditional, on every path — including --no-wizard, which is the
# hand-edited-file path and exactly where a transposed coordinate or a
# typo'd ICAO code appears. A bad receiver position has no visible symptom
# on the display; it silently degrades MLAT (which solves aircraft
# positions by multilateration from receiver locations), so this cannot be
# skipped just because the wizard didn't run.
if ! conf_validate; then
  echo "error: fix $CONF and re-run" >&2
  exit 1
fi

export HOSTNAME LAT LON ALT_FT GAIN PPM STATIC_IP METAR_STATION CALM_KT
export ADSBX_USER ADSBX_UUID FR24_KEY

if [[ $CHECK -eq 1 ]]; then
  check_mode
  exit 0
fi

shopt -s nullglob
for stage in "$STAGE_DIR"/*.sh; do
  name="$(basename "$stage" .sh)"
  number="${name%%-*}"
  stamp="$STAMP_DIR/$name.done"

  if (( 10#$number < 10#$FROM )); then
    echo "--- $name: skipped (--from $FROM)"
    continue
  fi
  if [[ -e $stamp && $FORCE -eq 0 ]]; then
    echo "--- $name: skipped (already complete; --force to re-run)"
    continue
  fi

  echo "--- $name: running"
  # Not `if ! bash "$stage"; then status=$?`: with the condition negated,
  # $? inside the then-branch reflects the negation (always 0), not the
  # stage's real exit code — `exit "$status"` would then always exit 0,
  # silently turning every stage failure into a reported success.
  if bash "$stage"; then
    touch "$stamp"
    echo "--- $name: complete"
  else
    status=$?
    cat >&2 <<EOF

stage $name failed (exit $status)
completed stages keep their stamps and will be skipped.
fix, then re-run:  sudo ./install.sh
full log:          $LOG
EOF
    exit "$status"
  fi
done

echo "=== all stages complete ==="
