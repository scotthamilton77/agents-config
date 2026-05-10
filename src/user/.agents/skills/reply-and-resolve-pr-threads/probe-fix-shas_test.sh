#!/usr/bin/env bash
# Smoke test for probe-fix-shas.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/probe-fix-shas.sh"
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

echo "[probe-fix-shas_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --branch flag" "grep -q -- '--branch' '$SCRIPT'"
assert "accepts --items flag" "grep -q -- '--items' '$SCRIPT'"

# Minimal inventory fixture
ITEMS="$TMP/items.json"
echo '[{"comment_id":"c1","fix_sha":"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"}]' >"$ITEMS"

# Failure path: missing flags
if "$SCRIPT" 2>/dev/null; then
  echo "  FAIL: accepted invocation with no flags"
  FAIL=1
else
  echo "  ok: rejects missing required flags"
fi

# Failure path: unknown flag rejected
if "$SCRIPT" --branch main --items "$ITEMS" --bogus 2>/dev/null; then
  echo "  FAIL: accepted unknown flag"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL
