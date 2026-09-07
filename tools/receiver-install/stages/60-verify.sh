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

  # total.position_count_by_type, not total.messages: both fields genuinely
  # exist in readsb's stats.json (confirmed on the live receiver —
  # total.messages was present and climbing, e.g. 6868511), so this is not
  # a missing-field workaround. position_count_by_type is used because it
  # is the field docs/receiver-pi.md documents as answering "is this
  # working": cumulative since readsb started, and broken down by source,
  # so a non-zero sum proves a position was actually solved, and which kind
  # (adsb_icao, mlat, ...) it came from. A raw message count can climb on
  # noise and repeated frames alone and says nothing about whether any
  # position was ever produced. (aircraft_count_by_type looks like the
  # obvious field to reach for instead of either, but this readsb build
  # leaves it absent — it reads back as None — so it cannot be used here.
  # An empty or unparsable body, e.g. from the redirect case above, sums to
  # zero the same as a genuinely quiet receiver, and fails the same way.)
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

# --- the aircraft database --------------------------------------------------
# A receiver with no --db-file decodes flawlessly and reports every aircraft
# with no type, registration or operator. Nothing upstream complains, and the
# one place an operator would look — the tar1090 map — still shows both,
# because the browser holds its own copy. Only the JSON does not, and only
# BOXRADAR reads the JSON. This shipped once already.
#
# Asked of live traffic rather than by testing for the file: a file that
# exists but is the wrong format, or is truncated, fails identically from
# here, and it is what readsb actually resolved that matters.
if feed=$(curl -sf --max-time 10 http://127.0.0.1/tar1090/data/aircraft.json); then
  # Same broad except and same reasoning as the stats parse above: a schema
  # surprise should report as "no types" and let the remaining checks run,
  # not abort the stage under set -e.
  counts=$(printf '%s' "$feed" | python3 -c \
    'import json,sys
try:
    ac = json.load(sys.stdin)["aircraft"]
except Exception:
    ac = []
print(len(ac), sum(1 for a in ac if a.get("t")))')
  read -r seen with_type <<<"$counts"
  if (( with_type > 0 )); then
    pass "the aircraft database is loaded ($with_type of $seen have a type)"
  elif (( seen == 0 )); then
    # Absence only means anything when there is traffic to be absent from.
    warn "nothing in range — cannot confirm the aircraft database"
  else
    # Not every hex is in the table, but zero out of a skyful is the database
    # missing, not a run of unlisted airframes.
    fail "$seen aircraft and not one type — readsb's --db-file did not load"
  fi
else
  fail "cannot read tar1090/data/aircraft.json"
fi

# --- MLAT return path -------------------------------------------------------
# --net-bi-port 30104 is what lets mlat-client return results. Without it MLAT
# does not error, it just never appears. Matched against the local
# address:port column only (not the whole line), anchored on the end, so a
# coincidental 30104 in a queue-length column can't produce a false pass.
#
# Captured first, then matched with no live pipe into grep -q: `ss | awk |
# grep -q` would let grep -q close the pipe the instant it matches, and
# under pipefail a SIGPIPE'd upstream (ss or awk, still writing on a box
# with many listening sockets) reports as pipeline failure — inverting this
# check exactly when the port *is* listening. See the mlat-client peer
# check below, which hit this for real on the live receiver.
listeners="$(ss -tln 2>/dev/null || true)"
ports="$(awk '{print $4}' <<<"$listeners")"
if grep -q ':30104$' <<<"$ports"; then
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
# $metar is already fully captured above (curl has exited), so matching
# against it with a herestring rather than piping it into grep -q avoids
# even the in-memory version of the same pipefail/SIGPIPE hazard the port
# check above and the MLAT-peer check further below were fixed for — there
# is no live producer left that could be signalled.
if grep -q '"stations"' <<<"$metar"; then
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
  # Fetched once and parsed once, rather than a curl per field: the two MLAT
  # fields only mean anything read together, and a second request could
  # straddle a state change and report a combination that never existed.
  monitor="$(curl -sf --max-time 10 http://127.0.0.1:8754/monitor.json || true)"
  # Broad except and a herestring, for the same two reasons as the readsb
  # parses above: a shape surprise should read back as "?" and let the rest
  # of the stage run rather than abort it under set -e, and nothing is left
  # writing into a pipe that an early reader exit could SIGPIPE.
  fields="$(python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
print(d.get("feed_status") or "?")
print(d.get("mlat-ok") or "?")
print(d.get("mlat_problem") or "none")' <<<"$monitor")"
  { read -r status; read -r mlat_ok; read -r mlat_problem; } <<<"$fields"

  if [[ $status == connected ]]; then
    pass "FR24 is connected"
  else
    warn "FR24 status is '$status' (may still be connecting)"
  fi

  # feed_status is not evidence about MLAT. The live receiver reported
  # "connected" for months while contributing nothing to MLAT at all, because
  # fr24feed.ini asked for MLAT (mlat="yes", mlat-without-gps="yes") and never
  # gave it a position — and mlat-started reads "YES" throughout, since the
  # thread does start before discovering it has nothing to work with. Only
  # these two fields tell the truth.
  case "$mlat_ok:$mlat_problem" in
    YES:*)
      pass "FR24 MLAT is contributing" ;;
    *:no-config)
      # The one MLAT verdict this installer owns: it means the fr24feed.ini
      # rendered by render_fr24 is missing latitude/longitude/altitude. That
      # is our bug, on our file, so it fails rather than warns.
      fail "FR24 MLAT has no position — latitude/longitude/altitude missing from /etc/fr24feed.ini" ;;
    NOT-PERMITTED:*)
      # Server-side. FR24 downloads a per-receiver configuration at startup
      # ("[feed][i]Downloading configuration") and MLAT permission comes down
      # with it, so no amount of local configuration changes this one.
      warn "FR24 has MLAT disabled for this key ($mlat_problem) — enable it on the FR24 account; nothing on this box can" ;;
    *)
      # Includes the first minutes after a restart, where mlat-ok is still
      # "NO" with no problem recorded because the thread has not finished
      # negotiating yet.
      warn "FR24 MLAT is '$mlat_ok' (problem: $mlat_problem) — may still be starting" ;;
  esac
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
  # Captured first, then matched, not `journalctl | grep -q`: grep -q exits
  # the instant it matches, closing the pipe while journalctl may still be
  # writing the rest of the 50 lines. Under pipefail that SIGPIPE (rc 141)
  # is what the pipeline reports as its exit status, not grep's — so `if`
  # takes the *else* branch precisely when peer_count *is* present. Caught
  # against the live receiver: 10 peer_count lines and 78 synced peers, but
  # this check still reported "no peers yet" until fixed.
  mlat_log="$(journalctl -u adsbexchange-mlat -n 50 --no-pager 2>/dev/null || true)"
  if grep -q 'peer_count' <<<"$mlat_log"; then
    pass "mlat-client has peers"
  else
    warn "mlat-client has no peers yet — normal for the first few minutes"
  fi
