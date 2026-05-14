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
# Stdout contract: the caller captures stdout via `$(...)` command
# substitution and compares it to the literal `handled` or `not-container`
# tokens. To prevent multi-line capture (which would route to the case
# error branch after irreversible state changes), this script saves the
# real stdout on FD 3 immediately after arg parsing and redirects all
# remaining stdout (including every `bd` subcommand) to stderr. Only the
# final decision token is written to FD 3.
#
# Exit: 0 on success (decision emitted on stdout); non-zero on error.

set -euo pipefail

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

# Save real stdout on FD 3; redirect remaining stdout to stderr so subordinate
# bd/jq/helper-script output does not pollute the caller's $(...) capture.
exec 3>&1 1>&2

X_TYPE=$(bd show "$BEAD_ID" --json | jq -r '.[0].issue_type // "task"')

CONTAINER=0
case "$X_TYPE" in
    milestone|epic) CONTAINER=1 ;;
    feature)
        # 'blocked' is not a real stored status; dep-blocked children have
        # status open or in_progress. open,in_progress covers all non-closed
        # children. `--limit 0` keeps the inventory unbounded so a child past
        # row 50 cannot slip past the container check. We FILTER OUT
        # formula-gate children (carrying `merge-gate` or `human` label)
        # before counting: brainstorm finalize attaches merge-gate /
        # [Human verify] children under feature-Y impl beads, and counting
        # those toward "feature has active children" wrongly reclassifies
        # legitimate Y impls as containers.
        CHILD_COUNT=$(bd list --parent "$BEAD_ID" --status open,in_progress --limit 0 --json \
            | jq '[.[] | select(((.labels // []) | (index("merge-gate") or index("human"))) | not)] | length')
        [ "$CHILD_COUNT" -gt 0 ] && CONTAINER=1 || CONTAINER=0 ;;
esac

if [ "$CONTAINER" = "0" ]; then
    echo "not-container" >&3
    exit 0
fi

# Detect prior-run state. Probe BOTH directions of the produced-from /
# produced-bead edge pair: the forward `produced-bead-<Y>` label on X
# (Step 7) AND the reverse `produced-from-<X>` label on non-closed Y
# candidates (Step 4). If Step 4 ran but Step 7 crashed, only the reverse
# edge exists — without checking it the container path would treat X as
# clean and orphan Y. `--limit 0` keeps the orphan inventory unbounded so
# a Y candidate past row 50 cannot slip past the probe.
PRODUCED_COUNT=$(bd label list "$BEAD_ID" --json \
    | jq '[.[] | select(startswith("produced-bead-"))] | length')
ORPHAN_REVERSE_COUNT=$(bd list --label "produced-from-$BEAD_ID" --limit 0 --json \
    | jq '[.[] | select(.status != "closed")] | length')

# HEP for container sources: the human bead is created as a CHILD of the
# source bead via `--parent`. This sidesteps bd's cross-type `blocks` epic
# wall (epic-typed sources cannot carry `blocks` deps to task-typed
# escalation beads) AND is uniformly cleaner than per-type dep branching
# (milestone / feature-with-children could in principle take a `blocks`
# dep, but the parent-child relationship documents the escalation more
# directly). `--no-inherit-labels` prevents the human bead from inheriting
# brainstormed / implementation-ready / session markers from the source
# container, which would otherwise produce surprising side effects.
# Container source readiness is gated by the Rule C invariant (containers
# MUST NOT carry readiness labels) rather than a `blocks` dep — enforced
# by the migrations + tests in this PR.
hep_create_human() {
    bd create --parent "$BEAD_ID" --no-inherit-labels "$@" --json \
        | jq -r 'if type == "array" then .[0].id else .id end // empty'
}

if [ "$PRODUCED_COUNT" -gt 1 ]; then
    # Multiple produced-bead-* labels: ambiguous-Y HEP.
    X_PRIORITY=$(bd show "$BEAD_ID" --json | jq -r '.[0].priority // "2"')
    ESC_ID=$(hep_create_human \
        --type task --priority "$X_PRIORITY" \
        --title "Manual triage: multiple produced-bead labels on $BEAD_ID (container)" \
        --description "finalize halted: $PRODUCED_COUNT produced-bead-* labels on $BEAD_ID which is now a container (type=$X_TYPE). Remove all but the correct label, then re-run finalize.")
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
    bd update "$BEAD_ID" --status open
    echo "PAUSED: ambiguous Y on container $BEAD_ID; escalation bead $ESC_ID created (child of source)."
    bd mol burn "$MOL_ID" --force
    echo "handled" >&3
    exit 0
fi

if [ "$PRODUCED_COUNT" -gt 0 ] || [ "$ORPHAN_REVERSE_COUNT" -gt 0 ]; then
    # Reclassification case: Y exists (via forward marker OR reverse-edge
    # orphan on a non-closed Y) but X is now a container.
    X_PRIORITY=$(bd show "$BEAD_ID" --json | jq -r '.[0].priority // "2"')
    ESC_ID=$(hep_create_human \
        --type task --priority "$X_PRIORITY" \
        --title "Manual triage: container reclassification of $BEAD_ID after Y was produced" \
        --description "finalize halted: $BEAD_ID produced a Y impl bead in a prior run (produced-bead=$PRODUCED_COUNT, reverse-orphan=$ORPHAN_REVERSE_COUNT) but is now a container (type=$X_TYPE). Determine whether to close the orphan Y or proceed. Re-run finalize after resolution.")
    if [ -z "$ESC_ID" ] || [ "$ESC_ID" = "null" ]; then
        echo "HEP: failed to extract escalation bead id" >&2
        exit 1
    fi
    bd label add "$ESC_ID" human
    # Tolerant lookup: bd mol current may fail or emit no usable JSON; the
    # `unknown` fallback is informational only. Under set -euo pipefail
    # the failure must be swallowed locally so the HEP path completes
    # instead of aborting after the escalation bead is already created.
    STEP_BEAD_ID=$(bd mol current "$MOL_ID" --json 2>/dev/null \
        | jq -r 'if type == "array" then .[0].id else .id end // "unknown"' \
        || echo "unknown")
    [ -z "$STEP_BEAD_ID" ] && STEP_BEAD_ID="unknown"
    bd update "$ESC_ID" --append-notes \
"Source: $BEAD_ID
Step-bead: $STEP_BEAD_ID
Molecule: $MOL_ID
Worktree: N/A
Scenario hint: scope-expanded (container reclassification after Y produced)"
    bd update "$BEAD_ID" --status open
    echo "PAUSED: container reclassification on $BEAD_ID; escalation bead $ESC_ID created (child of source)."
    bd mol burn "$MOL_ID" --force
    echo "handled" >&3
    exit 0
fi

# Clean container case: decomposition outcome — stamp audit-trail label,
# close X via I2 close-walk, burn the wisp. Per Rule C, do NOT stamp
# `brainstormed` or `implementation-ready`. The `epic-decomposed` label
# is audit-only.
echo "Container bead (type=$X_TYPE): decomposition outcome; implementation-ready NOT stamped."
bd label add "$BEAD_ID" epic-decomposed
~/.beads/scripts/bd-close-walk.sh \
    --bead-id "$BEAD_ID" \
    --reason "brainstormed (decomposition); no impl bead produced"
bd mol burn "$MOL_ID" --force
echo "handled" >&3
exit 0
