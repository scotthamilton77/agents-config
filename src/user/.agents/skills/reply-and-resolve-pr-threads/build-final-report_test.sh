#!/usr/bin/env bash
# Smoke test for build-final-report.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/build-final-report.sh"
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

echo "[build-final-report_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --inventory flag" "grep -q -- '--inventory' '$SCRIPT'"

# Minimal inventory fixture
INV="$TMP/inv.json"
cat >"$INV" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 42, "owner": "o", "repo": "r"},
  "items": [
    {"comment_id": "c1", "classification": "FIX", "fix_outcome": "committed"}
  ]
}
JSON

# Happy path: output must reference the fixture's comment_id (c1).
# Capture rc explicitly — no `|| true` masking real exit codes.
"$SCRIPT" --inventory "$INV" > "$TMP/out.txt" 2>&1
rc_happy=$?
assert "exits 0 on valid inventory" "[ \$rc_happy -eq 0 ]"
if grep -q 'c1' "$TMP/out.txt"; then
  echo "  ok: report references fixture comment_id"
else
  echo "  FAIL: report missing fixture comment_id; got: $(cat "$TMP/out.txt")"
  FAIL=1
fi

# Failure path: missing flag
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: nonexistent inventory
if "$SCRIPT" --inventory /nonexistent/path.json 2>/dev/null; then
  echo "  FAIL: accepted nonexistent inventory file"
  FAIL=1
else
  echo "  ok: rejects nonexistent inventory file"
fi

exit $FAIL
