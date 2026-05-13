#!/usr/bin/env bash
# Red-phase tests for:
#   AC1 — Container Bead definition documented in
#         src/plugins/beads/.claude/rules/beads.md under a new 'Container Beads' section.
#   AC5 — beads.md I1/I2 prose updated: 'ancestor epic' → 'ancestor bead'.
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# Resolve repo root by walking up from this script to a directory that has
# both src/ and a .git or src/plugins.
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
# AC1 — Container Beads section exists.
# -----------------------------------------------------------------------------
grep -Eq '^##[[:space:]]+Container Beads[[:space:]]*$' "$BEADS_MD" \
    || fail "AC1: '## Container Beads' section heading missing in beads.md"
pass "AC1: '## Container Beads' section present"

# Section must define what a container bead IS (mentions the types that
# qualify: epic, milestone, feature).
container_section=$(awk '/^## Container Beads[[:space:]]*$/{flag=1; next} /^## /{flag=0} flag' "$BEADS_MD")
[ -n "$container_section" ] || fail "AC1: Container Beads section body is empty"
for t in epic milestone feature; do
    echo "$container_section" | grep -qE "\b$t\b" \
        || fail "AC1: Container Beads section does not name type '$t'"
done
pass "AC1: Container Beads section names epic, milestone, feature"

# -----------------------------------------------------------------------------
# AC5 — I1/I2 prose updated: 'ancestor epic' → 'ancestor bead'.
# -----------------------------------------------------------------------------
# The previous prose contained "ancestor epic"; AC5 mandates "ancestor bead".
# Test: literal string "ancestor epic" must no longer appear in the file.
if grep -q 'ancestor epic' "$BEADS_MD"; then
    fail "AC5: beads.md still contains the phrase 'ancestor epic' (should be 'ancestor bead')"
fi
pass "AC5a: 'ancestor epic' phrase no longer present"

# And the replacement phrase must appear in the I1/I2 region.
grep -q 'ancestor bead' "$BEADS_MD" \
    || fail "AC5b: beads.md does not contain the replacement phrase 'ancestor bead'"
pass "AC5b: 'ancestor bead' phrase present"

echo "AC1 + AC5 beads.md red-phase tests passed."
