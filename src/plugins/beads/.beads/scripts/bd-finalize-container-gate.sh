#!/usr/bin/env bash
# bd-finalize-container-gate.sh — Step 0 of brainstorm-bead.formula.toml finalize.
#
# Determines whether X (the source seed bead) is a container
# (milestone, epic, or feature-with-children). If so, executes the
# appropriate HEP escalation OR a clean decomposition outcome, prints
# `handled` on stdout, and exits 0 — the caller MUST then exit 0 itself.
# Otherwise prints `not-container` and exits 0 so the caller falls
# through to Step 1.
#
# Usage:
#   bd-finalize-container-gate.sh --bead-id <id> --mol-id <mol-id>
#
# Output (stdout, one line):
#   handled        — container case fully handled (HEP escalation OR
#                    clean decomposition). Caller MUST exit 0.
#   not-container  — X is a leaf bead. Caller falls through to Step 1.
#
# Side effects (handled paths only):
#   - May create an escalation bead (label: human) and stamp it on X via
#     bd dep add (skipped for epic/milestone sources — Rule B structural
#     filter in whats-next already gates them out of bd ready).
#   - May close X via bd-close-walk.sh and stamp `epic-decomposed`.
#   - May burn the wisp via `bd mol burn`.
#   - Reverts X status to `open` on HEP paths.
#
# Exit: 0 on success (decision emitted on stdout); non-zero on error.

set -eu

BEAD_ID=""
MOL_ID=""

usage() {
    cat >&2 <<'EOF'
Usage: bd-finalize-container-gate.sh --bead-id <id> --mol-id <mol-id>

Step 0 of brainstorm-bead finalize: container detection + HEP / decomposition.

Options:
  --bead-id <id>     Source seed bead id (required)
  --mol-id <mol-id>  Current brainstorm-bead molecule id (required)
  -h, --help         Show this help
EOF
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --bead-id)
            [ $# -ge 2 ] || { echo "Error: --bead-id requires a value" >&2; usage; }
            BEAD_ID="$2"; shift 2 ;;
        --mol-id)
            [ $# -ge 2 ] || { echo "Error: --mol-id requires a value" >&2; usage; }
            MOL_ID="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

[ -z "$BEAD_ID" ] && { echo "Error: --bead-id is required" >&2; usage; }
[ -z "$MOL_ID" ]  && { echo "Error: --mol-id is required" >&2; usage; }

X_TYPE=$(bd show "$BEAD_ID" --json | jq -r '.[0].issue_type // "task"')

CONTAINER=0
case "$X_TYPE" in
    milestone|epic) CONTAINER=1 ;;
    feature)
        # Note: 'blocked' is not a real stored status; dep-blocked children
        # have status open or in_progress. open,in_progress covers all
        # non-closed children.
        CHILD_COUNT=$(bd list --parent "$BEAD_ID" --status open,in_progress --json | jq 'length')
        [ "$CHILD_COUNT" -gt 0 ] && CONTAINER=1 || CONTAINER=0 ;;
esac

if [ "$CONTAINER" = "0" ]; then
    echo "not-container"
    exit 0
fi

# Detect prior-run state. Probe BOTH directions of the produced-from /
# produced-bead edge pair: the forward `produced-bead-<Y>` label on X
# (Step 7) AND the reverse `produced-from-<X>` label on non-closed Y
# candidates (Step 4). If Step 4 ran but Step 7 crashed, only the reverse
# edge exists — without checking it the container path would treat X as
# clean and orphan Y.
PRODUCED_COUNT=$(bd label list "$BEAD_ID" --json \
    | jq '[.[] | select(startswith("produced-bead-"))] | length')
ORPHAN_REVERSE_COUNT=$(bd list --label "produced-from-$BEAD_ID" --json \
    | jq '[.[] | select(.status != "closed")] | length')

# epic/milestone sources cannot carry a cross-type `blocks` dep to a task
# escalation bead (bd's `blocks` epic wall hard-errors on cross-type edges).
# Containers are also excluded from `bd ready` and `bd ready --label
# implementation-ready` by structural filter (Rule B in the whats-next
# skill), so the dep is moot for them — setting status=open is sufficient
# to keep them out of any queue. For non-epic/milestone sources the dep
# is still required so `bd ready` gating works.
add_hep_block_dep() {
    local source_id="$1" esc_id="$2"
    case "$X_TYPE" in
        epic|milestone) ;;
        *) bd dep add "$source_id" "$esc_id" ;;
    esac
}

