#!/usr/bin/env bash
# Smoke test for post-replies.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/post-replies.sh"
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

echo "[post-replies_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --inventory flag" "grep -q -- '--inventory' '$SCRIPT'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "accepts --skip-comment-ids flag" "grep -q -- '--skip-comment-ids' '$SCRIPT'"

# Failure path: invoking without --inventory must fail (flag validation)
if "$SCRIPT" --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted invocation without --inventory"
  FAIL=1
else
  echo "  ok: rejects missing --inventory"
fi

# Failure path: bad inventory path must fail
if "$SCRIPT" --inventory /nonexistent/path.json --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted nonexistent inventory file"
  FAIL=1
else
  echo "  ok: rejects nonexistent inventory file"
fi

exit $FAIL
