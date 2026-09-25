#!/usr/bin/env bash
# Compiler settings for source builds we do not control.

# The CC to hand the feedclients' update.sh, or nothing to leave it alone.
#
# All three feedclients build adsbexchange/readsb, pinned at a 2024 commit
# whose `char spinner[4] = "|/-\\"` GCC 15 rejects under its -Werror as
# -Wunterminated-string-initialization. Their Makefile assigns CFLAGS with a
# plain `=`, so only CC reaches the compile line from outside. GCC 14 does not
# know the warning and errors on the flag, so it is probed rather than always
# passed.
feedclient_cc() {
  local flag=-Wno-error=unterminated-string-initialization
  if gcc -Werror "$flag" -x c -c /dev/null -o /dev/null 2>/dev/null; then
    echo "gcc $flag"
  fi
}
