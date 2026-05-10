#!/usr/bin/env bash
# Frontmatter contract test for Skill A (wait-for-pr-comments).
# Asserts AC3: model: sonnet[1m], effort: medium.
# Currently fails because frontmatter is model: opus[1m], effort: high.

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

echo "[skill_a_frontmatter_test]"

assert "SKILL.md exists" "[ -f '$SKILL_MD' ]"

# Extract frontmatter block (between first two '---' lines)
FM="$(awk '/^---$/{n++; next} n==1{print}' "$SKILL_MD")"

# AC3: model must be sonnet[1m]
if echo "$FM" | grep -qE '^model:[[:space:]]+sonnet\[1m\][[:space:]]*$'; then
  echo "  ok: model is sonnet[1m]"
else
  echo "  FAIL: model is not sonnet[1m] (frontmatter: $(echo "$FM" | grep -E '^model:'))"
  FAIL=1
fi

# AC3: effort must be medium
if echo "$FM" | grep -qE '^effort:[[:space:]]+medium[[:space:]]*$'; then
  echo "  ok: effort is medium"
else
  echo "  FAIL: effort is not medium (frontmatter: $(echo "$FM" | grep -E '^effort:'))"
  FAIL=1
fi

exit $FAIL
