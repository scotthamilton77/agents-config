#!/usr/bin/env bash
# Red-phase tests for AC "Container Beads spec lives in collect.py" and
# AC "I1/I2 prose: ancestor epic → ancestor bead":
#   - Container-Bead spec (three rules + filter matrix) lives in
#     src/user/.agents/skills/whats-next/collect.py module-level docs,
#     NOT in src/plugins/beads/.claude/rules/beads.md (which loads in every
#     context and should not carry the full routing spec).
#   - beads.md retains a short breadcrumb plus the I1/I2 walks (now driven by
#     bd-claim-walk.sh / bd-close-walk.sh helper scripts).
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
COLLECT_PY="$REPO_ROOT/src/user/.agents/skills/whats-next/collect.py"
[ -f "$BEADS_MD" ] || fail "beads.md not found at $BEADS_MD"
[ -f "$COLLECT_PY" ] || fail "collect.py not found at $COLLECT_PY"

# -----------------------------------------------------------------------------
# AC1 — Container-Bead spec lives in collect.py (not beads.md), and names
# epic, milestone, feature. Also covers the three rules + filter matrix that
# define the routing contract.
# -----------------------------------------------------------------------------

# beads.md should NOT carry the full routing spec — the Three Rules and the
# Filter Matrix table belong next to the enforcement code.
if grep -qE '^### (The )?Three Rules[[:space:]]*$' "$BEADS_MD"; then
    fail "AC1: Three-Rules section still in beads.md (must move to collect.py)"
fi
if grep -qE '^### Filter Matrix[[:space:]]*$' "$BEADS_MD"; then
    fail "AC1: Filter Matrix section still in beads.md (must move to collect.py)"
fi
pass "AC1a: beads.md does not carry the full Container-Bead routing spec"

# beads.md should still acknowledge container beads via a short breadcrumb
# referring readers to the canonical location.
grep -qiE 'container bead' "$BEADS_MD" \
    || fail "AC1b: beads.md must keep a short breadcrumb mentioning container beads"
pass "AC1b: beads.md keeps a container-bead breadcrumb"

# collect.py must carry the three rules AND the filter matrix in its module-
# level documentation, alongside type tokens.
for marker in 'Rule A' 'Rule B' 'Rule C' 'Filter Matrix'; do
    grep -qF "$marker" "$COLLECT_PY" \
        || fail "AC1c: collect.py missing routing-spec marker: $marker"
done
for t in epic milestone feature; do
    grep -qE "(^|[^[:alnum:]_])$t([^[:alnum:]_]|$)" "$COLLECT_PY" \
        || fail "AC1c: collect.py Container-Bead docs do not name type '$t'"
done
pass "AC1c: collect.py carries the three rules + filter matrix + type tokens"

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
