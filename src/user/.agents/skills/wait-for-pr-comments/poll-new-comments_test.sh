#!/usr/bin/env bash
# Smoke test for poll-new-comments.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/poll-new-comments.sh"
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

echo "[poll-new-comments_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -25 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"
assert "accepts --baseline flag" "grep -q -- '--baseline' '$SCRIPT'"
assert "accepts --interval flag" "grep -q -- '--interval' '$SCRIPT'"
assert "accepts --max-duration flag" "grep -q -- '--max-duration' '$SCRIPT'"
assert "no positional owner/repo parsing" "! grep -qE '^\s*REPO=\"\\\$1\"' '$SCRIPT'"

# Missing required flags — exit 3
"$SCRIPT" 2>/dev/null
rc_no_args=$?
assert "exits 3 with no flags" "[ \$rc_no_args -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --baseline 0 --interval 5 2>/dev/null
rc_no_max=$?
assert "exits 3 when --max-duration missing" "[ \$rc_no_max -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --baseline 0 --max-duration 60 2>/dev/null
rc_no_interval=$?
assert "exits 3 when --interval missing" "[ \$rc_no_interval -eq 3 ]"

# Bad numeric values
"$SCRIPT" --owner o --repo r --pr notanumber --baseline 0 --interval 5 --max-duration 60 2>/dev/null
rc_bad_pr=$?
assert "exits 3 for non-integer --pr" "[ \$rc_bad_pr -eq 3 ]"

"$SCRIPT" --owner o --repo r --pr 1 --baseline 0 --interval 0 --max-duration 60 2>/dev/null
rc_zero_interval=$?
assert "exits 3 for --interval 0" "[ \$rc_zero_interval -eq 3 ]"

# Unknown flag
"$SCRIPT" --owner o --repo r --pr 1 --baseline 0 --interval 5 --max-duration 60 --bogus 2>/dev/null
rc_bogus=$?
assert "exits 3 for unknown flag" "[ \$rc_bogus -eq 3 ]"

exit $FAIL
