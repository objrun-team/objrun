#!/usr/bin/env bash
# Only the two approved offline container stages are accepted. No setup.sh,
# elan, apt, pip, git, mutable branch, or remote mathematical verifier.
set -eu
case "$1" in
  bootstrap|unpack-probe) ;;
  *) echo "only an approved offline public dependency stage is allowed" >&2; exit 2 ;;
esac
exec python /plan/minif2f_restore.py "$1" --root /cache --public /public \
  --lock-sha "$PUBLIC_LOCK_SHA256" --problems-sha "$PROBLEMS_SHA256"
