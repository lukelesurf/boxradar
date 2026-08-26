#!/usr/bin/env bash
# Turn a general-purpose OS into a receiver appliance.
#
# Each item here is a drift the hand-built receiver had: no persistent journal,
# so its three-hourly reboots were undebuggable; no firewall despite ufw being
# installed; and a */5 cron re-running iwconfig because NetworkManager kept
# putting wifi power-save back.
set -euo pipefail

echo "hostname -> $HOSTNAME"
hostnamectl set-hostname "$HOSTNAME"
# 127.0.1.1 must track the hostname or sudo warns on every invocation.
if grep -q '^127\.0\.1\.1' /etc/hosts; then
  # Unescaped interpolation into a sed replacement is safe only because
  # conf_validate already restricts HOSTNAME to [a-z0-9-]: no /, & or
  # backslash can reach here. A future loosening of that regex needs to
  # revisit this line too.
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts
else
  printf '127.0.1.1\t%s\n' "$HOSTNAME" >>/etc/hosts
fi

apt-get update -qq
# dphys-swapfile is installed explicitly rather than assumed: bookworm's
# Raspberry Pi OS image ships it, trixie's does not — that image uses
# systemd-zram-generator instead, and /etc/dphys-swapfile simply is not there.
# The swap block below was guarded on that file existing, so on trixie it
# silently did nothing. zram is compressed RAM, not disk, so it buys very
# little against the one allocation this box actually has to survive (see
# below); a real swapfile is still wanted. Installing the package here is what
# makes the block reachable on both releases.
# git is listed because 40-feeders.sh clones the ADSBExchange feedclient
# itself. It used to arrive as a side effect of their feed.sh bootstrap, which
# apt-installed git/wget/unzip before cloning; that bootstrap is no longer
# called, so nothing else guarantees git on a bare Lite image.
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  avahi-daemon ufw unattended-upgrades bc curl dphys-swapfile git

# Persistent journal. Without this, logs live in /run and vanish on reboot —
# which is precisely when you want them.
mkdir -p /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/boxradar.conf <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=200M
EOF
mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal >/dev/null 2>&1 || true
systemctl restart systemd-journald

# Wifi power-save off, via NetworkManager rather than a cron that fights it.
# 2 = disable.
mkdir -p /etc/NetworkManager/conf.d
cat >/etc/NetworkManager/conf.d/boxradar-wifi-powersave.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF

# Swap. Raspberry Pi OS defaults to 100MB, which is not enough headroom for
# the 367MB peak when the configuration UI reduces a coastline for a new area.
# 512MB costs nothing on an 8GB+ card and keeps a 1GB board off the OOM killer
# during the one step that needs the memory. 1GB is not hypothetical: the Pi 4
# Model B ships in a 1GB variant, and that is the board this was first run on.
#
# Not a `[[ -e ]]` guard any more. The file comes from the package installed
# above, so by here it must exist — and the guard's failure mode was the worst
# available one: absent file, block skipped, stage reports success, and the
# shortfall surfaces hours later as an OOM kill during the coastline build,
# nowhere near the thing that caused it. Fail here instead.
if [[ ! -e /etc/dphys-swapfile ]]; then
  echo "/etc/dphys-swapfile is missing even though the package installed" >&2
  echo "check: dpkg -s dphys-swapfile" >&2
  exit 1
fi
# A fresh install of the package leaves CONF_SWAPSIZE commented out, so this
# awk yields the empty string rather than a number — hence ${current:-0}, and
# hence the `grep -q || echo >>` fallback below, which is what actually adds
# the line when sed's ^CONF_SWAPSIZE= pattern matches nothing.
current=$(awk -F= '/^CONF_SWAPSIZE/ {print $2}' /etc/dphys-swapfile)
if [[ ${current:-0} -lt 512 ]]; then
  echo "swap ${current:-0}MB -> 512MB"
  sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=512/' /etc/dphys-swapfile
  grep -q '^CONF_SWAPSIZE' /etc/dphys-swapfile || \
    echo 'CONF_SWAPSIZE=512' >>/etc/dphys-swapfile
  # On trixie this coexists with systemd-zram-generator rather than replacing
  # it: zram0 keeps priority 100 and the swapfile lands lower, so the kernel
  # fills compressed RAM first and spills to disk only when that is not
  # enough. That ordering is what we want, and needs nothing done to it.
  systemctl restart dphys-swapfile
else
  echo "swap already ${current}MB"
fi

# Any inherited reboot cron is removed. A receiver that reboots on a timer is
# hiding a fault, not fixing one.
#
# Captured once, then matched twice, rather than `crontab -l | grep -q` as
# the condition: grep -q exits the instant it matches, closing the pipe
# while crontab may still be writing later lines. Under pipefail that
# SIGPIPE is what the pipeline reports as its exit status, not grep's — so
# `if` takes the else branch precisely when the reboot line *is* present,
# and this stage silently reports success while the three-hourly reboot
# survives. It "works" on a short crontab today only because crontab -l
# finishes writing before grep -q gets a chance to close the pipe; it is
# not guaranteed to keep working as root's crontab grows. `|| true` belongs
# on this capture (crontab -l legitimately fails with no crontab at all,
# the common case on a fresh box) — not on the match below.
cron_content="$(crontab -l 2>/dev/null || true)"
if grep -q 'shutdown -r' <<<"$cron_content"; then
  echo "removing a scheduled reboot from root's crontab"
  tmp=$(mktemp)
  # grep exits 1 when the reboot line is the *only* line, since -v then
  # selects nothing — that is success here, not failure, so it alone is
  # tolerated. The write below is not: a failed `crontab "$tmp"` must abort
  # the stage rather than report success while the reboot cron survives.
  grep -v 'shutdown -r' <<<"$cron_content" >"$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
