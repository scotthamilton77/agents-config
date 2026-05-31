#!/usr/bin/env bash
# write-inventory.sh — atomic write helper for the PR-review hand-off contract.
#
# Reads inventory JSON from stdin, sets crash_recovery fields, writes atomically
# (mktemp + mv on the same filesystem), and runs retention housekeeping.
#
# Usage:
#   write-inventory.sh --state <state> --phase <last_completed_phase> --output <inventory_json_path>
#     --state:   complete | partial
#     --phase:   phase identifier (e.g. "5a-verify-failed", "7-write-inventory", "8-skill-b-done")
#     --output:  target path under ~/.claude/state/pr-inventory/
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
#
# Exit codes:
#   0  — write succeeded
#   64 — invalid args: unknown flag, invalid state, or empty phase/path (EX_USAGE)
#   65 — jq parse/write failed (EX_DATAERR)

set -euo pipefail

STATE=""
PHASE=""
PATH_OUT=""

usage() {
    echo "usage: write-inventory.sh --state <state> --phase <phase-id> --output <path>" >&2
    exit 64
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --state)  [ "$#" -ge 2 ] || usage; STATE="${2:-}";    shift 2 ;;
        --phase)  [ "$#" -ge 2 ] || usage; PHASE="${2:-}";    shift 2 ;;
        --output) [ "$#" -ge 2 ] || usage; PATH_OUT="${2:-}"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "error: unknown flag: $1" >&2; usage ;;
    esac
done

[ -n "$STATE"    ] || { echo "error: --state is required" >&2; exit 64; }
[ -n "$PHASE"    ] || { echo "error: --phase is required" >&2; exit 64; }
[ -n "$PATH_OUT" ] || { echo "error: --output is required" >&2; exit 64; }

case "$STATE" in
    complete) COMPLETED=true ;;
    partial)  COMPLETED=false ;;
    *) echo "error: --state must be 'complete' or 'partial', got '$STATE'" >&2; exit 64 ;;
esac

DIR_OUT="$(dirname "$PATH_OUT")"
mkdir -p "$DIR_OUT"

# Real mktemp in the target directory — symlink-safe, collision-safe.
# Restrict permissions so the transient file is never world-readable.
umask 077
TMP="$(mktemp "${PATH_OUT}.tmp.XXXXXXXX")"

if ! jq --argjson completed "$COMPLETED" --arg phase "$PHASE" \
       '.crash_recovery = {skill_a_completed: $completed, last_completed_phase: $phase}' \
       > "$TMP"; then
    rm -f "$TMP"
    echo "error: jq failed to update crash_recovery (input not valid JSON?)" >&2
    exit 65
fi

mv "$TMP" "$PATH_OUT"

# Retention housekeeping: delete inventories >30 days old. Never touches files
# newer than 30 days, so safe for crash recovery. Hard-guarded to the canonical
# inventory directory so a caller passing an arbitrary path can never trigger
# deletion of unrelated JSON files.
EXPECTED_DIR="${HOME}/.claude/state/pr-inventory"
if [ "$DIR_OUT" = "$EXPECTED_DIR" ]; then
    find "$EXPECTED_DIR" -type f -name '*.json' -mtime +30 -delete 2>/dev/null || true
fi
