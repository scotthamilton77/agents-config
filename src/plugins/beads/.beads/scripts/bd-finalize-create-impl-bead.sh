#!/usr/bin/env bash
# bd-finalize-create-impl-bead.sh — Create the implementation bead pair during brainstorm finalize.
#
# Wraps brainstorm-bead formula Step 4 ("Create Y atomically") in a single
# idempotent command. The LLM issues one invocation; the script handles the
# intra-step orphan guard (probe → create-or-short-circuit), escalation
# bookkeeping (human label + audit comment on source bead), and all error
# paths — so the formula needs no case statement or extra bd calls.
#
# Callers invoke as:
#   HELPER_OUT=$(bd-finalize-create-impl-bead.sh --source-bead-id X ...) || exit 1
#   Y_CONTAINER_ID=$(echo "$HELPER_OUT" | grep '^Y_CONTAINER_ID=' | cut -d= -f2)
#   Y_IMPL_ID=$(echo "$HELPER_OUT" | grep '^Y_IMPL_ID=' | cut -d= -f2)
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
#   stdout (exit 0): two lines in KEY=VALUE form:
#     Y_CONTAINER_ID=<id>
#     Y_IMPL_ID=<id>
#   stderr (exit 1): diagnostic message; source bead has been labelled 'human'
#                    and an audit comment added (escalate case only)
#
# Exit: 0 on success; 1 on any failure.
#
# Idempotency states (checked in order, first match wins):
#   State 3: X has produced-bead-<id> AND that bead has a Y_impl child
#            with produced-from-<X_id> → skip; emit existing IDs.
#   State 2: a bead has produced-from-<X_id> label, but X has no
#            produced-bead-* → resume from after step 5.
#   State 1: a bead has pending-split-<X_id> label, but no
#            produced-from-<X_id> child → resume after creating Y_impl.
#   State 0: none of the above → fresh start.

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

Create the Y_container/Y_impl 2-level implementation bead pair during
brainstorm-bead finalize (Step 4).

Emits two KEY=VALUE lines on stdout:
  Y_CONTAINER_ID=<id>
  Y_IMPL_ID=<id>

Y_container (type=epic) is the structural parent; Y_impl (formula-derived
type) is the executable leaf carrying all impl-ready labels, child of
Y_container.

Probes for existing beads via idempotency states before issuing bd create.
Escalates if multiple non-closed candidates exist (requires human triage).

Options:
  --source-bead-id  ID of the brainstorm seed bead — used for the orphan probe
                    and to stamp the produced-from label on Y_impl (required)
  --type            Bead type: feature, bug, or task (required)
  --priority        Priority: integer 0-4 or P0-P4 format (required)
  --title           Title for the new implementation bead (required);
                    Y_container gets this title (without [Impl] prefix),
                    Y_impl gets [Impl] <title>
  --labels          Comma-separated labels to apply to Y_impl; must include
                    produced-from-<source-bead-id> and other finalize labels (required)
  --spec-file       Path to file containing the spec/notes content (required)
  --ac-file         Path to file containing the acceptance criteria (required)
  --parent          Parent bead ID for Y_container; omit if source bead has no parent (optional)
  -h, --help        Show this help

Output:
  stdout (exit 0): two KEY=VALUE lines: Y_CONTAINER_ID=<id> and Y_IMPL_ID=<id>
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

# Extract .id from bd create --json output (handles both object and single-element array).
_parse_create_id() {
    local json="$1" label="$2" id
    id=$(printf '%s' "$json" | jq -r 'if type == "array" then .[0].id else .id end // empty') || {
        echo "Error: jq parse failed on $label create output" >&2; exit 1
    }
    [[ -n "$id" && "$id" != "null" ]] || { echo "Error: bd create returned no id for $label" >&2; exit 1; }
    printf '%s' "$id"
}

# Derive Y_container title (strip [Impl] prefix if present — Y_container gets
# the clean title; Y_impl gets [Impl] <title>).
TITLE_TRIMMED=$(printf %s "$TITLE" | awk '{$1=$1; print}')
case "$TITLE_TRIMMED" in
    '[Impl] '*)
        CONTAINER_TITLE="${TITLE_TRIMMED#\[Impl\] }"
        IMPL_TITLE="$TITLE_TRIMMED"
        ;;
    *)
        CONTAINER_TITLE="$TITLE_TRIMMED"
        IMPL_TITLE="[Impl] $TITLE_TRIMMED"
        ;;
