#!/usr/bin/env bash
# Journal readers for 60-verify.sh, kept here so they are testable off-box.

# True when the most recent "Results:  N positions/minute" line in $1 has
# N > 0. The line is logged every minute whether or not the client is
# connected, so its presence alone proves nothing.
mlat_returning_positions() {
  awk '/Results:.*positions\/minute/ { rate = $(NF - 1) }
       END { exit !(rate + 0 > 0) }' <<<"$1"
}
