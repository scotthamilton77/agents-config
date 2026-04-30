#!/usr/bin/env bash
# validate-inventory.sh — schema validation guard for the PR-review hand-off contract.
#
# Reads the inventory JSON file at the given path and runs nine `jq` predicates
# (one per Schema Validation Guard in docs/specs/2026-04-26-pr-review-skill-redesign.md).
# Exits 0 if all guards pass; non-zero with a human-readable error to stderr otherwise.
#
# Usage:
#   validate-inventory.sh <inventory_json_path>

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: validate-inventory.sh <inventory_json_path>" >&2
    exit 64
fi

PATH_IN="$1"

if [ ! -f "$PATH_IN" ]; then
    echo "error: file not found: $PATH_IN" >&2
    exit 66
fi

# Guard 0: parses + correct schema version
if ! jq -e '.schema_version == 1' "$PATH_IN" >/dev/null 2>&1; then
    echo "error: inventory does not parse as JSON or schema_version != 1: $PATH_IN" >&2
    exit 1
fi

run_guard() {
    local label="$1"; shift
    local predicate="$1"; shift
    local violators
    local jq_stderr
    jq_stderr="$(mktemp)"
    if ! violators=$(jq -c "$predicate" "$PATH_IN" 2>"$jq_stderr"); then
        echo "guard error [$label]: jq failed (predicate or jq feature unsupported):" >&2
        cat "$jq_stderr" >&2
        rm -f "$jq_stderr"
        return 1
    fi
    rm -f "$jq_stderr"
    if [ -n "$violators" ] && [ "$violators" != "[]" ] && [ "$violators" != "null" ] && [ "$violators" != "false" ]; then
        echo "guard failed [$label]: $violators" >&2
        return 1
    fi
    return 0
}

FAIL=0

# Guard 1: every item has non-empty rationale (regardless of classification)
run_guard "rationale-non-empty" \
    '[.items[] | select(.rationale == null or .rationale == "")]' || FAIL=1

# Guard 2: escalation_filed only set on ESCALATE
run_guard "escalation_filed-only-on-ESCALATE" \
    '[.items[] | select(.classification != "ESCALATE" and .escalation_filed == true)]' || FAIL=1

# Guard 3: review_summary items must have null thread_id, reply_to_comment_id, issue_comment_id
run_guard "review_summary-null-ids" \
    '[.items[] | select(.kind == "review_summary" and ((.thread_id != null) or (.reply_to_comment_id != null) or (.issue_comment_id != null)))]' || FAIL=1

# Guard 4: non-FIX items must have null fix_outcome
run_guard "non-FIX-null-fix_outcome" \
    '[.items[] | select(.classification != "FIX" and .fix_outcome != null)]' || FAIL=1

# Guard 5: FIX items must have valid fix_outcome (committed | already_addressed | failed)
# Explicit equality checks rather than IN(...), which is jq 1.6+. macOS and some
# Linux distros still ship jq 1.5; using IN() there would make Guard 5 fail to
# compile, surfacing as a guard error from run_guard (other guards still run via
# `|| FAIL=1`), and the validator would exit non-zero overall.
run_guard "FIX-valid-fix_outcome" \
    '[.items[] | select(.classification == "FIX" and (.fix_outcome != "committed" and .fix_outcome != "already_addressed" and .fix_outcome != "failed"))]' || FAIL=1

# Guard 6: committed FIX requires fix_commit_sha + fix_summary + fix_gate_variant
run_guard "committed-requires-all-fields" \
    '[.items[] | select(.fix_outcome == "committed" and (.fix_commit_sha == null or .fix_summary == null or .fix_gate_variant == null))]' || FAIL=1

# Guard 7: already_addressed requires fix_commit_sha
run_guard "already_addressed-requires-sha" \
    '[.items[] | select(.fix_outcome == "already_addressed" and .fix_commit_sha == null)]' || FAIL=1

# Guard 8: every ESCALATE item must have escalation_filed=true at write time.
# Skill A's interactive Phase 3.5 reclassifies ESCALATEs to FIX/SKIP/DEFER
# before write; autonomous Phase 3.5 sets escalation_filed=true. An ESCALATE
# with escalation_filed=false at write time means a Skill A bug — Skill B
# would silently skip it without a reply.
run_guard "ESCALATE-must-be-filed" \
    '[.items[] | select(.classification == "ESCALATE" and (.escalation_filed != true))]' || FAIL=1

if [ "$FAIL" -ne 0 ]; then
    echo "error: schema validation failed for $PATH_IN" >&2
    exit 1
fi

exit 0