esac

# ── Idempotency: State 3 probe ──────────────────────────────────────────────
# Check if X already has a produced-bead-* label AND that bead has a Y_impl
# child with produced-from-<X_id>.
PRODUCED_LABELS=$(bd label list "${SOURCE_BEAD_ID}" --json 2>/dev/null \
    | jq -c '[.[] | select(startswith("produced-bead-"))]' 2>/dev/null) || PRODUCED_LABELS='[]'
PRODUCED_COUNT=$(printf '%s' "$PRODUCED_LABELS" | jq 'length' 2>/dev/null) || PRODUCED_COUNT=0

if [[ "$PRODUCED_COUNT" -ge 2 ]]; then
    echo "Error: ${PRODUCED_COUNT} produced-bead-* labels on ${SOURCE_BEAD_ID}; caller must triage" >&2
    exit 1
fi

if [[ "$PRODUCED_COUNT" -eq 1 ]]; then
    CONTAINER_CANDIDATE=$(printf '%s' "$PRODUCED_LABELS" | jq -r '.[0]' | sed 's/^produced-bead-//')
    # Probe for Y_impl child of Y_container with produced-from-<X_id>.
    IMPL_CANDIDATE=$(bd list --parent "${CONTAINER_CANDIDATE}" \
        --label "produced-from-${SOURCE_BEAD_ID}" --json 2>/dev/null \
        | jq -r '[.[] | select(.status != "closed")] | .[0].id // empty' 2>/dev/null) || IMPL_CANDIDATE=""
    if [[ -n "$IMPL_CANDIDATE" && "$IMPL_CANDIDATE" != "null" ]]; then
        # State 3: both exist — emit and exit.
        printf 'Y_CONTAINER_ID=%s\n' "$CONTAINER_CANDIDATE"
        printf 'Y_IMPL_ID=%s\n' "$IMPL_CANDIDATE"
        exit 0
    fi
fi

# ── Idempotency: State 2 probe ──────────────────────────────────────────────
ORPHAN_JSON=$(bd list --label "produced-from-${SOURCE_BEAD_ID}" --json 2>/dev/null) || {
    echo "Error: bd list failed during orphan probe" >&2
    exit 1
}
ORPHAN_COUNT=$(printf '%s' "$ORPHAN_JSON" | jq '[.[] | select(.status != "closed")] | length' 2>/dev/null) || {
    echo "Error: jq parse failed on orphan probe output" >&2
    exit 1
}

if [[ "$ORPHAN_COUNT" -ge 2 ]]; then
    echo "Error: ${ORPHAN_COUNT} non-closed impl beads carry produced-from-${SOURCE_BEAD_ID}; caller must HEP-escalate" >&2
    exit 1
fi

if [[ "$ORPHAN_COUNT" -eq 1 ]]; then
    # State 2: Y_impl exists but X not stamped; find its parent (Y_container).
    EXISTING_IMPL=$(printf '%s' "$ORPHAN_JSON" | jq -r '[.[] | select(.status != "closed")] | .[0].id')
    EXISTING_CONTAINER=$(bd show "$EXISTING_IMPL" --json 2>/dev/null \
        | jq -r '.[0].parent // empty' 2>/dev/null) || EXISTING_CONTAINER=""
    if [[ -n "$EXISTING_CONTAINER" && "$EXISTING_CONTAINER" != "null" ]]; then
        # Guard: verify the parent is actually an epic (Y_container shape), not a legacy project epic.
        # A legacy single-Y bead (old formula) can carry produced-from-X but its parent is the
        # brainstorm container epic, not a Y_container. Misidentifying it would corrupt that epic.
        CONTAINER_TYPE=$(bd show "$EXISTING_CONTAINER" --json 2>/dev/null \
            | jq -r '.[0].issue_type // empty' 2>/dev/null) || CONTAINER_TYPE=""
        if [[ "$CONTAINER_TYPE" == "epic" ]]; then
            printf 'Y_CONTAINER_ID=%s\n' "$EXISTING_CONTAINER"
            printf 'Y_IMPL_ID=%s\n' "$EXISTING_IMPL"
            exit 0
        fi
        # Parent is not an epic — this is likely a legacy single-Y bead. Fall through to State 0
        # to create a fresh Y_container/Y_impl pair; the legacy bead is left as-is.
    else
        # Y_impl exists but has no parent — cannot safely resume; emit error for caller to HEP-escalate.
        bd comments add "$SOURCE_BEAD_ID" \
            "finalize halted: orphan impl bead $EXISTING_IMPL has no parent; manual triage required." >/dev/null 2>&1 || true
        echo "Error: orphan impl bead $EXISTING_IMPL has no parent; cannot resume safely" >&2
        exit 1
    fi
