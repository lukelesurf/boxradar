#!/usr/bin/env bash
# ADSBExchange, adsb.lol, adsb.fi, AeroDataBox and Flightradar24.
#
# The uuid and the sharing key are what tie this box to its existing
# statistics and MLAT peer reputation. Regenerating them silently restarts
# both from zero, which is why a rebuild restores them rather than letting the
# installers mint new ones.
#
# Ordering: this assumes stage 30 (readsb) already ran. Every feeder installer
# here detects and reconfigures whatever decoder is present, so running them
# first would leave them with nothing to configure against.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="${BOXRADAR_CONF:-/etc/boxradar/receiver.conf}"
# shellcheck source=../lib/render.sh
# shellcheck disable=SC1091
source "$SRC_DIR/lib/render.sh"
# shellcheck source=../lib/conf.sh
# shellcheck disable=SC1091
source "$SRC_DIR/lib/conf.sh"
# shellcheck source=../lib/build.sh
# shellcheck disable=SC1091
source "$SRC_DIR/lib/build.sh"

# Inherited by every update.sh below; see lib/build.sh for why.
feed_cc="$(feedclient_cc)"
[[ -n $feed_cc ]] && export CC="$feed_cc"

# fetch_and_run used to live here too, byte-for-byte identical to the copy in
# 30-readsb.sh. It went with the curl|bash call to adsbexchange.com/feed.sh:
# this stage now clones the feedclient with git and runs update.sh from it, so
# there is nothing left here to pipe into a shell.

# chrony is installed here, deliberately and visibly, because the adsb.lol
# and adsb.fi update.sh scripts would otherwise install it as a side effect:
# both carry the same check, `systemctl status chrony || systemctl status
# ntp`, which systemd-timesyncd does not satisfy. chrony declares
# Conflicts: time-daemon, which timesyncd provides, so apt *removes* timesyncd
# to make room — a receiver's clock daemon being swapped as a silent
# by-product of adding a feeder is exactly the kind of thing this installer
# exists to make explicit.
#
# Not fought, because chrony is the better clock here: MLAT is timing, and
# chrony disciplines and reports offset far more tightly than timesyncd
# (measured on the live receiver immediately after the swap: 1.4us from NTP
# time). fr24feed recognises it too — its "[time][i]Time synchronization
# confirmed" line names whichever daemon it finds.
#
# Guarded exactly as they guard it, so a box already running ntp or chrony is
# left alone rather than having a second time daemon pushed onto it. That
# guard is also what makes this safe to call from both opt-in blocks below
# rather than hoisting it to the top of the stage: a site feeding neither
# network keeps timesyncd, and a site feeding both installs chrony once.
ensure_ntp_daemon() {
  if ! systemctl is-active --quiet chrony && ! systemctl is-active --quiet ntp; then
    echo "installing chrony (the feeder needs a real NTP daemon; this replaces systemd-timesyncd)"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq chrony
  fi
}

# --- ADSBExchange ---------------------------------------------------------
ADSBX_PATH=/usr/local/share/adsbexchange
# The unit file, not the directory. `-d $ADSBX_PATH` was true the moment the
# feedclient repo had been cloned into it, so a run that died during the
# install left a directory behind that made every retry skip the install and
# go straight to `systemctl restart adsbexchange-feed` — restarting a service
# that was never installed. The unit file only exists once update.sh has
# actually finished, which is the condition this wants.
ADSBX_UNIT=/lib/systemd/system/adsbexchange-feed.service

# The uuid is written before the installer runs, not after. create-uuid.sh
# (which update.sh calls) keeps whatever it finds as long as it parses as a
# uuid, and only mints a new one otherwise — so seeding it here is what makes
# a rebuild keep its statistics and MLAT peer reputation, rather than
# generating one and overwriting it a moment later.
if [[ -n ${ADSBX_UUID:-} ]]; then
  echo "restoring the existing ADSBExchange uuid"
  mkdir -p "$ADSBX_PATH"
  printf '%s' "$ADSBX_UUID" >"$ADSBX_PATH/adsbx-uuid"
  # 0644, unlike fr24feed.ini's 0640: on disk this follows the upstream
  # ADSBExchange installer's own convention for the file, and the uuid is a
  # public identifier (it appears on ADSBExchange's own stats pages), not a
  # bearer credential like the FR24 sharing key. install.sh still redacts it
  # out of /var/log/boxradar-install.log as a precaution — a log is an
  # artefact that gets emailed around, and there is no cost to keeping the
  # uuid out of it even though this file's mode does not need to change.
  chmod 0644 "$ADSBX_PATH/adsbx-uuid"