if [ "$PRODUCED_COUNT" -gt 1 ]; then
    # Multiple produced-bead-* labels: ambiguous-Y HEP.
    X_PRIORITY=$(bd show "$BEAD_ID" --json | jq -r '.[0].priority // "2"')
    ESC_ID=$(bd create --type task --priority "$X_PRIORITY" \
        --title "Manual triage: multiple produced-bead labels on $BEAD_ID (container)" \
        --description "finalize halted: $PRODUCED_COUNT produced-bead-* labels on $BEAD_ID which is now a container (type=$X_TYPE). Remove all but the correct label, then re-run finalize." \
        --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
    if [ -z "$ESC_ID" ] || [ "$ESC_ID" = "null" ]; then
        echo "HEP: failed to extract escalation bead id" >&2
        exit 1
    fi
    bd label add "$ESC_ID" human
    bd update "$ESC_ID" --append-notes \
"Source: $BEAD_ID
Step-bead: N/A (pre-pour container gate)
Molecule: $MOL_ID
Worktree: N/A
Scenario hint: scope-expanded (multiple produced-bead labels on container)"
    add_hep_block_dep "$BEAD_ID" "$ESC_ID"
    bd update "$BEAD_ID" --status open
    echo "PAUSED: ambiguous Y on container $BEAD_ID; escalation bead $ESC_ID created." >&2
    bd mol burn "$MOL_ID" --force
    echo "handled"
    exit 0
fi

if [ "$PRODUCED_COUNT" -gt 0 ] || [ "$ORPHAN_REVERSE_COUNT" -gt 0 ]; then
    # Reclassification case: Y exists (via forward marker OR reverse-edge
    # orphan on a non-closed Y) but X is now a container.
    X_PRIORITY=$(bd show "$BEAD_ID" --json | jq -r '.[0].priority // "2"')
    ESC_ID=$(bd create --type task --priority "$X_PRIORITY" \
        --title "Manual triage: container reclassification of $BEAD_ID after Y was produced" \
        --description "finalize halted: $BEAD_ID produced a Y impl bead in a prior run (produced-bead=$PRODUCED_COUNT, reverse-orphan=$ORPHAN_REVERSE_COUNT) but is now a container (type=$X_TYPE). Determine whether to close the orphan Y or proceed. Re-run finalize after resolution." \
        --json | jq -r 'if type == "array" then .[0].id else .id end // empty')
    if [ -z "$ESC_ID" ] || [ "$ESC_ID" = "null" ]; then
        echo "HEP: failed to extract escalation bead id" >&2
        exit 1
    fi
    bd label add "$ESC_ID" human
    STEP_BEAD_ID=$(bd mol current "$MOL_ID" --json 2>/dev/null \
        | jq -r 'if type == "array" then .[0].id else .id end // "unknown"')
    bd update "$ESC_ID" --append-notes \
"Source: $BEAD_ID
Step-bead: $STEP_BEAD_ID
Molecule: $MOL_ID
Worktree: N/A
Scenario hint: scope-expanded (container reclassification after Y produced)"
    add_hep_block_dep "$BEAD_ID" "$ESC_ID"
    bd update "$BEAD_ID" --status open
    echo "PAUSED: container reclassification on $BEAD_ID; escalation bead $ESC_ID created." >&2
    bd mol burn "$MOL_ID" --force
    echo "handled"
    exit 0
fi

# Clean container case: decomposition outcome — stamp audit-trail label,
# close X via I2 close-walk, burn the wisp. Per Rule C, do NOT stamp
# `brainstormed` or `implementation-ready`. The `epic-decomposed` label
# is audit-only.
echo "Container bead (type=$X_TYPE): decomposition outcome; implementation-ready NOT stamped." >&2
bd label add "$BEAD_ID" epic-decomposed
~/.beads/scripts/bd-close-walk.sh \
    --bead-id "$BEAD_ID" \
    --reason "brainstormed (decomposition); no impl bead produced"
bd mol burn "$MOL_ID" --force
echo "handled"
exit 0
