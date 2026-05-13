#!/usr/bin/env bash
# Red-phase tests for AC "Container Beads section in beads.md" and
# AC "I1/I2 prose: ancestor epic → ancestor bead":
#   - Container Bead definition documented in
#     src/plugins/beads/.claude/rules/beads.md under a new
#     '## Container Beads' section.
#   - beads.md I1/I2 prose updated to type-agnostic 'ancestor bead' phrasing
#     (scoped to the I1 and I2 sections only).
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/plugins/beads" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/plugins/beads" ] \
    || fail "could not locate repo root containing src/plugins/beads (started at $SCRIPT_DIR)"

BEADS_MD="$REPO_ROOT/src/plugins/beads/.claude/rules/beads.md"
[ -f "$BEADS_MD" ] || fail "beads.md not found at $BEADS_MD"

# -----------------------------------------------------------------------------
# AC1 — Container Beads section exists and names epic, milestone, feature.
# -----------------------------------------------------------------------------
grep -Eq '^##[[:space:]]+Container Beads[[:space:]]*$' "$BEADS_MD" \
    || fail "AC1: '## Container Beads' section heading missing in beads.md"
pass "AC1: '## Container Beads' section present"

container_section=$(awk '/^## Container Beads[[:space:]]*$/{flag=1; next} /^## /{flag=0} flag' "$BEADS_MD")
[ -n "$container_section" ] || fail "AC1: Container Beads section body is empty"
for t in epic milestone feature; do
    echo "$container_section" | grep -qE "(^|[^[:alnum:]_])$t([^[:alnum:]_]|$)" \
        || fail "AC1: Container Beads section does not name type '$t'"
done
pass "AC1: Container Beads section names epic, milestone, feature"

# -----------------------------------------------------------------------------
# AC5 / I1+I2 prose update — scoped per section.
# The spec mandates updating the I1 prose: "every ancestor epic" → "every
# ancestor" (or "every ancestor bead"). Don't ban "ancestor epic" globally;
# scope to the I1 and I2 section blocks.
# -----------------------------------------------------------------------------
# Extract I1 block: from "**I1." up to but not including "**I2.".
i1_block=$(awk '/^\*\*I1\./{flag=1} /^\*\*I2\./{flag=0} flag' "$BEADS_MD")
[ -n "$i1_block" ] || fail "AC5: cannot locate I1 section block in beads.md"

# Extract I2 block: from "**I2." up to but not including "**I3.".
i2_block=$(awk '/^\*\*I2\./{flag=1} /^\*\*I3\./{flag=0} flag' "$BEADS_MD")
[ -n "$i2_block" ] || fail "AC5: cannot locate I2 section block in beads.md"

# I1 must NOT contain the phrase "ancestor epic"
if echo "$i1_block" | grep -q 'ancestor epic'; then
    fail "AC5: I1 block still contains 'ancestor epic' (spec requires removal)"
fi
pass "AC5a: I1 block no longer contains 'ancestor epic'"

# I2 must NOT contain the phrase "ancestor epic"
if echo "$i2_block" | grep -q 'ancestor epic'; then
    fail "AC5: I2 block still contains 'ancestor epic' (spec requires removal)"
fi
pass "AC5b: I2 block no longer contains 'ancestor epic'"

# AT LEAST ONE of I1 or I2 must contain the replacement phrasing.
# Accept either "ancestor bead" (preferred new phrasing) OR "every ancestor"
# (the spec's stated rewrite: "every ancestor epic" → "every ancestor").
i1_has_new=0
i2_has_new=0
echo "$i1_block" | grep -qE 'ancestor bead|every ancestor[^[:alnum:]]' && i1_has_new=1 || true
echo "$i2_block" | grep -qE 'ancestor bead|every ancestor[^[:alnum:]]' && i2_has_new=1 || true

# Per spec, BOTH I1 and I2 are about walking ancestors; both should be
# updated to the type-agnostic phrasing.
[ "$i1_has_new" = "1" ] \
    || fail "AC5c: I1 block lacks the new type-agnostic phrasing ('ancestor bead' or 'every ancestor')"
[ "$i2_has_new" = "1" ] \
    || fail "AC5d: I2 block lacks the new type-agnostic phrasing ('ancestor bead' or 'every ancestor')"
pass "AC5c+d: I1 and I2 blocks use the new type-agnostic ancestor phrasing"

echo "AC1 + AC5 beads.md red-phase tests passed."
