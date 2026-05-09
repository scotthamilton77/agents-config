#!/usr/bin/env bash
# bd-migrate-deps.sh — Migrate dep edges from <source> to <target> (bidirectional).
#
# Implements brainstorm-bead.formula.toml STEP 6 §3 mechanical rubric:
# retarget both OUTBOUND (X -> OTHER) and INBOUND (OTHER -> X) dep edges
# from a brainstorm seed bead X to its produced implementation bead Y.
#
# Symmetric rubric (applies in BOTH directions):
#   dep_type                                                  | linked status   | action
#   blocks (or "blocked-by" for legacy edges created with     | any             | migrate
#     `bd dep add --type blocked-by`; normalized on write)    |                 |
#   tracks, until, caused-by, validates, relates-to,          | any             | migrate
#     supersedes                                              |                 |
#   discovered-from, related                                  | closed          | keep on X
#   discovered-from, related                                  | open / wip      | migrate
#   parent-child                                              | any             | SKIP
#   unknown dep type                                          | any             | WARN + migrate
#
# Cost: O(N_out + N_in) — exactly two `bd dep list` calls capture all edges
# and their statuses inline via the `.status` field. No per-edge `bd show`
# status calls are issued. Plus O(N_migrated) `bd dep add` / `bd dep remove`
# pairs. Typical total << 40 bd calls.
#
# Idempotent: re-running after a partial failure produces the same end state.
# Already-migrated edges no longer appear in X's dep list (in either direction),
# so a replay is a no-op for them.
#
# Failure semantics (consistent with sibling helpers):
#   - bd dep add failure (incl. cycle errors) → WARN, retain X-side, continue.
#     Does NOT use --no-cycle-check; bd's default cycle detection stays in force.
#   - bd dep remove failure after a successful add → WARN, retain both edges,
#     continue. Replay will re-attempt the remove because the X-side edge is
#     still visible to the iterator.
#   - All other bd/jq/shell failures → propagate non-zero (set -euo pipefail).
#
# Usage:
#   bd-migrate-deps.sh --source <X> --target <Y>
#
# Exit: 0 on success; non-zero on input-arg errors or unguarded bd/jq failures.

set -euo pipefail

SOURCE=""
TARGET=""

