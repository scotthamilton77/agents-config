#!/usr/bin/env bash
# Red-phase test for AC "brainstorm-bead finalize Step 0 container gate":
# brainstorm-bead.formula.toml finalize step must include a container-gate
# (Step 0) that prevents impl-ready stamping on milestone / epic /
# feature-with-children, BEFORE any other finalize work runs.
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
HELPER="$REPO_ROOT/src/plugins/beads/.beads/scripts/bd-finalize-container-gate.sh"
[ -f "$FORMULA" ] || fail "brainstorm-bead.formula.toml not found at $FORMULA"
[ -f "$HELPER" ]  || fail "bd-finalize-container-gate.sh helper not found at $HELPER"

# Extract the finalize step body and write to a tmp file (also captures line
# numbers within the finalize body for ordering checks).
TMP_FIN=$(mktemp)
trap 'rm -f "$TMP_FIN"' EXIT

awk '
    /^id[[:space:]]*=[[:space:]]*"finalize"/{f=1; print; next}
    f && /^\[\[steps\]\]/{f=0}
    f { print }
' "$FORMULA" > "$TMP_FIN"

[ -s "$TMP_FIN" ] || fail "finalize step body not found in formula"

# ---------------------------------------------------------------------------
# gate-marker: finalize body carries an explicit Step 0 / container-gate marker.
# ---------------------------------------------------------------------------
grep -qiE 'container[- ]gate|step[[:space:]]*0[^0-9]' "$TMP_FIN" \
    || fail "gate-marker: finalize body lacks a 'Step 0' or 'container gate' marker"
pass "gate-marker: finalize body contains Step 0 / container-gate marker"

# ---------------------------------------------------------------------------
# helper-invocation: finalize body invokes the extracted helper script.
# The bash logic lives in bd-finalize-container-gate.sh; the formula must
# call it from Step 0.
# ---------------------------------------------------------------------------
grep -qE 'bd-finalize-container-gate\.sh' "$TMP_FIN" \
    || fail "helper-invocation: finalize body does not invoke bd-finalize-container-gate.sh"
pass "helper-invocation: finalize body invokes bd-finalize-container-gate.sh"

# ---------------------------------------------------------------------------
# milestone-epic-arm: gate handles milestone AND epic types (explicit type branches).
# Probe for a 'case' construct that branches on the X_TYPE / issue_type
# variable with milestone and epic arms. We accept the spec's literal shape
# (`milestone|epic)`) or any variant that names both types as case branches.
# Lives in the extracted helper after Step 0 bash extraction.
# ---------------------------------------------------------------------------
grep -qE 'milestone[[:space:]]*\|[[:space:]]*epic|epic[[:space:]]*\|[[:space:]]*milestone' "$HELPER" \
    || fail "milestone-epic-arm: helper script does not have a 'milestone|epic' (or 'epic|milestone') case branch"
pass "milestone-epic-arm: helper script has milestone|epic case arm"

# ---------------------------------------------------------------------------
# feature-branch + feature-child-probe: feature-with-children behavior —
# implementation MUST have a `feature)` case-arm and probe child count via
# `bd list --parent <X> --status open,in_progress`. Lives in the helper.
# ---------------------------------------------------------------------------
grep -qE '(^|[[:space:]])feature\)' "$HELPER" \
    || fail "feature-branch: helper script lacks a 'feature)' case branch"

python3 - "$HELPER" <<'PY' || fail "feature-child-probe: helper's feature branch does not probe active children via 'bd list --parent ... --status open,in_progress'"
import re, sys
body = open(sys.argv[1]).read()
# Find any bd list command and assert both flags appear together (order-free).
ok = False
for m in re.finditer(r'bd\s+list[^\n]{0,400}', body):
    seg = m.group(0)
    if '--parent' in seg and re.search(r'--status\s+open,in_progress', seg):
        ok = True
        break
if not ok:
    raise SystemExit("no 'bd list --parent ... --status open,in_progress' invocation found")
PY
pass "feature-child-probe: helper script probes active children via bd list --parent ... --status open,in_progress"

# ---------------------------------------------------------------------------
# impl-ready-suppression + epic-decomposed-stamp: the formula body
# documents implementation-ready suppression (Step 0 doc-block) AND the
# helper stamps the `epic-decomposed` audit-trail label on the clean
# decomposition path.
# ---------------------------------------------------------------------------
grep -qE 'implementation-ready' "$TMP_FIN" \
    || fail "impl-ready-suppression: finalize body does not reference 'implementation-ready'"
grep -qE 'epic-decomposed' "$HELPER" \
    || fail "epic-decomposed-stamp: helper script does not stamp 'epic-decomposed' audit-trail label"
pass "impl-ready-suppression + epic-decomposed-stamp: finalize body documents implementation-ready suppression; helper stamps epic-decomposed"

# ---------------------------------------------------------------------------
# gate-precedes-impl-ready: Step 0 container gate must appear BEFORE any
# `bd label add ... implementation-ready` stamping in the finalize body.
# Use line numbers within the finalize body.
# ---------------------------------------------------------------------------
gate_line=$(grep -niE 'container[- ]gate|step[[:space:]]*0[^0-9]' "$TMP_FIN" | head -1 | cut -d: -f1)
impl_label_line=$(grep -nE 'bd[[:space:]]+label[[:space:]]+add[^\n]*implementation-ready' "$TMP_FIN" | head -1 | cut -d: -f1)

[ -n "$gate_line" ] || fail "gate-precedes-impl-ready: could not locate gate marker line"
if [ -n "$impl_label_line" ]; then
    [ "$gate_line" -lt "$impl_label_line" ] \
        || fail "gate-precedes-impl-ready: container gate (line $gate_line) must appear BEFORE first 'bd label add ... implementation-ready' (line $impl_label_line)"
    pass "gate-precedes-impl-ready: container gate precedes implementation-ready stamping (gate@$gate_line, stamp@$impl_label_line)"
else
    # If there is no impl-ready stamping in finalize at all, the ordering
    # invariant is vacuously satisfied — but flag, because the leaf path
    # MUST stamp implementation-ready (per spec); absence is suspicious.
    pass "gate-precedes-impl-ready: no 'implementation-ready' stamp present in finalize body (vacuous ordering pass); review separately if unexpected"
fi

echo "All container-gate red-phase tests passed."
