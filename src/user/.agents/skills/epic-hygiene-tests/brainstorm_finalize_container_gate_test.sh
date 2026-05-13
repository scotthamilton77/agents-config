#!/usr/bin/env bash
# Red-phase test for AC3: brainstorm-bead.formula.toml finalize step must
# include a container-gate (Step 0) that prevents impl-ready stamping on
# milestone / epic / feature-with-children.
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/plugins/beads" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/plugins/beads" ] \
    || fail "could not locate repo root containing src/plugins/beads"

FORMULA="$REPO_ROOT/src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml"
[ -f "$FORMULA" ] || fail "brainstorm-bead.formula.toml not found at $FORMULA"

# Extract the finalize step's description block. The finalize step's id is
# 'finalize' (see formula lines 219-222). We capture its description body.
finalize_body=$(awk '
    /^id[[:space:]]*=[[:space:]]*"finalize"/{f=1; next}
    f && /^\[\[steps\]\]/{f=0}
    f { print }
' "$FORMULA")

[ -n "$finalize_body" ] || fail "finalize step body not found in formula"

# AC3 requires a Step 0 container gate that prevents impl-ready stamping on
# milestone / epic / feature-with-children. Probe for:
#   (a) a "Step 0" container-gate label somewhere in the finalize body
#   (b) references to all three container conditions: milestone, epic,
#       feature-with-children
#   (c) the gate must reference NOT stamping implementation-ready (or
#       equivalent: e.g., "block", "halt", "refuse", "skip" the impl-ready
#       label on containers)

# Probe (a): explicit container-gate / Step 0 marker.
echo "$finalize_body" | grep -qiE 'container[- ]gate|step[[:space:]]*0[^0-9]' \
    || fail "AC3a: finalize body lacks a 'Step 0' or 'container gate' marker"
pass "AC3a: finalize body contains Step 0 / container-gate marker"

# Probe (b): all three container categories named.
for cond in milestone epic 'feature-with-children'; do
    echo "$finalize_body" | grep -qE "$cond" \
        || fail "AC3b: finalize body container gate does not mention '$cond'"
done
pass "AC3b: finalize body mentions milestone, epic, feature-with-children"

# Probe (c): gate references implementation-ready stamping suppression.
# Look for "implementation-ready" near a negation / gate verb.
echo "$finalize_body" | grep -qE 'implementation-ready' \
    || fail "AC3c: finalize body container gate does not reference implementation-ready"
pass "AC3c: container gate mentions implementation-ready"

echo "AC3 container-gate red-phase test passed."
