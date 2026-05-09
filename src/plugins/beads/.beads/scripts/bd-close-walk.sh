#!/usr/bin/env bash
# bd-close-walk.sh — Close a bead then cascade-close empty ancestor epics (Beads I2 close walk).
#
# Implements the Beads I2 invariant: after closing a bead, walk the parent chain
# and close each ancestor whose remaining children are all closed. Stops at the
# first ancestor that still has non-closed children.
#
# Usage:
#   bd-close-walk.sh --bead-id <id> --reason <text>
#
# Output (stdout, one line):
#   closed=<csv>   comma-separated IDs of all beads closed (target + any ancestors)
#                  empty string after '=' means nothing was closed (all already closed)
#
# Exit: 0 on success; non-zero on error.

set -euo pipefail

BEAD_ID=""
REASON=""

usage() {
    cat >&2 <<'EOF'
Usage: bd-close-walk.sh --bead-id <id> --reason <text>

Close a bead then cascade-close empty ancestor epics (Beads I2 close walk).

Closes <id> with the given reason, then walks UP the parent chain. At each
ancestor, checks if all children are closed; if so, closes the ancestor with
"All children closed". Stops at the first ancestor with non-closed children.

If <id> is already closed, skips the initial close and proceeds with the
ancestor walk (idempotent re-entry).

Options:
  --bead-id <id>    ID of the bead to close (required)
  --reason <text>   Close reason for the target bead (required)
  -h, --help        Show this help

Output (one line on stdout):
  closed=<csv>   comma-separated IDs closed in this run (empty if nothing needed closing)
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bead-id)
            [[ $# -ge 2 ]] || { echo "Error: --bead-id requires a value" >&2; usage; }
            BEAD_ID="$2"; shift 2 ;;
        --reason)
            [[ $# -ge 2 ]] || { echo "Error: --reason requires a value" >&2; usage; }
            REASON="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

[[ -z "$BEAD_ID" ]] && { echo "Error: --bead-id is required" >&2; usage; }
[[ -z "$REASON" ]] && { echo "Error: --reason is required" >&2; usage; }

CLOSED=()

# Read status and parent from a single bd show call.
SHOW_JSON=$(bd show "$BEAD_ID" --json)
STATUS=$(printf '%s' "$SHOW_JSON" | jq -r '.[0].status // "open"')
PARENT=$(printf '%s' "$SHOW_JSON" | jq -r '.[0].parent // empty')

# Close target bead — skip if already closed (idempotent re-entry)
if [[ "$STATUS" != "closed" ]]; then
    bd close "$BEAD_ID" --reason "$REASON"
    CLOSED+=("$BEAD_ID")
fi

# I2 ancestor walk: close each parent whose children are all now closed.
# Read status + next parent in one bd show call so replay-safe skips are free.
while [[ -n "$PARENT" ]]; do
    PARENT_SHOW=$(bd show "$PARENT" --json)
    PARENT_STATUS=$(printf '%s' "$PARENT_SHOW" | jq -r '.[0].status // "open"')
    NEXT_PARENT=$(printf '%s' "$PARENT_SHOW" | jq -r '.[0].parent // empty')
    if [[ "$PARENT_STATUS" != "closed" ]]; then
        NON_CLOSED=$(bd list --parent="$PARENT" --json \
            | jq '[.[] | select(.status != "closed")] | length')
        [[ "$NON_CLOSED" == "0" ]] || break
        bd close "$PARENT" --reason "All children closed"
        CLOSED+=("$PARENT")
    fi
    PARENT="$NEXT_PARENT"
done

# Guard against bash 3.x empty-array unbound-variable error under set -u
if [[ ${#CLOSED[@]} -eq 0 ]]; then
    echo "closed="
else
    CLOSED_CSV=$(IFS=,; echo "${CLOSED[*]}")
    echo "closed=${CLOSED_CSV}"
fi
