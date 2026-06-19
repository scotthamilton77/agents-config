#!/usr/bin/env bash
# Frontmatter contract test for the monitor-pr skill.
# Pins the harness-consumed frontmatter: model: sonnet[1m], effort: medium.
# (A wrong `model` switches model mid-conversation and can overflow context;
# this is a real contract at the harness boundary, not a literal tautology.)

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_MD="$HERE/SKILL.md"
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[monitor_pr_frontmatter_test]"

assert "SKILL.md exists" "[ -f '$SKILL_MD' ]"

# Extract the frontmatter block (between the first two '---' lines).
FM="$(awk '/^---$/{n++; next} n==1{print}' "$SKILL_MD" 2>/dev/null)"

if echo "$FM" | grep -qE '^model:[[:space:]]+sonnet\[1m\][[:space:]]*$'; then
  echo "  ok: model is sonnet[1m]"
else
  echo "  FAIL: model is not sonnet[1m] (frontmatter: $(echo "$FM" | grep -E '^model:'))"
  FAIL=1
fi

if echo "$FM" | grep -qE '^effort:[[:space:]]+medium[[:space:]]*$'; then
  echo "  ok: effort is medium"
else
  echo "  FAIL: effort is not medium (frontmatter: $(echo "$FM" | grep -E '^effort:'))"
  FAIL=1
fi

exit $FAIL
