#!/usr/bin/env bash
# Prove the chain rather than announce success.
#
# Every check below corresponds to something that has silently failed on a
# hand-built receiver: MLAT with no return port, a METAR proxy that starts but
# cannot reach upstream, a feeder that installs but never connects.
set -euo pipefail

pass() { echo "  ok    $*"; }
fail() { echo "  FAIL  $*" >&2; FAILED=1; }
warn() { echo "  warn  $*"; }
FAILED=0

echo "verifying:"

# --- readsb ---------------------------------------------------------------
# `stats=$(...); then` rather than `stats=$(...) && pass || fail`: the latter
# is shellcheck SC2015 (A && B || C is not if-then-else — C also runs if B
# itself fails). The position check below is nested inside this branch
# rather than gated on its own `[[ -n $stats ]]`, for the same reason: `-f`
# only treats 4xx/5xx as failure, so a curl that "succeeds" against a 3xx
# redirect (as happened testing this off-target, against an unrelated
# reverse proxy on :80) would otherwise leave $stats empty and silently skip
# the position check instead of failing it — a gap in exactly the coverage
# this stage exists to provide.
if stats=$(curl -sf --max-time 10 http://127.0.0.1/tar1090/data/stats.json); then
  pass "tar1090 is serving readsb stats"

  # total.position_count_by_type is the field that answers "is this
  # working" — see docs/receiver-pi.md. It is cumulative since readsb
  # started and covers every position source (adsb_icao, mlat, ...), so a
  # non-zero sum proves both that the SDR is decoding and that at least one
  # source is producing fixes. (aircraft_count_by_type looks like the
  # obvious field to reach for instead, but this readsb build leaves it
  # absent — it reads back as None — so it cannot be used here. An empty or
  # unparsable body, e.g. from the redirect case above, sums to zero the
  # same as a genuinely quiet receiver, and fails the same way.)
  # Broad except, not just (ValueError, KeyError): readsb's JSON shape is
  # exactly the kind of thing that has already surprised this project once
  # (aircraft_count_by_type reading back as None on this build — see the
  # comment below). "total" present but not a dict, or position_count_by_type
  # present but not a mapping, are schema surprises this stage should report
  # as "no positions decoded", not crash on — a crash here under `set -e`
  # would abort the script and skip every check after it, including the ones
  # that matter more (MLAT port, the feeders).
  positions=$(printf '%s' "$stats" | python3 -c \
    'import json,sys
try:
    total = json.load(sys.stdin)["total"]
    counts = total.get("position_count_by_type") or {}
    n = int(sum(counts.values()))
except Exception:
    n = 0
print(n)')
  if (( positions > 0 )); then
    pass "readsb has decoded $positions position(s)"
  else
    fail "readsb has decoded no positions — aerial connected?"
  fi
else
  fail "cannot read tar1090/data/stats.json"
fi

# --- MLAT return path -------------------------------------------------------
# --net-bi-port 30104 is what lets mlat-client return results. Without it MLAT
# does not error, it just never appears. Matched against the local
# address:port column only (not the whole line), anchored on the end, so a
# coincidental 30104 in a queue-length column can't produce a false pass.
if ss -tln 2>/dev/null | awk '{print $4}' | grep -q ':30104$'; then
  pass "MLAT return port 30104 is listening"
else
  fail "port 30104 is not listening — MLAT results have nowhere to go"
fi

# --- boxradar services ------------------------------------------------------
if curl -sf --max-time 10 http://127.0.0.1:8081/healthz >/dev/null; then
  pass "boxradar-site is healthy"
else
  fail "boxradar-site /healthz failed"
fi
if curl -sf --max-time 10 http://127.0.0.1:8082/healthz >/dev/null; then
  pass "boxradar-config is healthy"
else
  fail "boxradar-config /healthz failed"
fi

metar=$(curl -sf --max-time 20 "http://127.0.0.1:8081/metar/${METAR_STATION}" || true)
if printf '%s' "$metar" | grep -q '"stations"'; then
  pass "METAR for $METAR_STATION is being served"
else
  fail "no METAR for $METAR_STATION — check the ICAO and outbound HTTPS"
fi

if curl -sf --max-time 10 "http://127.0.0.1:8081/contacts?lat=0&lon=0&n=1" >/dev/null; then
  pass "the contact feed answers"
else
  fail "the contact feed does not answer"
fi

# --- feeders ------------------------------------------------------------
if systemctl is-active --quiet fr24feed; then
  status=$(curl -sf --max-time 10 http://127.0.0.1:8754/monitor.json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("feed_status","?"))' \
    2>/dev/null || echo "?")
  if [[ $status == connected ]]; then
    pass "FR24 is connected"
  else
    warn "FR24 status is '$status' (may still be connecting)"
  fi
else
  fail "fr24feed is not running"
fi

if systemctl is-active --quiet adsbexchange-feed; then
  pass "the ADSBExchange feeder is running"
else
  fail "adsbexchange-feed is not running"
fi

# MLAT synchronisation takes minutes and depends on neighbouring receivers, so
# this warns rather than fails on a box that has only just come up.
if systemctl is-active --quiet adsbexchange-mlat; then
  if journalctl -u adsbexchange-mlat -n 50 --no-pager 2>/dev/null \
     | grep -q 'peer_count'; then
    pass "mlat-client has peers"
  else
    warn "mlat-client has no peers yet — normal for the first few minutes"
  fi
else
  fail "adsbexchange-mlat is not running"
fi

(( FAILED == 0 )) || { echo; echo "verification failed. see $0" >&2; exit 1; }

# `|| true`, matching the $metar pattern above: reached only once every check
# has already passed, so a `hostname -I` hiccup right here should not turn a
# genuinely working receiver into a bare-error exit — it should just print
# the URLs with whatever (possibly empty) address it got.
ip=$(hostname -I | awk '{print $1}') || true
cat <<EOF

BOXRADAR receiver ready.

  radar map          http://${ip}/tar1090/
  configure the map  http://${ip}:8082/      <- pick your airspace here
  feed for the board http://${ip}:8081/contacts
  FR24 status        http://${ip}:8754/

The display shows no geography until a map is published from the
configuration UI. That step needs local knowledge of which controlled
airspace matters near you, so it is not automated.
EOF