usage() {
    cat >&2 <<'EOF'
Usage: bd-migrate-deps.sh --source <X> --target <Y>

Migrate dep edges from <X> (source) to <Y> (target), in both directions.

Walks both X's outbound edges (X -> OTHER, via `bd dep list <X> --direction=down`)
and X's inbound edges (OTHER -> X, via `bd dep list <X> --direction=up`), and
applies the brainstorm-bead §3 mechanical rubric to retarget each edge onto Y.

Skips: parent-child edges (any direction), self-loops (other == X), and the
freshly-created Y-discovered-from-X seed link (inbound edge where source == Y).

Idempotent. Safe to replay after partial failure.

Options:
  --source <id>    Bead whose edges are being migrated FROM (required)
  --target <id>    Bead the edges are being retargeted TO (required)
  -h, --help       Show this help

Exits non-zero immediately if --source == --target (copy-paste guard) or
either flag is missing.
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            [[ $# -ge 2 ]] || { echo "Error: --source requires a value" >&2; usage; }
            SOURCE="$2"; shift 2 ;;
        --target)
            [[ $# -ge 2 ]] || { echo "Error: --target requires a value" >&2; usage; }
            TARGET="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

[[ -z "$SOURCE" ]] && { echo "Error: --source is required" >&2; usage; }
[[ -z "$TARGET" ]] && { echo "Error: --target is required" >&2; usage; }
[[ "$SOURCE" == "$TARGET" ]] && {
    echo "Error: --source and --target must differ (got '$SOURCE' for both)" >&2
    exit 1
}

# Apply the §3 rubric to one edge.
#
# Args:
#   $1 = dep_type     (raw, as emitted by bd dep list — may be "blocked-by")
#   $2 = other_id     (the bead at the OTHER end of the edge from X's perspective)
#   $3 = other_status (status of OTHER, read inline from the dep list .status field)
#   $4 = direction    ("out" for X -> OTHER, "in" for OTHER -> X)
#
# For each migrated edge:
#   - Normalizes "blocked-by" → "blocks" before calling bd dep add (bd dep add
#     does not accept "blocked-by"; bd reports it for both ends of a blocks edge).
#   - Outbound: bd dep add <Y> <OTHER> --type <T>; on success → bd dep remove <X> <OTHER>
#   - Inbound:  bd dep add <OTHER> <Y> --type <T>; on success → bd dep remove <OTHER> <X>
#     (positional convention: arg1 is the dependent bead, arg2 is the blocker/target)
migrate_edge() {
    local dep_type="$1"
    local other_id="$2"
    local other_status="$3"
    local direction="$4"

    # Skip parent-child in both directions; handled by Y.parent = X.parent
    # and the §4 children-placement step of brainstorm-bead.
    [[ "$dep_type" == "parent-child" ]] && return 0

    # Skip edges to the migration target itself — applies to both the inbound
    # Y-discovered-from-X seed link and any pre-wired outbound X→Y edges.
    # bd's add-side would reject the resulting Y→Y self-loop with an error,
    # but skipping here avoids a noisy WARN for a valid graph state.
    [[ "$other_id" == "$TARGET" ]] && return 0

    # Defensive guard: skip self-loops (other == X). Should not occur in
    # a well-formed graph, but bd dep list could surface one if somehow created.
    [[ "$other_id" == "$SOURCE" ]] && return 0

    # Decide whether to migrate per the §3 rubric.
    local migrate
    case "$dep_type" in
        blocks|blocked-by|tracks|until|caused-by|validates|relates-to|supersedes)
            migrate=1 ;;
        discovered-from|related)
            if [[ "$other_status" == "closed" ]]; then
                migrate=0
            else
                migrate=1
            fi ;;
        *)
            # Unknown dep type — be conservative; migrate by default and log.
            echo "WARN: unknown dep_type '$dep_type' on edge involving $SOURCE and $other_id; migrating to $TARGET by default."
            migrate=1 ;;
    esac

    [[ "$migrate" == "1" ]] || return 0

    # Normalize "blocked-by" → "blocks" before calling bd dep add.
    # `bd dep add --type blocked-by` is accepted and stores edges with
    # dependency_type="blocked-by"; normalizing to the canonical "blocks"
    # ensures migrated edges have the standard shape.
    local add_type="$dep_type"
    [[ "$add_type" == "blocked-by" ]] && add_type="blocks"

    # Build the (dependent, blocker) tuple for bd dep add per the positional
    # convention: arg1 = dependent bead, arg2 = blocker/target bead.
    local add_dependent add_blocker remove_a remove_b
    if [[ "$direction" == "out" ]]; then
        # X -> OTHER becomes Y -> OTHER
        add_dependent="$TARGET"; add_blocker="$other_id"
        remove_a="$SOURCE";      remove_b="$other_id"
    else
        # OTHER -> X becomes OTHER -> Y
        add_dependent="$other_id"; add_blocker="$TARGET"
        remove_a="$other_id";      remove_b="$SOURCE"
    fi

    # Gate the X-side remove on a successful Y-side add: if `bd dep add`
    # fails for any reason (incl. cycle detection), keep the original edge
    # to preserve dep-graph integrity. Never drop edges silently.
    if bd dep add "$add_dependent" "$add_blocker" --type "$add_type"; then
        # `bd dep remove` is positional-only (issue-id, depends-on-id); no --type flag.
        bd dep remove "$remove_a" "$remove_b" \
            || echo "WARN: bd dep remove $remove_a $remove_b failed; both edges retained (replay will reattempt)."
    else
        echo "WARN: bd dep add $add_dependent $add_blocker --type $add_type failed; X edge retained to preserve dep graph."
    fi
}

# ── Outbound: X -> OTHER edges ──────────────────────────────────────────────
# `bd dep list <X> --direction=down --json` returns one entry per outbound
# edge with .id (other end), .dependency_type, and .status (of the other end).
OUT_JSON=$(bd dep list "$SOURCE" --direction=down --json)
# Pre-render to variable so jq parse failures propagate via set -e rather than
# silently producing zero iterations from inside a process-substitution subshell.
OUT_TSV=$(printf '%s' "$OUT_JSON" | jq -r '.[] | "\(.dependency_type)\t\(.id)\t\(.status // "open")"')
while IFS=$'\t' read -r dep_type other_id other_status; do
    # Guard against empty lines from a zero-item list or malformed records.
    [[ -z "$dep_type" ]] && continue
    migrate_edge "$dep_type" "$other_id" "$other_status" "out"
done <<< "$OUT_TSV"

# ── Inbound: OTHER -> X edges ───────────────────────────────────────────────
# `bd dep list <X> --direction=up --json` returns one entry per inbound edge
# with the same shape (.id is the OTHER bead — i.e. the source of the inbound edge).
# migrate_edge skips the Y-discovered-from-X seed link (other_id == TARGET).
IN_JSON=$(bd dep list "$SOURCE" --direction=up --json)
IN_TSV=$(printf '%s' "$IN_JSON" | jq -r '.[] | "\(.dependency_type)\t\(.id)\t\(.status // "open")"')
while IFS=$'\t' read -r dep_type other_id other_status; do
    [[ -z "$dep_type" ]] && continue
    migrate_edge "$dep_type" "$other_id" "$other_status" "in"
done <<< "$IN_TSV"
