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

# Happy path: invocation with --pr must either produce JSON-shaped output
# containing the expected context keys, or exit non-zero. A passing
# invocation that emits no recognizable output is a contract violation.
output=$("$SCRIPT" --pr 1 2>&1); rc=$?
assert "exits non-zero or emits pr_number/owner/repo in JSON output" \
  "echo \"\$output\" | grep -qE '\"pr_number\"|\"owner\"|\"repo\"' || [ \$rc -ne 0 ]"

# Failure path: unknown flag should be rejected (--bogus FIRST so it's seen
# before any valid flag, preventing I/O before flag validation)
if "$SCRIPT" --bogus-flag-xyz --pr 1 2>/dev/null; then
  echo "  FAIL: accepted unknown flag --bogus-flag-xyz"
  FAIL=1
else
  echo "  ok: rejects unknown flag"
fi

exit $FAIL
