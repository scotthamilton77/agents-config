#!/usr/bin/env bash
# Regression test for the `bd ... --json | jq` ID-extractor dual-shape bug.
#
# Defect: the expression `(.[0].id // .id) // empty` was used to defensively
# pull an `id` from `bd create --json` output that may be either a JSON object
# `{"id":"x"}` or an array `[{"id":"x"}]`. jq's `//` is null-or-false-only —
# it does NOT catch the runtime exception "Cannot index object with number"
# that `.[0]` throws on an object. So the broken expression aborts on the
# object shape (exit 5) instead of falling through.
#
# The fix replaces the broken form with:
#   if type == "array" then .[0].id else .id end // empty
#
# Affected production sites (must not carry the broken pattern any longer):
#   - src/plugins/beads/.beads/scripts/bd-record-decision.sh
#   - src/plugins/beads/.beads/scripts/bd-finalize-create-impl-bead.sh
#   - src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml  (3 sites)
#   - src/plugins/beads/.agents/skills/create-bead/SKILL.md  (doc snippet)
#
# This test lives under src/user/.agents/skills/ so the project's [gates].test
# command picks it up (it scans src/user/.agents/skills/**/*_test.sh only).
# It does NOT depend on its own location — only on the repo root being two
# levels up from this file's grandparent. We resolve the repo root via git.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE" && git rev-parse --show-toplevel)"
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[bd_json_extractor_dual_shape_test]"

BROKEN_EXPR='(.[0].id // .id) // empty'
FIXED_EXPR='if type == "array" then .[0].id else .id end // empty'

# --- jq-expression contract ---
# The broken expression MUST fail on object-shape input. If this assertion
# fails, jq has changed its semantics and the test premise is invalid.
set +e
printf '{"id":"x"}' | jq -r "$BROKEN_EXPR" >/dev/null 2>&1
BROKEN_RC=$?
set -e
assert "broken jq expression fails (non-zero) on object input {id:x}" \
  "[ $BROKEN_RC -ne 0 ]"

# The fixed expression MUST succeed on BOTH shapes, emitting 'x'.
set +e
FIX_OBJ_OUT="$(printf '{"id":"x"}' | jq -r "$FIXED_EXPR" 2>/dev/null)"
FIX_OBJ_RC=$?
FIX_ARR_OUT="$(printf '[{"id":"x"}]' | jq -r "$FIXED_EXPR" 2>/dev/null)"
FIX_ARR_RC=$?
set -e
assert "fixed jq expression exits 0 on object input {id:x}" \
  "[ $FIX_OBJ_RC -eq 0 ]"
assert "fixed jq expression emits 'x' on object input {id:x}" \
  "[ '$FIX_OBJ_OUT' = 'x' ]"
assert "fixed jq expression exits 0 on array input [{id:x}]" \
  "[ $FIX_ARR_RC -eq 0 ]"
assert "fixed jq expression emits 'x' on array input [{id:x}]" \
  "[ '$FIX_ARR_OUT' = 'x' ]"

# --- production-site negative grep ---
# The known-broken pattern must NOT appear anywhere under src/plugins/beads/.
# This is the bead's R5 isolation-equivalent: regression-guard that no site
# silently reverts to the broken single-shape form.
BEADS_DIR="$REPO_ROOT/src/plugins/beads"
assert "src/plugins/beads/ directory present" "[ -d '$BEADS_DIR' ]"

set +e
BROKEN_HITS="$(grep -RnE '\.\[0\]\.id // \.id' "$BEADS_DIR" 2>/dev/null || true)"
set -e
if [ -n "$BROKEN_HITS" ]; then
  echo "  FAIL: broken pattern '.[0].id // .id' still present in src/plugins/beads/:"
  printf '%s\n' "$BROKEN_HITS" | sed 's/^/    /'
  FAIL=1
else
  echo "  ok: no occurrences of '.[0].id // .id' under src/plugins/beads/"
fi

# Also forbid the naive single-shape `jq -r '.id'` form in the three known
# formula sites (which silently emit 'null' on the array shape). We scope this
# strictly to the brainstorm-bead formula since other unrelated `.id` uses in
# the tree may be legitimate.
FORMULA="$BEADS_DIR/.beads/formulas/brainstorm-bead.formula.toml"
assert "brainstorm-bead.formula.toml present" "[ -f '$FORMULA' ]"

set +e
NAIVE_HITS="$(grep -nE "jq -r '\.id'" "$FORMULA" 2>/dev/null || true)"
set -e
if [ -n "$NAIVE_HITS" ]; then
  echo "  FAIL: naive single-shape pattern \"jq -r '.id'\" still present in brainstorm-bead.formula.toml:"
  printf '%s\n' "$NAIVE_HITS" | sed 's/^/    /'
  FAIL=1
else
  echo "  ok: no naive \"jq -r '.id'\" in brainstorm-bead.formula.toml"
fi

# Doc snippet in create-bead SKILL teaches the pattern; it must also be fixed
# so users copy a correct form.
SKILL_DOC="$BEADS_DIR/.agents/skills/create-bead/SKILL.md"
assert "create-bead SKILL.md present" "[ -f '$SKILL_DOC' ]"

set +e
DOC_HITS="$(grep -nE "jq -r '\.id'" "$SKILL_DOC" 2>/dev/null || true)"
set -e
if [ -n "$DOC_HITS" ]; then
  echo "  FAIL: naive single-shape pattern \"jq -r '.id'\" still present in create-bead/SKILL.md:"
  printf '%s\n' "$DOC_HITS" | sed 's/^/    /'
  FAIL=1
else
  echo "  ok: no naive \"jq -r '.id'\" in create-bead/SKILL.md"
fi

exit $FAIL
