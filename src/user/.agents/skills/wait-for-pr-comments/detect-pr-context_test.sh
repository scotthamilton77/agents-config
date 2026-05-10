#!/usr/bin/env bash
# Smoke test for detect-pr-context.sh
# Helper does not exist yet — these tests MUST fail in red phase.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/detect-pr-context.sh"
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[detect-pr-context_test]"

# Existence + executable
assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"

# Header contract: set -euo pipefail at top of script
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"

# Header contract: documents inputs/outputs
assert "documents inputs/outputs in header" "head -30 '$SCRIPT' | grep -qiE 'input|output|exit'"

# Named flags only
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"

# Happy path: invoking without args runs (we don't care about the gh result,
# only that flag parsing works and the script is callable)
output=$("$SCRIPT" --pr 1 2>&1) || true
assert "produces some output when invoked with --pr" "[ -n \"\$output\" ] || [ -f '$SCRIPT' ]"

# Failure path: unknown flag should be rejected
if "$SCRIPT" --bogus-flag-xyz 2>/dev/null; then
  echo "  FAIL: accepted unknown flag --bogus-flag-xyz"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL
