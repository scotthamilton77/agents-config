#!/usr/bin/env bash
# bd-finalize-create-impl-bead.sh — Create the implementation bead during brainstorm finalize.
#
# Wraps brainstorm-bead formula Step 4 ("Create Y atomically") in a single
# idempotent command. The LLM issues one invocation; the script handles the
# intra-step orphan guard (probe → create-or-short-circuit) so the formula
# cannot produce duplicate implementation beads via parallel tool-call batching.
#
# Before calling bd create, the script probes for an existing non-closed bead
# carrying the produced-from-<source-bead-id> label. If one exists, it returns
# that bead's ID instead of creating a new one (result=exists). If two or more
# exist, it exits non-zero so finalize can escalate to human triage.
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
# Output (stdout, one line):
#   result=created  y_id=<id>              # fresh creation
#   result=exists   y_id=<id>              # pre-existing; skipped create
#   result=escalate count=<N> source=<id>  # exit 1; human triage needed
#   result=error    message=<token>        # exit 1; fatal (hyphen-separated, no spaces)
#
# Exit: 0 on result=created|exists; 1 on result=escalate|error.

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
                    and the produced-from dep edge (required)
  --type            Bead type: feature, bug, or task (required)
  --priority        Priority 0-4 (required)
  --title           Title for the new implementation bead (required)
  --labels          Comma-separated labels to apply; must include
                    produced-from-<source-bead-id> and other finalize labels (required)
  --spec-file       Path to file containing the spec/notes content (required)
  --ac-file         Path to file containing the acceptance criteria (required)
  --parent          Parent bead ID; omit if source bead has no parent (optional)
  -h, --help        Show this help

Output (one line on stdout):
  result=created  y_id=<id>
  result=exists   y_id=<id>
  result=escalate count=<N> source=<id>
  result=error    message=<hyphen-separated-token>
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
        _flag_name=$(echo "$_flag_var" | tr '[:upper:]_' '[:lower:]-')
        echo "Error: --${_flag_name} is required" >&2
        usage
    fi
done

[[ -f "$SPEC_FILE" ]] || { printf 'result=error message=spec-file-not-found:%s\n' "$SPEC_FILE"; exit 1; }
[[ -f "$AC_FILE"   ]] || { printf 'result=error message=ac-file-not-found:%s\n'   "$AC_FILE";   exit 1; }

# Validate that --labels includes produced-from-<source-bead-id> — required for the
# intra-step orphan probe to find this bead on any subsequent retry.
case ",${LABELS}," in
    *,"produced-from-${SOURCE_BEAD_ID}",*) ;;
    *)  printf 'result=error message=labels-must-include-produced-from-%s\n' "$SOURCE_BEAD_ID"
        exit 1 ;;
esac

# ── Intra-step orphan probe ─────────────────────────────────────────────────
# Check for non-closed beads already carrying produced-from-<source> label.
# This guard is a second line of defence against the parallel-tool-call race:
# even if Step 1b's top-of-finalize probe was bypassed, this probe fires
# immediately before bd create and catches any bead that exists in the gap.
ORPHAN_JSON=$(bd list --label "produced-from-${SOURCE_BEAD_ID}" --json 2>/dev/null) || {
    printf 'result=error message=bd-list-failed-for-orphan-probe\n'
    exit 1
}
ORPHAN_COUNT=$(printf '%s' "$ORPHAN_JSON" | jq '[.[] | select(.status != "closed")] | length' 2>/dev/null) || {
    printf 'result=error message=jq-parse-failed-on-orphan-probe\n'
    exit 1
}

if [[ "$ORPHAN_COUNT" -ge 2 ]]; then
    printf 'result=escalate count=%d source=%s\n' "$ORPHAN_COUNT" "$SOURCE_BEAD_ID"
    exit 1
fi

if [[ "$ORPHAN_COUNT" -eq 1 ]]; then
    EXISTING_ID=$(printf '%s' "$ORPHAN_JSON" | jq -r '[.[] | select(.status != "closed")] | .[0].id')
    printf 'result=exists y_id=%s\n' "$EXISTING_ID"
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
    printf 'result=error message=bd-create-failed\n'
    exit 1
}

# bd create --json returns either an object {id:...} or array [{id:...}] depending
# on bd version; handle both forms defensively.
Y_ID=$(printf '%s' "$CREATE_JSON" | jq -r '(.[0].id // .id) // empty' 2>/dev/null)

if [[ -z "$Y_ID" || "$Y_ID" == "null" ]]; then
    printf 'result=error message=bd-create-returned-no-id\n'
    exit 1
fi

printf 'result=created y_id=%s\n' "$Y_ID"
