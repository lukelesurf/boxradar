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
      if ! read -r -p "$prompt: " reply; then
        # EOF (Ctrl-D, or stdin closed under an unattended/piped invocation)
        # on a *required* prompt with no stored default to fall back to —
        # unlike the defaulted branch above, there is nothing safe to do but
        # stop. Left unguarded, `reply` stays empty and `while :` spins
        # forever re-printing "(required)".
        echo
        echo "no input available — run interactively, or use --no-wizard" >&2
        exit 1
      fi
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
  ask HOSTNAME     "Hostname (reachable as <name>.local)" "boxradar-rx"
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
    --from) [[ $# -ge 2 ]] || { echo "--from needs a stage number" >&2; exit 2; }
             FROM="$2"; shift ;;
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
  # -u (unbuffered): sed defaults to full 4KB buffering on its stdout when
  # that's a pipe rather than a terminal, which is exactly what it is here.
  # scrub_log below relies on output reaching $LOG promptly to know when a
  # sync sentinel has actually landed on disk; buffered, that sentinel could
  # sit in sed's memory well after the write() that would make it visible.
  if [[ ${#patterns[@]} -eq 0 ]]; then cat; else sed -u "${patterns[@]}"; fi
}

# redact()'s patterns are built once, from whatever FR24_KEY/ADSBX_UUID were
# at the moment logging started — empty for ADSBX_UUID on a fresh box, since
# stage 40 (the ADSBExchange installer) is what generates it. A uuid it
# echoes reaches the log verbatim. Called once after every stage has had its
# chance to run, this re-reads $CONF (picking up whatever 40-feeders.sh just
# wrote) and rewrites $LOG in place with today's actual secret values
# scrubbed. Truncate-and-rewrite via a temp file, not `mv` onto $LOG: the
# exec redirection's tee is still writing into $LOG by file descriptor
# (opened O_APPEND) for the rest of this script's run, and swapping in a new
# inode would leave that fd appending into an orphaned file nothing can see.
#
# The tricky part is timing, not mechanism: `exec > >(redact | tee -a
# "$LOG")` runs that pipeline in a background subshell, asynchronously with
# the rest of this script. A read of $LOG taken right after the loop ends
# can race ahead of output the pipeline has not finished writing yet — this
# was caught by hand: a fake stage that echoed a freshly-generated uuid and
# was picked up by scrub_log's conf_load still left the *raw* uuid sitting
# in the log, because the read landed before that echo had made it through
# the pipe. Fixed by writing a one-off sentinel to stdout and polling $LOG
# until it shows up, which — since the pipe preserves order — proves
# everything written before it has too; only then is it safe to read.
# grep -F, not plain grep: the sentinel is arbitrary text, not a pattern.
scrub_log() {
  local tmp sentinel="scrub-sync-$$-$RANDOM"
  echo "$sentinel"
  for _ in $(seq 1 100); do
    grep -qF "$sentinel" "$LOG" 2>/dev/null && break
    sleep 0.05
  done
  if ! { conf_load "$CONF" \
      && tmp="$(mktemp)" \
      && redact <"$LOG" | grep -vF "$sentinel" >"$tmp" \
      && cat "$tmp" >"$LOG"; } 2>/dev/null; then
    # Silent-but-safe would defeat the point: this function exists so a log
    # an operator emails for help doesn't carry a live secret. If it
    # couldn't run, say so — the raw log is still there, just not scrubbed.
    echo "warning: could not scrub $LOG — check it by hand before sharing it" >&2
  fi
  [[ -n ${tmp:-} ]] && rm -f "$tmp"
  return 0
}

# Bash pre-sets $HOSTNAME at shell startup, from the environment or the
# machine's real hostname. conf_load unsets it before sourcing, but only
# runs when $CONF already exists — on a fresh box there is none, so without
# this, `ask HOSTNAME` below would see the machine's current name (e.g.
# "raspberrypi" straight off the Pi OS image) as its "current" value and
# offer that as the default instead of the wizard's own "boxradar-rx".
# Pressing enter would then "succeed" leaving the box named whatever the
# wizard exists to change. (The receiver's default is boxradar-rx, not
# boxradar: the ESP32 display board already owns boxradar.local via mDNS —
# see include/config.example.h and src/net_task.cpp — and this box installs
# avahi too, so the two would otherwise race for the same name on the LAN.)
unset HOSTNAME
[[ -r $CONF ]] && conf_load "$CONF"

# The wizard runs before logging starts. Not because read echoes input — the
# tty does that, and it never reaches this process's stdout — but because
# `ask` renders existing values as prompt defaults. On a re-run the FR24
# prompt reads "... [<the stored key>]: ", and read -p writes prompts to
# stderr, which tee would capture. Logging starts once the wizard is done.
if [[ $WIZARD -eq 1 ]]; then
  run_wizard
  conf_load "$CONF"
fi

mkdir -p "$(dirname "$LOG")" "$STAMP_DIR"
# tee would otherwise create $LOG under the process's default umask (0644 —
# world-readable) the first time it's written. Created explicitly at 0600
# instead: the log carries the redacted-but-still-sensitive shape of
# receiver.conf, and a default-umask window is still a window. An existing
# log from before this fix, or from a prior run, is chmod'd rather than
# truncated — tee -a's whole point is that a log survives across retries.
if [[ -e $LOG ]]; then
  chmod 0600 "$LOG"
else
  install -m 0600 /dev/null "$LOG"
fi
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
stages=("$STAGE_DIR"/*.sh)
if [[ ${#stages[@]} -eq 0 ]]; then
  echo "error: no stage scripts in $STAGE_DIR" >&2
  echo "       an incomplete copy of tools/receiver-install?" >&2
  exit 1
fi
for stage in "${stages[@]}"; do
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
    # A stage after 40 could have already generated an ADSBX_UUID that
    # redact() (fixed at fork time) never knew to scrub — and this log,
    # named right below, is exactly what a failed run gets emailed
    # somewhere for help with.
    scrub_log
    cat >&2 <<EOF

stage $name failed (exit $status)
completed stages keep their stamps and will be skipped.
fix, then re-run:  sudo ./install.sh
full log:          $LOG
EOF
    exit "$status"
  fi
done

scrub_log

echo "=== all stages complete ==="
