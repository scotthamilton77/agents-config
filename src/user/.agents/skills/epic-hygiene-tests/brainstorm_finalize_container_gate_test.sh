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
[ -f "$FORMULA" ] || fail "brainstorm-bead.formula.toml not found at $FORMULA"

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
# AC5a: finalize body carries an explicit Step 0 / container-gate marker.
# ---------------------------------------------------------------------------
grep -qiE 'container[- ]gate|step[[:space:]]*0[^0-9]' "$TMP_FIN" \
    || fail "AC5a: finalize body lacks a 'Step 0' or 'container gate' marker"
pass "AC5a: finalize body contains Step 0 / container-gate marker"

# ---------------------------------------------------------------------------
# AC5b: gate handles milestone AND epic types (explicit type branches).
# Probe for a 'case' construct that branches on the X_TYPE / issue_type
# variable with milestone and epic arms. We accept the spec's literal shape
# (`milestone|epic)`) or any variant that names both types as case branches.
# ---------------------------------------------------------------------------
grep -qE 'milestone[[:space:]]*\|[[:space:]]*epic|epic[[:space:]]*\|[[:space:]]*milestone' "$TMP_FIN" \
    || fail "AC5b: finalize body container gate does not have a 'milestone|epic' (or 'epic|milestone') case branch"
pass "AC5b: finalize body has milestone|epic case arm"

# ---------------------------------------------------------------------------
# AC5c: feature-with-children behavior — implementation MUST probe child
# count via `bd list --parent <X> --status open,in_progress`. This replaces
# the literal-phrase "feature-with-children" string match (which would
# false-negative on a correct implementation that doesn't use that exact
# phrase). The spec's authoritative shape is the bd list invocation.
# Behaviour probe:
#   (i) a `feature)` case-arm exists in the gate
#   (ii) within (or near) it, `bd list --parent` is called with
#        `--status open,in_progress` to count children
# ---------------------------------------------------------------------------
grep -qE '(^|[[:space:]])feature\)' "$TMP_FIN" \
    || fail "AC5c-i: finalize body container gate lacks a 'feature)' case branch"

# bd list --parent ... --status open,in_progress (order of --parent and
# --status may vary; check both flags appear within 200 chars of each other).
python3 - "$TMP_FIN" <<'PY' || fail "AC5c-ii: container gate's feature branch does not probe active children via 'bd list --parent ... --status open,in_progress'"
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
pass "AC5c: feature branch probes active children via bd list --parent ... --status open,in_progress"

# ---------------------------------------------------------------------------
# AC5d: gate must reference implementation-ready (the label whose stamping
# is being suppressed) AND the container path must NOT stamp 'brainstormed'.
# We assert both:
#   (i)  'implementation-ready' is mentioned in the finalize body
#   (ii) on the container path the comment/text "NOT stamped" appears near
#        the implementation-ready / brainstormed mention OR the formula
#        explicitly stamps 'epic-decomposed' (the audit-trail-only label
#        per spec).
# ---------------------------------------------------------------------------
grep -qE 'implementation-ready' "$TMP_FIN" \
    || fail "AC5d-i: finalize body does not reference 'implementation-ready'"
grep -qE 'epic-decomposed' "$TMP_FIN" \
    || fail "AC5d-ii: finalize body container path does not stamp 'epic-decomposed' audit-trail label (spec AC5/AC2 of design)"
pass "AC5d: container path mentions implementation-ready suppression and stamps epic-decomposed"

# ---------------------------------------------------------------------------
# AC5e (MJ1): Step 0 container gate must appear BEFORE any
# `bd label add ... implementation-ready` stamping in the finalize body.
# Use line numbers within the finalize body.
# ---------------------------------------------------------------------------
gate_line=$(grep -niE 'container[- ]gate|step[[:space:]]*0[^0-9]' "$TMP_FIN" | head -1 | cut -d: -f1)
impl_label_line=$(grep -nE 'bd[[:space:]]+label[[:space:]]+add[^\n]*implementation-ready' "$TMP_FIN" | head -1 | cut -d: -f1)

[ -n "$gate_line" ] || fail "AC5e: could not locate gate marker line"
if [ -n "$impl_label_line" ]; then
    [ "$gate_line" -lt "$impl_label_line" ] \
        || fail "AC5e: container gate (line $gate_line) must appear BEFORE first 'bd label add ... implementation-ready' (line $impl_label_line)"
    pass "AC5e: container gate precedes implementation-ready stamping (gate@$gate_line, stamp@$impl_label_line)"
else
    # If there is no impl-ready stamping in finalize at all, the ordering
    # invariant is vacuously satisfied — but flag, because the leaf path
    # MUST stamp implementation-ready (per spec); absence is suspicious.
    pass "AC5e: no 'implementation-ready' stamp present in finalize body (vacuous ordering pass); review separately if unexpected"
fi

echo "AC5 container-gate red-phase test passed."
