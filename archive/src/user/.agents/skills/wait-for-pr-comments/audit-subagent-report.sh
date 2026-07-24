#!/usr/bin/env bash
# Purpose: validate a per-comment fix subagent's report against the fix_outcome
# schema, then run audit checks (SHA ancestry, commit count).
#
# Inputs:
#   --pre-sha       <sha>   HEAD SHA before fix subagent ran
#   --baseline-sha  <sha>   phase4_baseline_sha — the HEAD SHA captured at Phase 4 start, before any fix subagents run
#   --report        <file>  JSON file produced by the fix subagent
#   --worktree-root <path>  absolute path to the worktree (git -C target)
#
# Outputs:
#   stdout:
#     exit 0 → (no output)
#     exit 1 → JSON {violation, rationale}   audit failure
#     exit 2 → JSON {field,     message}     schema violation
#   exit codes:
#     0 = audit pass
#     1 = audit failure (ancestry / commit-count)
#     2 = schema violation (missing/invalid required field)
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --pre-sha <sha> --baseline-sha <sha> --report <file> --worktree-root <path>

Validates fix_outcome schema (exit 2) + audits SHA ancestry (exit 1). Exit 0 = pass.
EOF
  exit 2
}

PRE_SHA=""
BASELINE_SHA=""
REPORT=""
WT_ROOT=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --pre-sha)       PRE_SHA="${2:-}";      shift 2 ;;
    --baseline-sha)  BASELINE_SHA="${2:-}"; shift 2 ;;
    --report)        REPORT="${2:-}";       shift 2 ;;
    --worktree-root) WT_ROOT="${2:-}";      shift 2 ;;
    -h|--help)       usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$PRE_SHA" ] && [ -n "$BASELINE_SHA" ] && [ -n "$REPORT" ] && [ -n "$WT_ROOT" ] || {
  echo "error: --pre-sha, --baseline-sha, --report, --worktree-root are all required" >&2
  exit 2
}

[ -f "$REPORT" ] || { echo "error: report file not found: $REPORT" >&2; exit 2; }

emit_schema_violation() {
  jq -nc --arg f "$1" --arg m "$2" '{field: $f, message: $m}'
  exit 2
}

emit_audit_violation() {
  jq -nc --arg v "$1" --arg r "$2" '{violation: $v, rationale: $r}'
  exit 1
}

# --- Schema validation ---
# Required: comment_id (string), fix_outcome (enum).
COMMENT_ID="$(jq -r '.comment_id // empty' "$REPORT" 2>/dev/null || true)"
[ -n "$COMMENT_ID" ] || emit_schema_violation "comment_id" "missing required field"

FIX_OUTCOME="$(jq -r '.fix_outcome // empty' "$REPORT" 2>/dev/null || true)"
[ -n "$FIX_OUTCOME" ] || emit_schema_violation "fix_outcome" "missing required field"

case "$FIX_OUTCOME" in
  committed|deferred|already_addressed|escalated|abandoned|failed) ;;
  *) emit_schema_violation "fix_outcome" "invalid enum value: $FIX_OUTCOME" ;;
esac

FIX_SUMMARY="$(jq -r '.fix_summary // empty' "$REPORT" 2>/dev/null || true)"
[ -n "$FIX_SUMMARY" ] || emit_schema_violation "fix_summary" "missing required field"

# Conditional requirements
case "$FIX_OUTCOME" in
  committed|already_addressed)
    FIX_SHA="$(jq -r '.fix_commit_sha // empty' "$REPORT" 2>/dev/null || true)"
    [ -n "$FIX_SHA" ] || emit_schema_violation "fix_commit_sha" "required when fix_outcome=$FIX_OUTCOME"
    ;;
esac

