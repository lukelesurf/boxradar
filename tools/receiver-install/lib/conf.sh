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

  # Blank means DHCP. Otherwise 20-os.sh hands this straight to
  # `nmcli connection modify ... ipv4.addresses`, which takes an address
  # optionally followed by a /prefix — anchoring it here also keeps anything
  # else (in particular a stray quote) out of a value that conf_write quotes
  # when writing the file.
  [[ -z ${STATIC_IP:-} || ${STATIC_IP:-} =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]] || \
    _bad "STATIC_IP must be blank (DHCP) or an address like 192.0.2.10/24"

  # These three are interpolated into receiver.conf, which is later sourced
  # (by root, during install). A value containing $(...), a backtick, quotes
  # or whitespace would corrupt the file or execute as shell rather than
  # being assigned — restricting the character set is not cosmetic here.
  [[ ${ADSBX_USER:-} =~ ^[A-Za-z0-9_.-]+$ ]] || \
    _bad "ADSBX_USER may only contain letters, digits, dot, underscore and hyphen"
  # Blank means this site does not feed adsb.lol at all — 40-feeders.sh skips
  # its whole section — so unlike ADSBX_USER this is only constrained when
  # present. adsb.lol's own configure.sh merely strips spaces out of the name;
  # the same class as ADSBX_USER is stricter than they require, which is the
  # right direction for a value that lands in a file root sources.
  [[ -z ${ADSBLOL_USER:-} || ${ADSBLOL_USER:-} =~ ^[A-Za-z0-9_.-]+$ ]] || \
    _bad "ADSBLOL_USER may only contain letters, digits, dot, underscore and hyphen"
  # An 8-character floor, not just the character class: redact() builds its
  # sed patterns straight from these values (s|$FR24_KEY|<FR24_KEY>|g), so a
  # one-character key doesn't just under-validate — it turns every matching
  # character anywhere in the log into a placeholder, e.g. FR24_KEY=k
  # shredding every "k" in the install log.
  if [[ ! ${FR24_KEY:-} =~ ^[A-Za-z0-9]+$ ]]; then
    _bad "FR24_KEY may only contain letters and digits"
  elif (( ${#FR24_KEY} < 8 )); then
    _bad "FR24_KEY must be at least 8 characters"
  fi
  # Blank on a new box — the ADSBExchange installer generates it — so it is
  # only constrained when present. Same 8-character floor as FR24_KEY, and
  # for the same redact() reason.
  if [[ -n ${ADSBX_UUID:-} ]]; then
    if [[ ! ${ADSBX_UUID} =~ ^[A-Za-z0-9-]+$ ]]; then
      _bad "ADSBX_UUID may only contain letters, digits and hyphen"
    elif (( ${#ADSBX_UUID} < 8 )); then
      _bad "ADSBX_UUID must be at least 8 characters"
    fi
  fi
  # Same rules, same reasons: adsb.lol's create-uuid.sh keeps whatever it
  # finds in /usr/local/share/adsblol/adsblol-uuid as long as it parses as a
  # uuid, so restoring this is what carries a rebuilt box's identity across.
  if [[ -n ${ADSBLOL_UUID:-} ]]; then
    if [[ ! ${ADSBLOL_UUID} =~ ^[A-Za-z0-9-]+$ ]]; then
      _bad "ADSBLOL_UUID may only contain letters, digits and hyphen"
    elif (( ${#ADSBLOL_UUID} < 8 )); then
      _bad "ADSBLOL_UUID must be at least 8 characters"
    fi
  fi

  return $problems
}

conf_write() {
  local path=$1 key value
  # conf_validate character-checks the fields it knows about, but this file
  # is sourced — by root — so writing is the last place to catch a value
  # that could break out of its own quoting. A field added later without a
  # matching validation rule fails here rather than silently becoming
  # shell. (This is what caught STATIC_IP: quoted by conf_write but, at the
  # time, only checked for emptiness by conf_validate — a value carrying
  # its own closing quote escaped into command context on source.)
  for key in HOSTNAME LAT LON ALT_FT GAIN PPM STATIC_IP METAR_STATION \
             CALM_KT ADSBX_USER ADSBX_UUID ADSBLOL_USER ADSBLOL_UUID \
             FR24_KEY; do
    value="${!key:-}"
    if [[ $value == *'"'* || $value == *'`'* || $value == *'$'* || \
          $value == *\\* || $value == *$'\n'* ]]; then
      echo "receiver.conf: $key contains a character that cannot be written safely" >&2
      return 1
    fi
  done
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

# Position. ONE source, fanned out to readsb, ADSBExchange, adsb.lol, MLAT
# and selection.json. The hand-built receiver carried four different positions
# spanning ~15m; MLAT is the consumer for which that was not cosmetic —
# adsb.lol's own wizard puts it plainly: "a small error of 15m/45ft will cause
# issues with MLAT".
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

# adsb.lol. Blank ADSBLOL_USER means this site does not feed them and stage 40
# installs nothing for it. Feeding is also what grants re-api access, which is
# gated on the station's source IP rather than a key — so there is no
# credential here to restore, only the identity.
#
# :- on both, unlike every field above them: a receiver.conf written before
# adsb.lol support existed has neither key, conf_load leaves them unset, and
# install.sh runs under set -u. Without the default, rewriting an older conf
# (which conf_write does whenever stage 40 records a new uuid) would abort on
# an unbound variable instead of quietly filling in the blanks.
ADSBLOL_USER="${ADSBLOL_USER:-}"
ADSBLOL_UUID="${ADSBLOL_UUID:-}"

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
