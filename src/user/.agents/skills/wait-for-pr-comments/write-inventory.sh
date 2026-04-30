#!/usr/bin/env bash
# write-inventory.sh — atomic write helper for the PR-review hand-off contract.
#
# Reads inventory JSON from stdin, sets crash_recovery fields, writes atomically
# (mktemp + mv on the same filesystem), and runs retention housekeeping.
#
# Usage:
#   write-inventory.sh <state> <last_completed_phase> <inventory_json_path>
#     state:                 complete | partial
#     last_completed_phase:  phase identifier (e.g. "5a-verify-failed",
#                            "7-write-inventory", "8-skill-b-done")
#     inventory_json_path:   target path under ~/.claude/state/pr-inventory/
#
# The script:
#   1. Reads inventory body from stdin.
#   2. Sets crash_recovery.skill_a_completed = (state == "complete") and
#      crash_recovery.last_completed_phase = <last_completed_phase>.
#   3. Validates with `jq` that the result parses.
#   4. Writes to <path>.tmp.<pid>, then `mv` to final path (POSIX-atomic on
#      the same filesystem).
#   5. Runs retention housekeeping: delete files older than 30 days in the
#      inventory directory. Never touches files newer than 30 days.

set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "usage: write-inventory.sh <state> <last_completed_phase> <inventory_json_path>" >&2
    exit 64
fi

STATE="$1"
PHASE="$2"
PATH_OUT="$3"

case "$STATE" in
    complete) COMPLETED=true ;;
    partial)  COMPLETED=false ;;
    *) echo "error: state must be 'complete' or 'partial', got '$STATE'" >&2; exit 64 ;;
esac

if [ -z "$PHASE" ]; then
    echo "error: last_completed_phase must be non-empty" >&2
    exit 64
fi

if [ -z "$PATH_OUT" ]; then
    echo "error: inventory_json_path must be non-empty" >&2
    exit 64
fi

DIR_OUT="$(dirname "$PATH_OUT")"
mkdir -p "$DIR_OUT"

TMP="${PATH_OUT}.tmp.$$"

if ! jq --argjson completed "$COMPLETED" --arg phase "$PHASE" \
       '.crash_recovery = {skill_a_completed: $completed, last_completed_phase: $phase}' \
       > "$TMP"; then
    rm -f "$TMP"
    echo "error: jq failed to update crash_recovery (input not valid JSON?)" >&2
    exit 65
fi

mv "$TMP" "$PATH_OUT"

# Retention housekeeping: delete inventories >30 days old. Never touches files
# newer than 30 days, so safe for crash recovery (the just-written file is
# safe even on tmpfs systems with weird mtimes because find's -mtime test is
# strict ">30").
find "$DIR_OUT" -type f -name '*.json' -mtime +30 -delete 2>/dev/null || true
