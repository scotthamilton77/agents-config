#!/usr/bin/env bash
# bd-finalize-create-impl-bead.sh — Create the implementation bead during brainstorm finalize.
#
# Wraps brainstorm-bead formula Step 4 ("Create Y atomically") in a single
# idempotent command. The LLM issues one invocation; the script handles the
# intra-step orphan guard (probe → create-or-short-circuit), escalation
# bookkeeping (human label + audit comment on source bead), and all error
# paths — so the formula needs no case statement or extra bd calls.
#
# Callers invoke as:
#   Y_ID=$(bd-finalize-create-impl-bead.sh --source-bead-id X ...) || exit 1
#
# Usage:
#   bd-finalize-create-impl-bead.sh \
#     --source-bead-id <id> \
#     --type <feature|bug|task> \
#     --priority <0-4|P0-P4> \
#     --title <text> \
#     --labels <csv> \
#     --spec-file <path> \
#     --ac-file <path> \
#     [--parent <id>]
#
# Output:
#   stdout (exit 0): the new (or pre-existing) implementation bead ID — nothing else
#   stderr (exit 1): diagnostic message; source bead has been labelled 'human'
#                    and an audit comment added (escalate case only)
#
# Exit: 0 on success; 1 on any failure.

set -euo pipefail

SOURCE_BEAD_ID=""
TYPE=""
PRIORITY=""
TITLE=""
LABELS=""
SPEC_FILE=""
AC_FILE=""
PARENT=""

