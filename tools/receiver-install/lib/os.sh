#!/usr/bin/env bash
# OS-level settings for 20-os.sh, kept here so they are testable off-box.

GAI_BEGIN="# BEGIN boxradar: prefer IPv4"
GAI_END="# END boxradar"

# Make getaddrinfo prefer IPv4, in a marked block of $1 that re-runs replace.
#
# adsb.lol's /0/me and re-api, and adsb.fi's /v2/snapshot, authorise by source
# IP. Over IPv6 the receiver presents its own address, which nothing else on
# the LAN shares; over IPv4 it presents the NATed address the home server also
# uses. readsb and mlat-client have no -4 flag and feed.adsb.lol round-robins,
# so this is the only lever that covers every feeder at once.
#
# glibc discards its entire built-in table as soon as one precedence line
# exists, so the full RFC 6724 table is restated with ::ffff:0:0/96 on top.
gai_prefer_ipv4() {
  local path=$1 tmp
  tmp="$(mktemp "${path}.XXXXXX")"
  if [[ -e $path ]]; then
    awk -v b="$GAI_BEGIN" -v e="$GAI_END" \
      '$0 == b { skip = 1; next } $0 == e { skip = 0; next } !skip' \
      "$path" >"$tmp"
  fi
  cat >>"$tmp" <<EOF
$GAI_BEGIN
# Written by tools/receiver-install stage 20; see lib/os.sh for why.
precedence ::1/128       50
precedence ::/0          40
precedence ::ffff:0:0/96 100
precedence 2002::/16     30
precedence 2001::/32      5
precedence fc00::/7       3
precedence ::/96          1
precedence fec0::/10      1
precedence 3ffe::/16      1
$GAI_END
EOF
  chmod 0644 "$tmp"
  mv "$tmp" "$path"
}
