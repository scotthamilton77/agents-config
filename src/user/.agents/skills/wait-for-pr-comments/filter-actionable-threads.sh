#!/usr/bin/env bash
# Purpose: filter count-unresolved-threads.sh output against the PR inventory,
# excluding threads that are intentionally unresolved (SKIP / ESCALATE
# classifications). Phase 9 uses this to decide whether to re-loop: only
# genuinely actionable threads (unresolved FIX, or threads not in the
# inventory at all) should trigger a new review round.
#
# Inputs:
#   stdin:        JSON from count-unresolved-threads.sh
#                 {count: <n>, thread_ids: ["<id>", ...]}
#   --inventory <path>  PR inventory JSON (schema_version 1)
#
# Outputs:
#   stdout: JSON {count: <n>, thread_ids: [<id>, ...]} — only actionable threads
#   exit codes:
#     0 = success
#     1 = inventory file missing / unreadable
#     2 = bad flag usage or stdin parse failure
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --inventory <path> < <count-unresolved-threads JSON>

Reads count-unresolved-threads.sh output from stdin and filters out thread IDs
that the inventory marks SKIP or ESCALATE (intentionally unresolved). Emits
JSON {count, thread_ids} of remaining actionable threads.
EOF
  exit 2
}

INVENTORY=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --inventory) INVENTORY="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$INVENTORY" ] || { echo "error: --inventory is required" >&2; exit 2; }
[ -r "$INVENTORY" ] || { echo "error: cannot read inventory: $INVENTORY" >&2; exit 1; }

STDIN_JSON="$(cat)"

ERR_TMP="$(mktemp)"
trap 'rm -f "$ERR_TMP"' EXIT

if ! THREAD_IDS="$(printf '%s' "$STDIN_JSON" | jq -c '.thread_ids // []' 2>"$ERR_TMP")"; then
  echo "error: failed to parse stdin JSON: $(cat "$ERR_TMP")" >&2
  exit 2
fi

if ! RESULT="$(printf '%s' "$THREAD_IDS" | jq -c --slurpfile inv "$INVENTORY" '
  . as $unresolved
  | ($inv[0].items // [])
  | map(select(.thread_id != null) | {thread_id, classification})
  as $inv_threads
  | $unresolved
  | map(. as $tid
      | ($inv_threads | map(select(.thread_id == $tid)) | .[0] // null) as $match
      | if $match == null
        then .
        elif $match.classification == "SKIP" or $match.classification == "ESCALATE"
        then empty
        else .
        end)
  | {count: length, thread_ids: .}
' 2>"$ERR_TMP")"; then
  echo "error: failed to process inventory or thread IDs: $(cat "$ERR_TMP")" >&2
  exit 2
fi

printf '%s\n' "$RESULT"