fi

if [[ ! -f $ADSBX_UNIT ]]; then
  echo "installing the ADSBExchange feeder"
  # Deliberately NOT https://www.adsbexchange.com/feed.sh. That bootstrap's
  # last act is setup.sh, which runs configure.sh: five whiptail dialogs
  # asking for the feeder name, latitude, longitude and altitude. install.sh
  # sends stdout through `redact | tee`, so whiptail is handed a pipe instead
  # of a tty — it paints the dialog into the log file, the operator sees
  # nothing they can type into, and the run dies with "Setup canceled
  # (probably using Esc button)". Giving it a tty instead would fix the
  # drawing and still be wrong: it would make this stage unattendable.
  #
  # Nothing is lost by skipping it. Every answer configure.sh asks for is
  # already in receiver.conf, and its only output is /etc/default/adsbexchange
  # — a file this stage overwrites below in any case. update.sh is the half
  # that actually installs (build deps, venv, compile, unit files, uuid) and
  # is entirely non-interactive.
  #
  # The trade is a dependency on upstream's internal layout rather than their
  # published entry point, so a restructure upstream breaks this rather than
  # silently misconfiguring it. Accepted: the alternative is a stage that
  # cannot run unattended at all.
  mkdir -p "$ADSBX_PATH"
  if [[ -d $ADSBX_PATH/git/.git ]]; then
    git -C "$ADSBX_PATH/git" fetch --depth 1 origin master
    git -C "$ADSBX_PATH/git" reset --hard FETCH_HEAD
  else
    rm -rf "$ADSBX_PATH/git"
    git clone --depth 1 --single-branch --branch master \
      https://github.com/adsbexchange/feedclient.git "$ADSBX_PATH/git"
  fi
  # update.sh sources /etc/default/adsbexchange, so it has to exist before it
  # runs. Rendering it here as well as below is not redundant: it means the
  # file holds this installer's values from the very first moment rather than
  # briefly holding whatever the skipped wizard would have written.
  render_adsbexchange >/etc/default/adsbexchange
  bash "$ADSBX_PATH/git/update.sh"
else
  echo "ADSBExchange feeder already present"
fi

if [[ -z ${ADSBX_UUID:-} && -s $ADSBX_PATH/adsbx-uuid ]]; then
  # Generated by their installer on a new box. Persist it through conf_write
  # rather than a hand-rolled sed/append: conf_write is what defines the
  # file's format (every value quoted) and it carries the write-side guard
  # that rejects a value able to break out of that quoting. A second,
  # separately maintained writer here is exactly the kind of drift that
  # already bit STATIC_IP once (see lib/conf.sh) — quoted by conf_write but,
  # at the time, only checked for emptiness elsewhere.
  ADSBX_UUID="$(cat "$ADSBX_PATH/adsbx-uuid")"
  conf_write "$CONF"
  echo "recorded the new ADSBExchange uuid in $CONF"
fi

echo "writing /etc/default/adsbexchange"
render_adsbexchange >/etc/default/adsbexchange
systemctl restart adsbexchange-feed adsbexchange-mlat
# Not swallowed with `|| true`: see 30-readsb.sh, which does not swallow
# readsb's or tar1090's enable either. An enable that fails here (missing
# [Install] section, a unit name that changed upstream) means the feeder does
# not come back after a reboot, and that should fail this stage loudly right
# now rather than report success and leave a silently-disabled feeder for
# whoever next checks why the stats page shows nothing.
systemctl enable adsbexchange-feed adsbexchange-mlat >/dev/null

