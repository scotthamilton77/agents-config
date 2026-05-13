#!/usr/bin/env bash
# Red-phase tests for AC7: whats-next SKILL.md must:
#   - render a 7-column table: P | Milestone | Feature | Parent Epic | Bead ID | Type | Title
#   - handle 4 sections: Needs your attention / Planning-ready /
#     Ready to brainstorm / Ready to implement
#   - default mode excludes the implementation section
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_MD="$SCRIPT_DIR/SKILL.md"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[ -f "$SKILL_MD" ] || fail "SKILL.md not found at $SKILL_MD"

# T1. 7-column table header present.
header_re='\| *P *\| *Milestone *\| *Feature *\| *Parent Epic *\| *Bead ID *\| *Type *\| *Title *\|'
grep -Eq "$header_re" "$SKILL_MD" \
    || fail "T1: SKILL.md missing 7-column table header (P | Milestone | Feature | Parent Epic | Bead ID | Type | Title)"
pass "T1: 7-column header present"

# T2. All four section names referenced.
for section in "Needs your attention" "Planning-ready" "Ready to brainstorm" "Ready to implement"; do
    grep -qF "$section" "$SKILL_MD" \
        || fail "T2: SKILL.md missing section heading: '$section'"
done
pass "T2: all four section names referenced"

# T3. Default-mode rule names planning-ready alongside human + brainstorm.
# The spec calls for: default mode renders human + planning-ready + brainstorm
# (no implementation). Probe the doc for a description that ties default to
# the planning-ready section explicitly.
grep -qiE 'default.*planning-ready|planning-ready.*default' "$SKILL_MD" \
    || fail "T3: SKILL.md does not document planning-ready as a default-mode section"
pass "T3: default mode documents planning-ready inclusion"

echo "All whats-next SKILL.md red-phase tests reached."
