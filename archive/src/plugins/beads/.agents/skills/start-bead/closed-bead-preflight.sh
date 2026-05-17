#!/bin/sh
# closed-bead-preflight.sh — Route Z preflight for the start-bead skill.
#
# Pure-read helper: probes a target bead, decides whether start-bead should
# proceed, forward to a produced bead, friendly-exit, or halt. Emits a single
# decision=... line on stdout. Performs NO state mutation (no bd update, no
# bd comments) — the agent driving the skill applies any audit comments.
#
# Usage:
#   closed-bead-preflight.sh <target-id> [--original=<id>] [--chain=<csv>]
#
# Decisions (stdout, single line, key=value pairs):
#   decision=proceed
#   decision=friendly-exit current=<target>
#   decision=forward target=<Y> chain=<csv>
#   decision=halt reason=cycle    original=<id> chain=<csv>
#   decision=halt reason=dangling original=<id> intermediate=<X> y=<Y>
#   decision=halt reason=multiple original=<id> intermediate=<X> labels=<csv>
#   decision=halt reason=error    message=<terse>
#
# Exit code: 0 on a clean decision; non-zero on error halts.

set -e

TARGET=""
ORIGINAL=""
CHAIN=""

# --- Argument parsing -------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --original=*)
            ORIGINAL=${arg#--original=}
            ;;
        --chain=*)
            CHAIN=${arg#--chain=}
            ;;
        --*)
            printf 'decision=halt reason=error message=unknown-flag:%s\n' "$arg"
            exit 2
            ;;
        *)
            if [ -z "$TARGET" ]; then
                TARGET=$arg
            else
                printf 'decision=halt reason=error message=extra-positional:%s\n' "$arg"
                exit 2
            fi
            ;;
    esac
done

if [ -z "$TARGET" ]; then
    printf 'decision=halt reason=error message=missing-target-id\n'
    exit 2
fi

# Default --original to the target on initial entry.
if [ -z "$ORIGINAL" ]; then
    ORIGINAL=$TARGET
fi

# --- Probe target bead ------------------------------------------------------
# Capture both stdout and exit status. `bd show` failure or null jq output
# both map to decision=halt reason=error.
TARGET_JSON=$(bd show "$TARGET" --json 2>/dev/null) || {
    printf 'decision=halt reason=error message=bd-show-failed:%s\n' "$TARGET"
    exit 1
}

STATUS=$(printf '%s' "$TARGET_JSON" | jq -r '.[0].status // "null"' 2>/dev/null) || {
    printf 'decision=halt reason=error message=jq-parse-failed:%s\n' "$TARGET"
    exit 1
}

if [ "$STATUS" = "null" ] || [ -z "$STATUS" ]; then
    printf 'decision=halt reason=error message=missing-status:%s\n' "$TARGET"
    exit 1
fi

# --- Open beads pass through unchanged -------------------------------------
if [ "$STATUS" != "closed" ]; then
    printf 'decision=proceed\n'
    exit 0
fi

# --- Count produced-bead-* labels (with prefix intact) ---------------------
# Count BEFORE stripping the prefix so that an invalid label like
# "produced-bead-" (empty Y) is still counted — its emptiness is
# diagnosed below as an explicit error halt rather than silently
# collapsing to COUNT=0 and friendly-exiting.
COUNT=$(printf '%s' "$TARGET_JSON" \
    | jq '[.[0].labels[]? | select(startswith("produced-bead-"))] | length' \
    2>/dev/null) || {
    printf 'decision=halt reason=error message=jq-labels-failed:%s\n' "$TARGET"
    exit 1
}

# --- Closed, no produced-bead-* → friendly exit ----------------------------
if [ "$COUNT" -eq 0 ]; then
    printf 'decision=friendly-exit current=%s\n' "$TARGET"
    exit 0
fi

# --- Extract Y-ids (strip prefix) for downstream branches ------------------
PRODUCED=$(printf '%s' "$TARGET_JSON" \
    | jq -r '.[0].labels[]? | select(startswith("produced-bead-")) | sub("^produced-bead-"; "")' \
    2>/dev/null) || {
    printf 'decision=halt reason=error message=jq-labels-failed:%s\n' "$TARGET"
    exit 1
}

# --- Closed, multiple produced-bead-* → halt -------------------------------
if [ "$COUNT" -ge 2 ]; then
    LABELS_CSV=$(printf '%s\n' "$PRODUCED" | tr '\n' ',' | sed 's/,$//')
    printf 'decision=halt reason=multiple original=%s intermediate=%s labels=%s\n' \
        "$ORIGINAL" "$TARGET" "$LABELS_CSV"
    exit 0
fi

# --- COUNT == 1: cycle / dangling / forward branches ------------------------
Y=$PRODUCED

# Validate Y is non-empty. An empty Y means the label was literally
# "produced-bead-" with no suffix — invalid forward pointer, halt.
if [ -z "$Y" ]; then
    printf 'decision=halt reason=error message=invalid-produced-bead-label-empty-y original=%s intermediate=%s\n' \
        "$ORIGINAL" "$TARGET"
    exit 1
fi

# Cycle check: Y already in (chain ∪ {target}).
# We compare against the chain extended with the current target, since
# revisiting the current target itself is also a cycle.
if [ -n "$CHAIN" ]; then
    EXTENDED_CHAIN=$CHAIN,$TARGET
else
    EXTENDED_CHAIN=$TARGET
fi

# Membership test: split EXTENDED_CHAIN on commas and look for Y.
CYCLE_HIT=0
OLD_IFS=$IFS
IFS=,
for item in $EXTENDED_CHAIN; do
    if [ "$item" = "$Y" ]; then
        CYCLE_HIT=1
        break
    fi
done
IFS=$OLD_IFS

if [ "$CYCLE_HIT" -eq 1 ]; then
    # Final chain reported in the halt: extended chain + the revisited Y.
    FINAL_CHAIN=$EXTENDED_CHAIN,$Y
    printf 'decision=halt reason=cycle original=%s chain=%s\n' \
        "$ORIGINAL" "$FINAL_CHAIN"
    exit 0
fi

# Y-existence probe.
if ! bd show "$Y" --json 2>/dev/null \
    | jq -e --arg yid "$Y" '.[0].id == $yid' >/dev/null 2>&1; then
    printf 'decision=halt reason=dangling original=%s intermediate=%s y=%s\n' \
        "$ORIGINAL" "$TARGET" "$Y"
    exit 0
fi

# Forward: Y exists, no cycle. Pass extended chain to next invocation.
printf 'decision=forward target=%s chain=%s\n' "$Y" "$EXTENDED_CHAIN"
exit 0
