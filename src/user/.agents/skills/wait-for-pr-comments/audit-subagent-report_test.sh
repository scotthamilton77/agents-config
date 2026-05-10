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

# Build a valid-ish report fixture
VALID_REPORT="$TMP/valid.json"
cat >"$VALID_REPORT" <<'JSON'
{
  "schema_version": 1,
  "comment_id": "abc123",
  "classification": "FIX",
  "fix_outcome": "committed",
  "pre_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
  "post_sha": "cafebabecafebabecafebabecafebabecafebabe",
  "files_touched": ["src/foo.ts"],
  "rationale": "Applied the suggested fix."
}
JSON

# Schema violation fixture — missing required field "classification"
SCHEMA_BAD="$TMP/schema-bad.json"
cat >"$SCHEMA_BAD" <<'JSON'
{
  "schema_version": 1,
  "comment_id": "abc123",
  "fix_outcome": "committed",
  "pre_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
  "post_sha": "cafebabecafebabecafebabecafebabecafebabe",
  "rationale": "missing classification"
}
JSON

# Happy path: any of {exit 0, exit 1} acceptable as a passing structural test —
# the audit might legitimately conclude "fail" because pre_sha != HEAD in this
# tmp dir. What MUST hold is that exit is not 2 (schema is well-formed).
out_valid="$( "$SCRIPT" --pre-sha deadbeefdeadbeefdeadbeefdeadbeefdeadbeef --baseline-sha cafebabecafebabecafebabecafebabecafebabe --report "$VALID_REPORT" --worktree-root "$TMP" 2>/dev/null || true )"
rc_valid=$?
# We re-run capturing rc properly
"$SCRIPT" --pre-sha deadbeefdeadbeefdeadbeefdeadbeefdeadbeef --baseline-sha cafebabecafebabecafebabecafebabecafebabe --report "$VALID_REPORT" --worktree-root "$TMP" >/dev/null 2>&1
rc_valid=$?
if [ "$rc_valid" = "2" ]; then
  echo "  FAIL: well-formed report reported as schema violation (exit 2)"
  FAIL=1
else
  echo "  ok: well-formed report does not exit 2"
fi

# Schema violation path: missing field must yield exit 2
"$SCRIPT" --pre-sha deadbeefdeadbeefdeadbeefdeadbeefdeadbeef --baseline-sha cafebabecafebabecafebabecafebabecafebabe --report "$SCHEMA_BAD" --worktree-root "$TMP" >/dev/null 2>&1
rc_bad=$?
if [ "$rc_bad" = "2" ]; then
  echo "  ok: schema-bad report exits 2"
else
  echo "  FAIL: schema-bad report should exit 2, got $rc_bad"
  FAIL=1
fi

# Failure path: missing --report flag must error
if "$SCRIPT" --pre-sha x --baseline-sha y --worktree-root "$TMP" 2>/dev/null; then
  echo "  FAIL: accepted invocation missing --report"
  FAIL=1
else
  echo "  ok: rejects missing --report"
fi

exit $FAIL