# --- adsb.lol -------------------------------------------------------------
# Opt-in. A blank ADSBLOL_USER means this site does not feed adsb.lol and
# nothing below runs — unlike ADSBExchange and FR24, which every BOXRADAR
# receiver feeds. Feeding them is also what grants re-api access
# (https://re-api.adsb.lol), the network-wide unfiltered readsb API, which is
# authorised by the station's source IP rather than by a key. That is why
# there is no credential to restore here, only the identity: any host sharing
# the receiver's public address can query it.
if [[ -n ${ADSBLOL_USER:-} ]]; then
  ADSBLOL_PATH=/usr/local/share/adsblol
  # The unit file, not the directory — same reasoning as ADSBX_UNIT above.
  ADSBLOL_UNIT=/lib/systemd/system/adsblol-feed.service

  ensure_ntp_daemon

  # Seeded before their installer runs, for the same reason as the
  # ADSBExchange uuid above: create-uuid.sh keeps whatever it finds as long as
  # it parses as a uuid, and mints a new one otherwise.
  if [[ -n ${ADSBLOL_UUID:-} ]]; then
    echo "restoring the existing adsb.lol uuid"
    mkdir -p "$ADSBLOL_PATH"
    printf '%s' "$ADSBLOL_UUID" >"$ADSBLOL_PATH/adsblol-uuid"
    chmod 0644 "$ADSBLOL_PATH/adsblol-uuid"
  fi

  if [[ ! -f $ADSBLOL_UNIT ]]; then
    echo "installing the adsb.lol feeder"
    # Deliberately NOT https://adsb.lol/feed.sh, for the reason spelled out at
    # length in the ADSBExchange block above — and here it is not even a
    # judgement call: their feed.sh is byte-for-byte the same bootstrap, and
    # its last act is setup.sh, which runs configure.sh (five whiptail
    # dialogs) and then a whiptail yes/no. Both are undrawable through
    # install.sh's log pipe. update.sh is the non-interactive half.
    mkdir -p "$ADSBLOL_PATH"
    if [[ -d $ADSBLOL_PATH/git/.git ]]; then
      git -C "$ADSBLOL_PATH/git" fetch --depth 1 origin master
      git -C "$ADSBLOL_PATH/git" reset --hard FETCH_HEAD
    else
      rm -rf "$ADSBLOL_PATH/git"
      git clone --depth 1 --single-branch --branch master \
        https://github.com/adsblol/feed.git "$ADSBLOL_PATH/git"
    fi
    # Rendered before update.sh runs, which sources it. Skipping configure.sh
    # means nothing else ever writes this file.
    render_adsblol >/etc/default/adsblol
    bash "$ADSBLOL_PATH/git/update.sh"
  else
    echo "adsb.lol feeder already present"
  fi

  if [[ -z ${ADSBLOL_UUID:-} && -s $ADSBLOL_PATH/adsblol-uuid ]]; then
    ADSBLOL_UUID="$(cat "$ADSBLOL_PATH/adsblol-uuid")"
    conf_write "$CONF"
    echo "recorded the new adsb.lol uuid in $CONF"
  fi

  echo "writing /etc/default/adsblol"
  render_adsblol >/etc/default/adsblol
  systemctl restart adsblol-feed adsblol-mlat
  # Not swallowed, same as the ADSBExchange enable above.
  systemctl enable adsblol-feed adsblol-mlat >/dev/null
else
  echo "adsb.lol: ADSBLOL_USER is blank — not feeding adsb.lol"
fi

# --- adsb.fi ---------------------------------------------------------------
# Opt-in, exactly as adsb.lol above: a blank ADSBFI_USER means nothing here
# runs. Their scripts are the same ADSBExchange feedclient a third time, so
# this block is the adsb.lol one with the names changed — see lib/render.sh
# for the one place they genuinely differ, which is the local port block.
#
# Feeding grants the feeder-only /v2/snapshot endpoint on opendata.adsb.fi
# (all aircraft, refreshed twice a minute), authorised by the station's source
# IP rather than a key — the same arrangement re-api.adsb.lol uses, so there
# is no credential to restore here either.
if [[ -n ${ADSBFI_USER:-} ]]; then
  ADSBFI_PATH=/usr/local/share/adsbfi
  # The unit file, not the directory — same reasoning as ADSBX_UNIT above.
  ADSBFI_UNIT=/lib/systemd/system/adsbfi-feed.service

  ensure_ntp_daemon

  if [[ -n ${ADSBFI_UUID:-} ]]; then
    echo "restoring the existing adsb.fi uuid"
    mkdir -p "$ADSBFI_PATH"
    printf '%s' "$ADSBFI_UUID" >"$ADSBFI_PATH/adsbfi-uuid"
    chmod 0644 "$ADSBFI_PATH/adsbfi-uuid"
  fi

  if [[ ! -f $ADSBFI_UNIT ]]; then
    echo "installing the adsb.fi feeder"
    # Deliberately NOT https://adsb.fi/feed.sh — the same bootstrap-runs-
    # whiptail problem spelled out in the ADSBExchange block above. Their
    # setup.sh runs configure.sh (five dialogs) and then a yes/no box, none of
    # which can draw through install.sh's log pipe. update.sh is the
    # non-interactive half.
    #
    # One extra reason to skip configure.sh here beyond the others: it is the
    # thing that would write RESULTS3=30157 and collide with
    # adsbexchange-mlat. Rendering /etc/default/adsbfi ourselves is what fixes
    # that, so running their wizard would actively undo it.
    mkdir -p "$ADSBFI_PATH"
    if [[ -d $ADSBFI_PATH/git/.git ]]; then
      git -C "$ADSBFI_PATH/git" fetch --depth 1 origin master
      git -C "$ADSBFI_PATH/git" reset --hard FETCH_HEAD
    else
      rm -rf "$ADSBFI_PATH/git"
      git clone --depth 1 --single-branch --branch master \
        https://github.com/adsbfi/adsb-fi-scripts.git "$ADSBFI_PATH/git"
    fi
    # Rendered before update.sh runs, which sources it. update.sh also treats
    # an unset INPUT/USER/TARGET/NET_OPTIONS as "never configured" and drops
    # into setup.sh's wizard, so this file existing and being complete is what
    # keeps the stage unattended.
    render_adsbfi >/etc/default/adsbfi
    bash "$ADSBFI_PATH/git/update.sh"
  else
    echo "adsb.fi feeder already present"
  fi

  if [[ -z ${ADSBFI_UUID:-} && -s $ADSBFI_PATH/adsbfi-uuid ]]; then
    ADSBFI_UUID="$(cat "$ADSBFI_PATH/adsbfi-uuid")"
    conf_write "$CONF"
    echo "recorded the new adsb.fi uuid in $CONF"
  fi

  echo "writing /etc/default/adsbfi"
  render_adsbfi >/etc/default/adsbfi
  systemctl restart adsbfi-feed adsbfi-mlat
  # Not swallowed, same as the ADSBExchange enable above.
  systemctl enable adsbfi-feed adsbfi-mlat >/dev/null
else
  echo "adsb.fi: ADSBFI_USER is blank — not feeding adsb.fi"
fi

# --- Flightradar24 ---------------------------------------------------------
# --- AeroDataBox ------------------------------------------------------------
# Opt-in. The feed itself is a connector on the main readsb, rendered by
# stage 30 (see render_readsb); all that lives here is their MLAT client.
# install.sh has already minted AERODATABOX_UUID by the time this runs.
if [[ -n ${AERODATABOX_USER:-} ]]; then
  ensure_ntp_daemon

  mkdir -p /usr/local/share/aerodatabox
  printf '%s' "$AERODATABOX_UUID" >/usr/local/share/aerodatabox/aerodatabox-uuid
  chmod 0644 /usr/local/share/aerodatabox/aerodatabox-uuid

  echo "writing /etc/default/aerodatabox-mlat"
  render_aerodatabox_mlat >/etc/default/aerodatabox-mlat
  install -m 0644 "$SRC_DIR/files/aerodatabox-mlat.service" \
                  /etc/systemd/system/aerodatabox-mlat.service
  systemctl daemon-reload
  systemctl restart aerodatabox-mlat
  systemctl enable aerodatabox-mlat >/dev/null
else
  echo "AeroDataBox: AERODATABOX_USER is blank — not feeding AeroDataBox"
  # Switching a site off must actually stop it: readsb's connector goes with
  # the next render, but nothing else would ever remove this unit.
  if [[ -f /etc/systemd/system/aerodatabox-mlat.service ]]; then
    systemctl disable --now aerodatabox-mlat >/dev/null
    rm -f /etc/systemd/system/aerodatabox-mlat.service
    systemctl daemon-reload
  fi
fi

