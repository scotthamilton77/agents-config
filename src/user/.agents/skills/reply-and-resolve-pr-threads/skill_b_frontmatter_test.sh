#!/usr/bin/env bash
# Frontmatter contract test for Skill B (reply-and-resolve-pr-threads).
# Asserts AC8: model: sonnet[1m], effort: low.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL_MD="$HERE/SKILL.md"
FAIL=0

echo "[skill_b_frontmatter_test]"

if [ ! -f "$SKILL_MD" ]; then
  echo "  FAIL: SKILL.md not found at $SKILL_MD"
  exit 1
else
  echo "  ok: SKILL.md exists"
fi

# Extract frontmatter block (between first two '---' lines)
FM="$(awk '/^---$/{n++; next} n==1{print}' "$SKILL_MD")"

# AC8: model must be sonnet[1m]
if echo "$FM" | grep -qE '^model:[[:space:]]+sonnet\[1m\][[:space:]]*$'; then
  echo "  ok: model is sonnet[1m]"
else
  echo "  FAIL: model is not sonnet[1m] (frontmatter: $(echo "$FM" | grep -E '^model:'))"
  FAIL=1
fi

# AC8: effort must be low
if echo "$FM" | grep -qE '^effort:[[:space:]]+low[[:space:]]*$'; then
  echo "  ok: effort is low"
else
  echo "  FAIL: effort is not low (frontmatter: $(echo "$FM" | grep -E '^effort:'))"
  FAIL=1
fi

exit $FAIL