else
  fail "adsbexchange-mlat is not running"
fi

# --- adsb.lol -------------------------------------------------------------
# Only checked when this site feeds them at all. Absent ADSBLOL_USER, the
# stage installed nothing and there is nothing here to be wrong.
if [[ -n ${ADSBLOL_USER:-} ]]; then
  if systemctl is-active --quiet adsblol-feed; then
    pass "the adsb.lol feeder is running"
  else
    fail "adsblol-feed is not running"
  fi
  if systemctl is-active --quiet adsblol-mlat; then
    # Same capture-then-match discipline as the mlat-client check above, and
    # for the same SIGPIPE reason. "Results:" rather than peer_count: their
    # mlat-client fork reports "Results:  N positions/minute", which is the
    # line that proves MLAT solutions are actually coming back — 132.9/min
    # within a minute of the first install on the live receiver.
    lol_log="$(journalctl -u adsblol-mlat -n 50 --no-pager 2>/dev/null || true)"
    if grep -q 'positions/minute' <<<"$lol_log"; then
      pass "adsb.lol MLAT is returning positions"
    else
      warn "no adsb.lol MLAT results yet — normal for the first few minutes"
    fi
  else
    fail "adsblol-mlat is not running"
  fi

  # The reason for feeding them, from this project's point of view. A 200 here
  # proves the source-IP authorisation actually took, which is not something
  # the feeder's own status can tell you. Warn, not fail: it depends on
  # outbound HTTPS and on adsb.lol having registered the station, which lags
  # the first feed by a few minutes.
  if curl -sf --max-time 15 "https://re-api.adsb.lol/?circle=${LAT},${LON},10" >/dev/null; then
    pass "re-api.adsb.lol answers this station"
  else
    warn "re-api.adsb.lol did not answer — it authorises by source IP and can lag the first feed"
  fi
fi

# --- adsb.fi ---------------------------------------------------------------
# Only checked when this site feeds them, same as adsb.lol above.
if [[ -n ${ADSBFI_USER:-} ]]; then
  if systemctl is-active --quiet adsbfi-feed; then
    pass "the adsb.fi feeder is running"
  else
    fail "adsbfi-feed is not running"
  fi
  if systemctl is-active --quiet adsbfi-mlat; then
    # Same capture-then-match discipline and the same "positions/minute"
    # marker as the adsb.lol check: it is the same mlat-client fork.
    fi_log="$(journalctl -u adsbfi-mlat -n 50 --no-pager 2>/dev/null || true)"
    if grep -q 'positions/minute' <<<"$fi_log"; then
      pass "adsb.fi MLAT is returning positions"
    else
      warn "no adsb.fi MLAT results yet — normal for the first few minutes"
    fi
  else
    fail "adsbfi-mlat is not running"
  fi

  # The point of feeding them, from this project's side: /v2/snapshot is
  # open only to feeder IPs. A 200 proves the source-IP authorisation took,
  # which nothing on the receiver itself can tell you.
  #
  # Exactly one request, no retry. The feeder endpoint is rate limited to one
  # request per 30 seconds and a 403 counts against that limit, so a check
  # that politely retried would be the thing keeping itself locked out.
  #
  # --max-filesize caps the body at 64KB: the snapshot is every aircraft the
  # network can see and runs to megabytes, and none of it is wanted here.
  # curl aborts mid-transfer with exit 63 once the cap is passed, which is why
  # this reads %{http_code} instead of relying on -f — and why the `|| true`
  # is not hiding anything. Verified against the live endpoint: exit 63 still
  # emits the status code.
  #
  # 403 and 000 are reported apart on purpose. 403 is the expected answer for
  # the first few minutes and means the feed simply has not registered yet;
  # 000 means curl never got an answer at all, which is a network problem and
  # worth different words. `curl -f` collapses both into one exit status,
  # which is why the re-api check above can only say "did not answer".
  fi_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
    --max-filesize 65536 "https://opendata.adsb.fi/api/v2/snapshot" || true)"
  case "$fi_code" in
    200) pass "opendata.adsb.fi/v2/snapshot answers this station" ;;
    403) warn "adsb.fi has not authorised this IP yet — it can lag the first feed by a few minutes" ;;
    *)   warn "opendata.adsb.fi did not answer (HTTP '${fi_code:-none}')" ;;
  esac
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
