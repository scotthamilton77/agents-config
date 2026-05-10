#!/usr/bin/env bash
# Smoke test for audit-subagent-report.sh
# Helper does not exist yet — these tests MUST fail in red phase.
#
# Contract:
#   exit 0 = audit pass
#   exit 1 = audit failure (JSON {violation,rationale} on stdout)
#   exit 2 = schema violation (JSON {field,message} on stdout)

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/audit-subagent-report.sh"
WT="/Users/scott/src/projects/agents-config/.claude/worktrees/feat/agents-config-abn9.4-optimize-pr-review-comments"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[audit-subagent-report_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents exit codes (0/1/2) in header" "head -40 '$SCRIPT' | grep -qE 'exit'"
assert "accepts --pre-sha flag" "grep -q -- '--pre-sha' '$SCRIPT'"
assert "accepts --baseline-sha flag" "grep -q -- '--baseline-sha' '$SCRIPT'"
assert "accepts --report flag" "grep -q -- '--report' '$SCRIPT'"
assert "accepts --worktree-root flag" "grep -q -- '--worktree-root' '$SCRIPT'"

# --- Exit-2 fixture: schema violation — missing required field ---
# A valid schema requires at minimum: comment_id, classification, fix_outcome.
# This fixture omits comment_id, so the script must exit 2 and emit
# {field, message} JSON on stdout.
SCHEMA_BAD="$TMP/schema-bad.json"
cat >"$SCHEMA_BAD" <<'JSON'
{
  "schema_version": 1,
  "classification": "FIX",
  "fix_outcome": "committed"
}
JSON

"$SCRIPT" --pre-sha deadbeefdeadbeefdeadbeefdeadbeefdeadbeef \
          --baseline-sha cafebabecafebabecafebabecafebabecafebabe \
          --report "$SCHEMA_BAD" \
          --worktree-root "$WT" > "$TMP/out-bad.json" 2>&1
rc_bad=$?
if [ "$rc_bad" = "2" ]; then
  echo "  ok: schema-bad report exits 2"
else
  echo "  FAIL: schema-bad report should exit 2, got $rc_bad"
  FAIL=1
fi
if grep -qE '"field"|"message"' "$TMP/out-bad.json"; then
  echo "  ok: schema violation emits {field,message} on stdout"
else
  echo "  FAIL: schema violation output missing field/message keys; got: $(cat "$TMP/out-bad.json")"
  FAIL=1
fi

# --- Exit-1 fixture: audit failure ---
# Valid schema, but fix_commit_sha references a SHA that provably does NOT
# exist in this repo. The ancestry/existence check must fail → exit 1 with
# {violation, rationale} JSON on stdout.
NONEXISTENT_SHA="0000000000000000000000000000000000000001"
AUDIT_FAIL="$TMP/audit-fail.json"
cat >"$AUDIT_FAIL" <<JSON
{
  "schema_version": 1,
  "comment_id": "c1",
  "classification": "FIX",
  "fix_outcome": "committed",
  "fix_commit_sha": "$NONEXISTENT_SHA",
  "fix_summary": "claimed but unverifiable",
  "fix_gate_variant": "fast",
  "verification_evidence": {"test_command": "bash test.sh", "output": "ok"}
}
JSON

HEAD_SHA="$(git -C "$WT" rev-parse HEAD 2>/dev/null || echo "0000000000000000000000000000000000000000")"
"$SCRIPT" --pre-sha "$HEAD_SHA" \
          --baseline-sha "$HEAD_SHA" \
          --report "$AUDIT_FAIL" \
          --worktree-root "$WT" > "$TMP/out-fail.json" 2>&1
rc_fail=$?
if [ "$rc_fail" = "1" ]; then
  echo "  ok: audit-failure report exits 1"
else
  echo "  FAIL: audit-failure report should exit 1, got $rc_fail"
  FAIL=1
fi
if grep -qE '"violation"|"rationale"' "$TMP/out-fail.json"; then
  echo "  ok: audit failure emits {violation,rationale} on stdout"
else
  echo "  FAIL: audit-failure output missing violation/rationale keys; got: $(cat "$TMP/out-fail.json")"
  FAIL=1
fi

# --- Exit-0 fixture: audit pass ---
# Valid schema and ancestry check passes (HEAD is trivially an ancestor of
# itself, and fix_commit_sha exists). Pass HEAD as both fix_commit_sha and
# pre/baseline sha so all ancestry checks succeed.
AUDIT_PASS="$TMP/audit-pass.json"
cat >"$AUDIT_PASS" <<JSON
{
  "schema_version": 1,
  "comment_id": "c1",
  "classification": "FIX",
  "fix_outcome": "committed",
  "fix_commit_sha": "$HEAD_SHA",
  "fix_summary": "fixed and verified",
  "fix_gate_variant": "fast",
  "verification_evidence": {"test_command": "bash test.sh", "output": "ok"}
}
JSON

"$SCRIPT" --pre-sha "$HEAD_SHA" \
          --baseline-sha "$HEAD_SHA" \
          --report "$AUDIT_PASS" \
          --worktree-root "$WT" > "$TMP/out-pass.json" 2>&1
rc_pass=$?
if [ "$rc_pass" = "0" ]; then
  echo "  ok: valid+ancestry-clean report exits 0"
else
  echo "  FAIL: valid+ancestry-clean report should exit 0, got $rc_pass (output: $(cat "$TMP/out-pass.json"))"
  FAIL=1
fi

# --- Flag-validation path: missing --report must error ---
if "$SCRIPT" --pre-sha "$HEAD_SHA" --baseline-sha "$HEAD_SHA" --worktree-root "$WT" 2>/dev/null; then
  echo "  FAIL: accepted invocation missing --report"
  FAIL=1
else
  echo "  ok: rejects missing --report"
fi

exit $FAIL