usage() {
    cat >&2 <<'EOF'
Usage: bd-finalize-create-impl-bead.sh \
  --source-bead-id <id> \
  --type <feature|bug|task> \
  --priority <0-4|P0-P4> \
  --title <text> \
  --labels <csv> \
  --spec-file <path> \
  --ac-file <path> \
  [--parent <id>]

Create the implementation bead during brainstorm-bead finalize (Step 4).

Probes for an existing non-closed bead carrying label produced-from-<source-bead-id>
before issuing bd create. Returns the existing bead ID if one is found (idempotent
re-entry), creates a new one if none exists. Escalates if multiple non-closed
candidates exist (requires human triage).

This script gives the LLM a single named invocation for Step 4 of brainstorm-bead
finalize, preventing the parallel-tool-call race that produces duplicate
implementation beads.

Options:
  --source-bead-id  ID of the brainstorm seed bead — used for the orphan probe
                    and to stamp the produced-from label on Y (required)
  --type            Bead type: feature, bug, or task (required)
  --priority        Priority: integer 0-4 or P0-P4 format (required)
  --title           Title for the new implementation bead (required)
  --labels          Comma-separated labels to apply; must include
                    produced-from-<source-bead-id> and other finalize labels (required)
  --spec-file       Path to file containing the spec/notes content (required)
  --ac-file         Path to file containing the acceptance criteria (required)
  --parent          Parent bead ID; omit if source bead has no parent (optional)
  -h, --help        Show this help

Output:
  stdout (exit 0): the new or pre-existing implementation bead ID (one line)
  stderr (exit 1): diagnostic; source bead gets 'human' label + audit comment on escalate
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source-bead-id)
            [[ $# -ge 2 ]] || { echo "Error: --source-bead-id requires a value" >&2; usage; }
            SOURCE_BEAD_ID="$2"; shift 2 ;;
        --type)
            [[ $# -ge 2 ]] || { echo "Error: --type requires a value" >&2; usage; }
            TYPE="$2"; shift 2 ;;
        --priority)
            [[ $# -ge 2 ]] || { echo "Error: --priority requires a value" >&2; usage; }
            PRIORITY="$2"; shift 2 ;;
        --title)
            [[ $# -ge 2 ]] || { echo "Error: --title requires a value" >&2; usage; }
            TITLE="$2"; shift 2 ;;
        --labels)
            [[ $# -ge 2 ]] || { echo "Error: --labels requires a value" >&2; usage; }
            LABELS="$2"; shift 2 ;;
        --spec-file)
            [[ $# -ge 2 ]] || { echo "Error: --spec-file requires a value" >&2; usage; }
            SPEC_FILE="$2"; shift 2 ;;
        --ac-file)
            [[ $# -ge 2 ]] || { echo "Error: --ac-file requires a value" >&2; usage; }
            AC_FILE="$2"; shift 2 ;;
        --parent)
            [[ $# -ge 2 ]] || { echo "Error: --parent requires a value" >&2; usage; }
            PARENT="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# Validate required args
for _flag_var in SOURCE_BEAD_ID TYPE PRIORITY TITLE LABELS SPEC_FILE AC_FILE; do
    if [[ -z "${!_flag_var}" ]]; then
        _flag_name=$(echo "$_flag_var" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
        echo "Error: --${_flag_name} is required" >&2
        usage
    fi
done

[[ -f "$SPEC_FILE" ]] || { echo "Error: spec-file not found: $SPEC_FILE" >&2; exit 1; }
[[ -f "$AC_FILE"   ]] || { echo "Error: ac-file not found: $AC_FILE" >&2;       exit 1; }

# Validate that --labels includes produced-from-<source-bead-id> — required for the
# intra-step orphan probe to find this bead on any subsequent retry.
case ",${LABELS}," in
    *,"produced-from-${SOURCE_BEAD_ID}",*) ;;
    *)  echo "Error: --labels must include produced-from-${SOURCE_BEAD_ID}" >&2
        exit 1 ;;
esac

# ── Intra-step orphan probe ─────────────────────────────────────────────────
# Check for non-closed beads already carrying produced-from-<source> label.
# This guard is a second line of defence against the parallel-tool-call race:
# even if Step 1b's top-of-finalize probe was bypassed, this probe fires
# immediately before bd create and catches any bead that exists in the gap.
ORPHAN_JSON=$(bd list --label "produced-from-${SOURCE_BEAD_ID}" --json 2>/dev/null) || {
    echo "Error: bd list failed during orphan probe" >&2
    exit 1
}
ORPHAN_COUNT=$(printf '%s' "$ORPHAN_JSON" | jq '[.[] | select(.status != "closed")] | length' 2>/dev/null) || {
    echo "Error: jq parse failed on orphan probe output" >&2
    exit 1
}

if [[ "$ORPHAN_COUNT" -ge 2 ]]; then
    # Multiple orphan impl beads exist — escalate to human; all bookkeeping done here.
    bd label add "$SOURCE_BEAD_ID" human || true
    bd comments add "$SOURCE_BEAD_ID" \
        "finalize halted: ${ORPHAN_COUNT} non-closed impl beads carry produced-from-${SOURCE_BEAD_ID}; manual triage required." || true
    echo "Error: ${ORPHAN_COUNT} non-closed impl beads found for ${SOURCE_BEAD_ID}; source bead flagged for human triage" >&2
    exit 1
fi

if [[ "$ORPHAN_COUNT" -eq 1 ]]; then
    # Pre-existing impl bead found — idempotent resume; output its ID.
    EXISTING_ID=$(printf '%s' "$ORPHAN_JSON" | jq -r '[.[] | select(.status != "closed")] | .[0].id')
    printf '%s\n' "$EXISTING_ID"
    exit 0
fi

# ── Create implementation bead ──────────────────────────────────────────────
PARENT_ARGS=()
[[ -n "$PARENT" ]] && PARENT_ARGS=("--parent" "$PARENT")

CREATE_JSON=$(bd create \
    --type "$TYPE" \
    --priority "$PRIORITY" \
    "${PARENT_ARGS[@]}" \
    --title "$TITLE" \
    --description "$(cat "$SPEC_FILE")" \
    --acceptance "$(cat "$AC_FILE")" \
    --labels "$LABELS" \
    --deps "discovered-from:${SOURCE_BEAD_ID}" \
    --no-inherit-labels \
    --json) || {
    echo "Error: bd create failed" >&2
    exit 1
}

# bd create --json returns either an object {id:...} or array [{id:...}] depending
# on bd version; handle both forms defensively.
Y_ID=$(printf '%s' "$CREATE_JSON" | jq -r 'if type == "array" then .[0].id else .id end // empty') || {
    echo "Error: jq parse failed on bd create output (see jq diagnostic above)" >&2
    exit 1
}

if [[ -z "$Y_ID" || "$Y_ID" == "null" ]]; then
    echo "Error: bd create returned no id" >&2
    exit 1
fi

printf '%s\n' "$Y_ID"