if [ "$FIX_OUTCOME" = "committed" ]; then
  FIX_VARIANT="$(jq -r '.fix_gate_variant // empty' "$REPORT" 2>/dev/null || true)"
  case "$FIX_VARIANT" in
    lite|full) ;;
    *) emit_schema_violation "fix_gate_variant" "required when fix_outcome=committed; got: $FIX_VARIANT" ;;
  esac

  EV_CMD="$(jq -r '.verification_evidence.test_command // empty' "$REPORT" 2>/dev/null || true)"
  EV_OUT="$(jq -r '.verification_evidence.output // empty' "$REPORT" 2>/dev/null || true)"
  [ -n "$EV_CMD" ] || emit_schema_violation "verification_evidence.test_command" "required when fix_outcome=committed"
  [ -n "$EV_OUT" ] || emit_schema_violation "verification_evidence.output" "required when fix_outcome=committed"
fi

# --- Audit checks (only for outcomes that claim a commit exists) ---
case "$FIX_OUTCOME" in
  committed)
    FIX_SHA="$(jq -r '.fix_commit_sha' "$REPORT")"

    # SHA must exist in the worktree.
    if ! git -C "$WT_ROOT" cat-file -e "${FIX_SHA}^{commit}" 2>/dev/null; then
      emit_audit_violation "fix_commit_sha_not_found" \
        "fix_commit_sha $FIX_SHA does not exist in worktree $WT_ROOT"
    fi

    # For committed: the fix is a NEW commit made AFTER pre_sha. It must NOT
    # be an ancestor of pre_sha (otherwise it predates the subagent's run).
    if git -C "$WT_ROOT" merge-base --is-ancestor "$FIX_SHA" "$PRE_SHA" 2>/dev/null; then
      emit_audit_violation "fix_commit_predates_subagent" \
        "fix_commit_sha $FIX_SHA predates or equals pre-sha $PRE_SHA (must be a newer commit)"
    fi

    # Fix commit must be reachable from current HEAD
    if ! git -C "$WT_ROOT" merge-base --is-ancestor "$FIX_SHA" HEAD 2>/dev/null; then
      emit_audit_violation "fix_commit_not_in_head" \
        "fix_commit_sha $FIX_SHA is not an ancestor of current HEAD"
    fi

    # Exactly one new commit since pre_sha, and it must match the reported SHA
    COMMIT_COUNT=$(git -C "$WT_ROOT" rev-list "${PRE_SHA}..HEAD" --count 2>/dev/null)
    ACTUAL_FIX_SHA=$(git -C "$WT_ROOT" rev-list "${PRE_SHA}..HEAD" 2>/dev/null | head -1)
    if [ "$COMMIT_COUNT" != "1" ]; then
      emit_audit_violation "unexpected_commit_count" \
        "expected exactly 1 new commit since pre-sha $PRE_SHA; got $COMMIT_COUNT"
    elif [ "$ACTUAL_FIX_SHA" != "$FIX_SHA" ]; then
      emit_audit_violation "fix_commit_sha_mismatch" \
        "reported fix_commit_sha $FIX_SHA differs from actual new commit $ACTUAL_FIX_SHA"
    fi
    ;;
  already_addressed)
    FIX_SHA="$(jq -r '.fix_commit_sha' "$REPORT")"

    # SHA must exist in the worktree.
    if ! git -C "$WT_ROOT" cat-file -e "${FIX_SHA}^{commit}" 2>/dev/null; then
      emit_audit_violation "fix_commit_sha_not_found" \
        "fix_commit_sha $FIX_SHA does not exist in worktree $WT_ROOT"
    fi

    # For already_addressed: the fix predates the session start, so it MUST be
    # an ancestor of baseline_sha (it existed before the session).
    if ! git -C "$WT_ROOT" merge-base --is-ancestor "$FIX_SHA" "$BASELINE_SHA" 2>/dev/null; then
      emit_audit_violation "fix_commit_not_in_baseline" \
        "fix_commit_sha $FIX_SHA is not an ancestor of baseline-sha $BASELINE_SHA"
    fi
    ;;
esac

exit 0
