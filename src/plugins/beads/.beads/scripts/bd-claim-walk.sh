#!/usr/bin/env bash
# bd-claim-walk.sh — Mark a bead and all ancestor epics in_progress (Beads I1 claim walk).
#
# Implements the Beads I1 invariant: before any work starts on a bead, the bead
# AND every ancestor epic must be marked in_progress so they never appear as
# available in `bd ready`.
#
# Usage:
#   bd-claim-walk.sh --bead-id <id>
#
# Output (stdout, one line):
#   walked=<N>   chain depth traversed (includes beads already in_progress/closed that were skipped)
#
# Exit: 0 on success; non-zero on error.

set -euo pipefail

BEAD_ID=""

usage() {
    cat >&2 <<'EOF'
Usage: bd-claim-walk.sh --bead-id <id>

Mark a bead and all ancestor epics in_progress (Beads I1 claim walk).

Walks UP the parent chain from <id>, marking each bead in_progress until
there are no more parents. Idempotent — already-in_progress and closed
beads are skipped without error.

Options:
  --bead-id <id>   ID of the bead whose work is starting (required)
  -h, --help       Show this help

Output (one line on stdout):
  walked=<N>   chain depth traversed (includes already-in_progress/closed beads that were skipped)
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bead-id)
            [[ $# -ge 2 ]] || { echo "Error: --bead-id requires a value" >&2; usage; }
            BEAD_ID="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

[[ -z "$BEAD_ID" ]] && { echo "Error: --bead-id is required" >&2; usage; }

COUNT=0
CURRENT="$BEAD_ID"

while [[ -n "$CURRENT" ]]; do
    COUNT=$((COUNT + 1))
    SHOW_JSON=$(bd show "$CURRENT" --json)
    STATUS=$(printf '%s' "$SHOW_JSON" | jq -r '.[0].status // "open"')
    NEXT=$(printf '%s' "$SHOW_JSON" | jq -r '.[0].parent // empty')
    # Skip beads that are already in_progress or closed — never reopen a closed bead.
    if [[ "$STATUS" != "in_progress" && "$STATUS" != "closed" ]]; then
        bd update "$CURRENT" --status in_progress
    fi
    CURRENT="$NEXT"
done

echo "walked=$COUNT"