fi

echo "configuring ufw"
# `--force reset` discards whatever rules are already there before laying
# down the set below. That makes re-running this stage converge on exactly
# the declared rules rather than accumulate `ufw allow` duplicates across
# runs — the idempotency contract for this block, not an oversight.
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
for port in 22 80 8081 8082 8754; do ufw allow "$port/tcp" >/dev/null; done
# tar1090's optional second instance. Only opened if it is configured.
if [[ -e /etc/lighttpd/conf-enabled/95-tar1090-otherport.conf ]]; then
  ufw allow 8504/tcp >/dev/null
fi
ufw --force enable >/dev/null
# Same shape as the fixes above (head -1 can close the pipe on ufw while it
# is still writing later rule lines), just cosmetic here: embedded inside a
# larger command substitution rather than a bare assignment, a SIGPIPE'd
# `ufw` cannot trip `set -e`, so at worst this prints a blank status line —
# but there is no reason to leave the pattern sitting here for the next
# person to copy.
ufw_status="$(ufw status || true)"
echo "ufw: $(head -1 <<<"$ufw_status")"

# Security updates only. This box may be in a house you cannot reach.
cat >/etc/apt/apt.conf.d/51boxradar-unattended <<'EOF'
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename},label=Debian-Security";
        "origin=Raspbian,codename=${distro_codename},label=Raspbian";
};
Unattended-Upgrade::Automatic-Reboot "false";
EOF
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades >/dev/null

if [[ -n ${STATIC_IP:-} ]]; then
  # The connection carrying the default route is the one actually in use.
  # "First active connection" would put the address on Ethernet for a box
  # that is really on wifi (or vice versa) on a Pi with both up — plausible
  # for exactly the box someone wants a static address on — and report
  # success while networking is silently wrong.
  #
  # Captured first, then matched: piping straight from `ip`/`nmcli` into an
  # awk that `exit`s after one line (the first line here; the first match
  # in the nmcli case) closes the pipe before the upstream command is
  # guaranteed to have finished writing — on a box with more than one
  # default route or more than one active connection, that upstream can
  # still SIGPIPE. Under pipefail that reports as pipeline failure, and
  # `conn=$(...)` was a bare `[[ ... ]] &&` statement at the top level, so
  # that failure would abort the whole script right here under `set -e`,
  # before the friendly diagnostic below ever ran. Same shape as the
  # crontab and MLAT-peer fixes elsewhere in this round; `|| true` on each
  # capture, never on the match.
  route_out="$(ip -4 route show default || true)"
  dev="$(awk '{print $5; exit}' <<<"$route_out")"
  # Field 3 of "default via <gw> dev <dev> ...". The gateway and the resolvers
  # are read from the DHCP lease that is live *right now*, because switching
  # ipv4.method to manual discards that lease and nothing else supplies them.
  # Setting ipv4.addresses alone left the box with an address, no default route
  # and no DNS — and since it still answered on the LAN, the breakage looked
  # like nothing at all until the first feeder connection or apt run. All three
  # go on in one `nmcli con mod` below.
  gw="$(awk '{print $3; exit}' <<<"$route_out")"
  conn=""
  dns=""
  if [[ -n $dev ]]; then
    active_conns="$(nmcli -t -f NAME,DEVICE connection show --active || true)"
    conn="$(awk -F: -v d="$dev" '$2 == d { print $1; exit }' <<<"$active_conns")"
    # One resolver per line from -g; ipv4.dns wants them comma-separated.
    # Same capture-then-match shape as above: the awk consumes all of it, so
    # nothing can SIGPIPE nmcli mid-write.
    dns_out="$(nmcli -g IP4.DNS device show "$dev" || true)"
    dns="$(awk 'NF { out = out sep $0; sep = "," } END { print out }' <<<"$dns_out")"
  fi
  if [[ -z $conn ]]; then
    echo "cannot determine which connection to give $STATIC_IP" >&2
    echo "active connections:" >&2
    nmcli -t -f NAME,DEVICE connection show --active >&2
    echo "set it by hand with: nmcli connection modify <name> \\" >&2
    echo "  ipv4.method manual ipv4.addresses $STATIC_IP \\" >&2
    echo "  ipv4.gateway <gateway> ipv4.dns <resolver>" >&2
    exit 1
  fi
  # Refused rather than half-applied. Writing the address without these is the
  # exact silent breakage described above, and "no default route" is not a
  # state worth reaching by accident — better to stop with the box still on a
  # working DHCP lease and let someone decide.
  if [[ -z $gw || -z $dns ]]; then
    missing=""
    [[ -z $gw ]] && missing="gateway"
    [[ -z $dns ]] && missing="${missing:+$missing and }resolver"
    echo "refusing to set $STATIC_IP: no $missing found" >&2
    echo "current default route: ${route_out:-<none>}" >&2
    echo "resolvers seen on $dev: ${dns:-<none>}" >&2
    echo "setting the address without both would leave this box with no" >&2
    echo "default route or no DNS, which looks healthy from the LAN but" >&2
    echo "breaks the feeders and apt. Set all three by hand, or leave" >&2
    echo "STATIC_IP blank and use a DHCP reservation instead." >&2
    exit 1
  fi
  echo "setting static IP $STATIC_IP on '$conn' ($dev), gw $gw, dns $dns"
  nmcli connection modify "$conn" \
    ipv4.method manual \
    ipv4.addresses "$STATIC_IP" \
    ipv4.gateway "$gw" \
    ipv4.dns "$dns"
  echo "NOTE: the address changes on the next reboot or reconnect."
fi

echo "os: hostname=$HOSTNAME, journal persistent, ufw enabled"
