#!/usr/bin/env bash
# Smoke test for build-inventory-body.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/build-inventory-body.sh"
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

echo "[build-inventory-body_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --items flag" "grep -q -- '--items' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "accepts --polling flag" "grep -q -- '--polling' '$SCRIPT'"

# Build minimal fixtures
ITEMS="$TMP/items.json"
PR="$TMP/pr.json"
POLLING="$TMP/polling.json"
echo '[{"comment_id":"c1","classification":"FIX"}]' >"$ITEMS"
echo '{"number":42,"owner":"o","repo":"r","head_sha":"abc"}' >"$PR"
echo '{"started_at":"2026-05-10T00:00:00Z","duration_s":12}' >"$POLLING"

# Happy path: outputs JSON containing required top-level keys
OUTPUT="$("$SCRIPT" --items "$ITEMS" --pr "$PR" --polling "$POLLING" 2>/dev/null || true)"
if [ -n "$OUTPUT" ] && echo "$OUTPUT" | grep -q '"schema_version"' \
   && echo "$OUTPUT" | grep -q '"pr"' \
   && echo "$OUTPUT" | grep -q '"polling"' \
   && echo "$OUTPUT" | grep -q '"items"'; then
  echo "  ok: output contains schema_version, pr, polling, items keys"
else
  echo "  FAIL: output missing required top-level keys (got: $OUTPUT)"
  FAIL=1
fi

# Failure path: missing --items must error
if "$SCRIPT" --pr "$PR" --polling "$POLLING" 2>/dev/null; then
  echo "  FAIL: accepted invocation missing --items"
  FAIL=1
else
  echo "  ok: rejects missing --items"
fi

exit $FAIL
