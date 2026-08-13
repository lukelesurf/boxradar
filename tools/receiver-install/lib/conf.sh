#!/usr/bin/env bash
# receiver.conf: the single source of truth for a site.
#
# Validation is stricter than it looks like it needs to be because the person
# running this on the second unit cannot be assumed to notice a transposed
# coordinate — and a wrong position does not show up on the display. It
# degrades MLAT, quietly.

conf_number() { [[ $1 =~ ^-?[0-9]+([.][0-9]+)?$ ]]; }
conf_integer() { [[ $1 =~ ^-?[0-9]+$ ]]; }

conf_validate() {
  local problems=0
  _bad() { echo "receiver.conf: $*" >&2; problems=1; }

  [[ ${HOSTNAME:-} =~ ^[a-z0-9][a-z0-9-]*$ ]] || \
    _bad "HOSTNAME must be lowercase letters, digits and hyphens"

  # bc is not on a bare Raspberry Pi OS Lite image, and this runs before the
  # stage that would install it. awk is always present.
  if ! conf_number "${LAT:-}"; then
    _bad "LAT is not a number: '${LAT:-}'"
  elif awk -v v="${LAT}" 'BEGIN { exit !(v > 90 || v < -90) }'; then
    _bad "LAT out of range: ${LAT}"
  fi

  if ! conf_number "${LON:-}"; then
    _bad "LON is not a number: '${LON:-}'"
  elif awk -v v="${LON}" 'BEGIN { exit !(v > 180 || v < -180) }'; then
    _bad "LON out of range: ${LON}"
  fi

  conf_integer "${ALT_FT:-}" || \
    _bad "ALT_FT must be a whole number of feet: '${ALT_FT:-}'"
  [[ ${GAIN:-} == "auto" ]] || conf_number "${GAIN:-}" || \
    _bad "GAIN must be 'auto' or a number: '${GAIN:-}'"
  conf_number "${PPM:-}" || _bad "PPM must be a number: '${PPM:-}'"
  [[ ${METAR_STATION:-} =~ ^[A-Za-z]{4}$ ]] || \
    _bad "METAR_STATION must be a 4-letter ICAO code: '${METAR_STATION:-}'"
  conf_integer "${CALM_KT:-}" || _bad "CALM_KT must be a whole number"

  # These three are interpolated into receiver.conf, which is later sourced
  # (by root, during install). A value containing $(...), a backtick, quotes
  # or whitespace would corrupt the file or execute as shell rather than
  # being assigned — restricting the character set is not cosmetic here.
  [[ ${ADSBX_USER:-} =~ ^[A-Za-z0-9_.-]+$ ]] || \
    _bad "ADSBX_USER may only contain letters, digits, dot, underscore and hyphen"
  [[ ${FR24_KEY:-} =~ ^[A-Za-z0-9]+$ ]] || \
    _bad "FR24_KEY may only contain letters and digits"
  # Blank on a new box — the ADSBExchange installer generates it — so it is
  # only constrained when present.
  [[ -z ${ADSBX_UUID:-} || ${ADSBX_UUID:-} =~ ^[A-Za-z0-9-]+$ ]] || \
    _bad "ADSBX_UUID may only contain letters, digits and hyphen"

  return $problems
}

conf_write() {
  local path=$1
  mkdir -p "$(dirname "$path")"
  # Created 0600 before anything is written to it: the file carries the FR24
  # key and the ADSBExchange uuid, and a default-umask window is still a
  # window.
  install -m 0600 /dev/null "$path"
  cat >"$path" <<EOF
# BOXRADAR receiver configuration. Written by tools/receiver-install.
# Mode 0600 — this file carries feeder credentials. Never commit it.

# Identity
HOSTNAME="${HOSTNAME}"

# Position. ONE source, fanned out to readsb, ADSBExchange, MLAT and
# selection.json. The hand-built receiver carried four different positions
# spanning ~15m; MLAT is the consumer for which that was not cosmetic.
LAT="${LAT}"
LON="${LON}"
ALT_FT="${ALT_FT}"

# Radio
GAIN="${GAIN}"
PPM="${PPM}"

# Network. Blank STATIC_IP means DHCP.
STATIC_IP="${STATIC_IP}"

# Weather
METAR_STATION="${METAR_STATION}"
CALM_KT="${CALM_KT}"

# Feeder identity. Restored on reinstall so statistics and MLAT peer
# reputation survive a rebuild rather than starting from zero.
ADSBX_USER="${ADSBX_USER}"
ADSBX_UUID="${ADSBX_UUID}"
FR24_KEY="${FR24_KEY}"
EOF
}

conf_load() {
  local path=$1
  [[ -r $path ]] || { echo "cannot read $path" >&2; return 1; }
  # Bash populates $HOSTNAME itself at shell startup (from the environment if
  # inherited, otherwise from the machine's real hostname), so it is never
  # unset going into a source. Clear it first so a receiver.conf that omits
  # HOSTNAME leaves the variable empty rather than silently keeping whatever
  # this shell already had — which conf_validate could then wrongly accept.
  unset HOSTNAME
  # shellcheck disable=SC1090
  source "$path"
}