if ! command -v fr24feed >/dev/null 2>&1; then
  echo "adding the Flightradar24 apt repository"
  install -d -m 0755 /etc/apt/keyrings
  # -f here too: gpg --dearmor already fails loudly on a non-armored body
  # (a 404 page), but -f turns that into "curl: (22) The requested URL
  # returned error: 404" instead of gpg's less specific "no valid OpenPGP
  # data found".
  #
  # --yes: this whole block only re-enters while `fr24feed` is still missing
  # from PATH, which is exactly the state a retry after a failed `apt-get
  # install` (network blip, package hiccup) leaves behind — with the keyring
  # already written from the prior attempt. Without --yes, gpg refuses to
  # overwrite an existing file and prompts on stdin instead, which install.sh
  # leaves connected to the terminal for the wizard; that prompt is now
  # buried in teed log output and the stage hangs rather than converging.
  # FR24-Repository-Signing-Key.gpg is gone — it 404s, and because curl -s
  # swallows the message, the only symptom was gpg saying "no valid OpenPGP
  # data found" about an empty stdin. Worse, `-o` had already created
  # /etc/apt/keyrings/flightradar24.gpg at zero bytes before gpg gave up, so
  # the retry inherited a broken keyring. Collected into a variable first and
  # written only once there is something to write, the same reasoning that put
  # fetch_and_run in 30-readsb.sh.
  #
  # Keys are gathered rather than picked. FR24 publishes a year-stamped file
  # and an unversioned one, and they are not interchangeable: on trixie, apt
  # verifies with sqv, which rejects the older keys outright —
  #
  #   Policy rejected non-revocation signature (SubkeyBinding) ...
  #   because: SHA1 is not considered secure since 2026-02-01
  #   Missing key ED843290A602413685E57D436F7703F65FA1BDAF
  #
  # — and that key appears only in flightradar24.2026.pub, not in the
  # unversioned flightradar24.pub. So the unversioned name alone fails on
  # trixie today, and the year-stamped name alone rots every January. Taking
  # the union of whatever is published leaves apt to choose a signature it
  # will accept, and keeps working across the next rotation without an edit.
  fr24_year="$(date +%Y)"
  fr24_keys=""
  for key_url in \
    "https://repo-feed.flightradar24.com/flightradar24.${fr24_year}.pub" \
    "https://repo-feed.flightradar24.com/flightradar24.$((fr24_year - 1)).pub" \
    "https://repo-feed.flightradar24.com/flightradar24.pub"; do
    if key_part="$(curl -sfL "$key_url")"; then
      fr24_keys+="$key_part"$'\n'
      echo "  signing key: ${key_url##*/}"
    fi
  done
  if [[ -z $fr24_keys ]]; then
    echo "could not download any Flightradar24 signing key" >&2
    echo "tried the ${fr24_year}, $((fr24_year - 1)) and unversioned names at" >&2
    echo "https://repo-feed.flightradar24.com/ — check whether they have" >&2
    echo "renamed it again, and check network access." >&2
    exit 1
  fi
  printf '%s' "$fr24_keys" | gpg --yes --dearmor -o /etc/apt/keyrings/flightradar24.gpg
  echo "deb [signed-by=/etc/apt/keyrings/flightradar24.gpg] https://repo-feed.flightradar24.com flightradar24 raspberrypi-stable" \
    >/etc/apt/sources.list.d/flightradar24.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq fr24feed
else
  echo "fr24feed already present: $(fr24feed --version 2>&1 | head -1)"
fi

echo "writing /etc/fr24feed.ini"
# fr24feed's systemd unit runs it as User=fr24, not root, so the file only
# needs to be readable by that user's group — not world-readable. Resolve the
# actual group rather than assuming its name matches the username: if a
# 'fr24' group exists use it, else fall back to the fr24 user's real primary
# group, else the package has not actually finished installing and this
# should fail here rather than fall back to a world-readable file to route
# around the problem.
if getent group fr24 >/dev/null 2>&1; then
  fr24_group=fr24
elif id -u fr24 >/dev/null 2>&1; then
  fr24_group="$(id -gn fr24)"
else
  echo "the fr24 user does not exist — expected it from fr24feed's package" >&2
  echo "install. check: dpkg -s fr24feed" >&2
  exit 1
fi
# umask 077 covers the window between create and the explicit chmod below,
# which is the permanent mode.
umask 077
render_fr24 >/etc/fr24feed.ini
chown "root:$fr24_group" /etc/fr24feed.ini
chmod 0640 /etc/fr24feed.ini
umask 022

fr24feed --validate-config --config-file=/etc/fr24feed.ini >/dev/null || {
  echo "fr24feed rejected the config. Is FR24_KEY correct?" >&2; exit 1; }
systemctl restart fr24feed
systemctl enable fr24feed >/dev/null

# Built from what actually ran rather than spelled out per combination: with
# two independent opt-ins there are four sentences to keep in step, and the
# one that goes stale is the one nobody is feeding when they read it.
configured=(adsbexchange)
[[ -n ${ADSBLOL_USER:-} ]] && configured+=(adsb.lol)
[[ -n ${ADSBFI_USER:-} ]] && configured+=(adsb.fi)
[[ -n ${AERODATABOX_USER:-} ]] && configured+=(AeroDataBox)
configured+=(fr24feed)
# Not "${configured[*]}" with IFS=' + ': ${array[*]} joins on the *first
# character* of IFS, so that produces a plain space-separated list and looks
# like it worked.
printf -v feeder_list '%s + ' "${configured[@]}"
echo "feeders: ${feeder_list% + } configured"
