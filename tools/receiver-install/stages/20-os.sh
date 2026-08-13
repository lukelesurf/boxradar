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
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  avahi-daemon ufw unattended-upgrades bc curl

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
# during the one step that needs the memory.
if [[ -e /etc/dphys-swapfile ]]; then
  current=$(awk -F= '/^CONF_SWAPSIZE/ {print $2}' /etc/dphys-swapfile)
  if [[ ${current:-0} -lt 512 ]]; then
    echo "swap ${current:-0}MB -> 512MB"
    sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=512/' /etc/dphys-swapfile
    grep -q '^CONF_SWAPSIZE' /etc/dphys-swapfile || \
      echo 'CONF_SWAPSIZE=512' >>/etc/dphys-swapfile
    systemctl restart dphys-swapfile
  else
    echo "swap already ${current}MB"
  fi
fi

# Any inherited reboot cron is removed. A receiver that reboots on a timer is
# hiding a fault, not fixing one.
if crontab -l 2>/dev/null | grep -q 'shutdown -r'; then
  echo "removing a scheduled reboot from root's crontab"
  tmp=$(mktemp)
  # grep exits 1 when the reboot line is the *only* line, since -v then
  # selects nothing — that is success here, not failure, so it alone is
  # tolerated. The write below is not: a failed `crontab "$tmp"` must abort
  # the stage rather than report success while the reboot cron survives.
  crontab -l 2>/dev/null | grep -v 'shutdown -r' >"$tmp" || true
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
echo "ufw: $(ufw status | head -1)"

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
  dev="$(ip -4 route show default | awk '{print $5; exit}')"
  conn=""
  [[ -n $dev ]] && conn="$(nmcli -t -f NAME,DEVICE connection show --active \
                            | awk -F: -v d="$dev" '$2 == d { print $1; exit }')"
  if [[ -z $conn ]]; then
    echo "cannot determine which connection to give $STATIC_IP" >&2
    echo "active connections:" >&2
    nmcli -t -f NAME,DEVICE connection show --active >&2
    echo "set it by hand with: nmcli connection modify <name> \\" >&2
    echo "  ipv4.method manual ipv4.addresses $STATIC_IP" >&2
    exit 1
  fi
  echo "setting static IP $STATIC_IP on '$conn' ($dev)"
  nmcli connection modify "$conn" ipv4.method manual ipv4.addresses "$STATIC_IP"
  echo "NOTE: the address changes on the next reboot or reconnect."
fi

echo "os: hostname=$HOSTNAME, journal persistent, ufw enabled"