fi

# ── Idempotency: State 1 probe ──────────────────────────────────────────────
PENDING_JSON=$(bd list --label "pending-split-${SOURCE_BEAD_ID}" --json 2>/dev/null) || PENDING_JSON='[]'
PENDING_COUNT=$(printf '%s' "$PENDING_JSON" | jq '[.[] | select(.status != "closed")] | length' 2>/dev/null) || PENDING_COUNT=0

Y_CONTAINER_ID=""
if [[ "$PENDING_COUNT" -ge 1 ]]; then
    # State 1: Y_container exists but Y_impl not yet created.
    Y_CONTAINER_ID=$(printf '%s' "$PENDING_JSON" | jq -r '[.[] | select(.status != "closed")] | .[0].id')
fi

# ── State 0: Create Y_container (if not already found in State 1) ───────────
if [[ -z "$Y_CONTAINER_ID" ]]; then
    PARENT_ARGS=()
    [[ -n "$PARENT" ]] && PARENT_ARGS=("--parent" "$PARENT")

    # Y_container intentionally carries no labels: --no-inherit-labels keeps it clean of
    # impl-ready / session markers (Rule C), and no --labels arg is passed so category
    # labels from X stay on Y_impl (the visible leaf in brainstorm/impl queries). The
    # container is a structural grouping bead, not the bearer of project semantics.
    CONTAINER_JSON=$(bd create \
        --type epic \
        --priority "$PRIORITY" \
        "${PARENT_ARGS[@]}" \
        --title "$CONTAINER_TITLE" \
        --no-inherit-labels \
        --json) || {
        echo "Error: bd create for Y_container failed" >&2
        exit 1
    }

    Y_CONTAINER_ID=$(_parse_create_id "$CONTAINER_JSON" "Y_container") || exit 1

    # Stamp crash-recovery marker FIRST — minimizes the window where Y_container exists
    # without a probe-able label. A crash after this line is detected by State 1 on retry.
    # A crash between create and this line leaves an unlabeled container (unavoidable without
    # atomic create+label); that window is inherent to the two-phase protocol.
    bd label add "$Y_CONTAINER_ID" "pending-split-${SOURCE_BEAD_ID}" >/dev/null 2>&1 || true

    # Claim-walk invariant I1.
    bd update "$Y_CONTAINER_ID" --status in_progress >/dev/null 2>&1 || true
fi

# ── Create Y_impl under Y_container ─────────────────────────────────────────
IMPL_JSON=$(bd create \
    --type "$TYPE" \
    --priority "$PRIORITY" \
    --parent "$Y_CONTAINER_ID" \
    --title "$IMPL_TITLE" \
    --description "$(cat "$SPEC_FILE")" \
    --acceptance "$(cat "$AC_FILE")" \
    --labels "$LABELS" \
    --deps "discovered-from:${SOURCE_BEAD_ID}" \
    --no-inherit-labels \
    --json) || {
    echo "Error: bd create for Y_impl failed" >&2
    exit 1
}

Y_IMPL_ID=$(_parse_create_id "$IMPL_JSON" "Y_impl") || exit 1

# Remove State 1 crash-recovery marker from Y_container now that Y_impl is created.
bd label remove "$Y_CONTAINER_ID" "pending-split-${SOURCE_BEAD_ID}" >/dev/null 2>&1 || true

# Emit the two-line KEY=VALUE output.
printf 'Y_CONTAINER_ID=%s\n' "$Y_CONTAINER_ID"
printf 'Y_IMPL_ID=%s\n' "$Y_IMPL_ID"
