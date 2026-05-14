#!/usr/bin/env bash
# PR #72 stress-test — GROUP B: container gate at brainstorm-bead finalize.
#
# Exercises the SHIPPED bd-finalize-container-gate.sh helper directly. For
# each test, we create a sacrificial seed bead (labeled `stress-test-fixture`)
# and pour a real wisp molecule (so the helper's `bd mol burn` succeeds);
# we then invoke the helper and check decision token + post-conditions.
#
# Coverage:
#   B1. epic with no children → decision='handled'
#   B2. After B1: epic ends closed + carries `epic-decomposed`, NOT
#       `implementation-ready` / `brainstormed` / `implementation-readied-session-*`.
#   B3. Same as B1+B2 for milestone type.
#   B4. Feature with 1 open plain-labeled child → decision='handled' +
#       carries `epic-decomposed`.
#   B5. Childless feature → decision='not-container' (NOT carries `epic-decomposed`).
#   B6. HEP path: epic with `produced-bead-NONEXISTENT-xyzzy` label →
#       decision='handled'; child human bead exists; source reverts to
#       open and does NOT carry `human` label.
#
# Cleanup: trap exits, closes all `stress-test-fixture` beads (open
# children + sources). Sacrificial wisps are burned by the helper or by
# the trap fallback.
set -u

fail() { echo "FAIL: $*" >&2; cleanup; exit 1; }
pass() { echo "PASS: $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/plugins/beads" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/plugins/beads" ] \
    || { echo "FAIL: could not locate repo root" >&2; exit 1; }

HELPER="$REPO_ROOT/src/plugins/beads/.beads/scripts/bd-finalize-container-gate.sh"
[ -f "$HELPER" ] \
    || { echo "FAIL: bd-finalize-container-gate.sh not found at $HELPER" >&2; exit 1; }

command -v bd  >/dev/null 2>&1 || { echo "FAIL: bd CLI not on PATH" >&2; exit 1; }
command -v jq  >/dev/null 2>&1 || { echo "FAIL: jq required" >&2; exit 1; }

# Track sacrificial beads and wisps so cleanup can sweep on exit.
CREATED_BEADS=()
CREATED_WISPS=()

cleanup() {
    # Burn any leftover wisps (helper normally burns them; HEP fallback paths
    # also burn). This sweep handles aborted runs.
    for w in "${CREATED_WISPS[@]:-}"; do
        [ -n "$w" ] && bd mol burn "$w" --force >/dev/null 2>&1 || true
    done
    # Close any beads still carrying the stress-test-fixture label, and
    # any child beads under them (HEP escalation children get auto-parent
    # IDs like agents-config-XXX.1 and must be closed explicitly because
    # they don't carry stress-test-fixture by inheritance).
    for b in "${CREATED_BEADS[@]:-}"; do
        [ -z "$b" ] && continue
        # Close children first (HEP escalations).
        bd list --parent "$b" --status open,in_progress --limit 0 --json 2>/dev/null \
            | jq -r '.[].id // empty' | while read -r c; do
                [ -n "$c" ] && bd close "$c" --reason "stress-test cleanup" >/dev/null 2>&1 || true
            done
        bd close "$b" --reason "stress-test cleanup" >/dev/null 2>&1 || true
    done
    # Final sanity sweep — anything still carrying stress-test-fixture.
    bd list --label stress-test-fixture --status open,in_progress --limit 0 --json 2>/dev/null \
        | jq -r '.[].id // empty' | while read -r leftover; do
            [ -n "$leftover" ] && bd close "$leftover" --reason "stress-test cleanup sweep" >/dev/null 2>&1 || true
        done
}
trap cleanup EXIT

# Helper to create a sacrificial bead.
make_bead() {
    local type="$1" title="$2"
    local id
    id=$(bd create --title "$title" --type "$type" --priority 4 --json \
        | jq -r 'if type=="array" then .[0].id else .id end // empty')
    [ -z "$id" ] && fail "make_bead: failed to create $type bead"
    bd label add "$id" stress-test-fixture >/dev/null 2>&1 || fail "label stress-test-fixture failed on $id"
    CREATED_BEADS+=("$id")
    echo "$id"
}

# Helper to pour a sacrificial wisp molecule and echo its mol-id.
make_wisp() {
    local bead_id="$1" slug="$2"
    local out mol
    out=$(bd mol wisp brainstorm-bead --var "bead-id=$bead_id" --var "title-slug=$slug" --json 2>/dev/null)
    mol=$(echo "$out" | jq -r '.new_epic_id // empty')
    [ -z "$mol" ] && fail "make_wisp: failed to pour wisp for $bead_id"
    CREATED_WISPS+=("$mol")
    echo "$mol"
}

# Helper to invoke gate and return decision token via stdout.
run_gate() {
    local bid="$1" mol="$2"
    bash "$HELPER" --bead-id "$bid" --mol-id "$mol"
}

# Helper: bead carries a label?
has_label() {
    local bead_id="$1" label="$2"
    bd label list "$bead_id" --json 2>/dev/null | jq -e "any(.[]; . == \"$label\")" >/dev/null
}

# Helper: bead status.
bead_status() {
    bd show "$1" --json 2>/dev/null | jq -r '.[0].status // empty'
}

# =============================================================================
# B1 + B2: epic, no children — decision=handled; closed + epic-decomposed.
# =============================================================================
E1=$(make_bead epic "stress-test E1 epic no children")
MOL1=$(make_wisp "$E1" "stress-e1")
DECISION=$(run_gate "$E1" "$MOL1")
[ "$DECISION" = "handled" ] \
    || fail "B1: epic E1 decision expected 'handled', got '$DECISION'"
pass "B1: childless epic → decision=handled"

# Post-conditions for B2:
STATUS=$(bead_status "$E1")
[ "$STATUS" = "closed" ] \
    || fail "B2: epic E1 status expected 'closed', got '$STATUS'"
has_label "$E1" epic-decomposed \
    || fail "B2: epic E1 does NOT carry 'epic-decomposed' label"
! has_label "$E1" implementation-ready \
    || fail "B2: epic E1 must NOT carry 'implementation-ready' label"
! has_label "$E1" brainstormed \
    || fail "B2: epic E1 must NOT carry 'brainstormed' label"
# Session marker check
session_markers=$(bd label list "$E1" --json 2>/dev/null \
    | jq -r '.[] | select(startswith("implementation-readied-session-"))' | head -1)
[ -z "$session_markers" ] \
    || fail "B2: epic E1 carries implementation-readied-session-* label: $session_markers"
pass "B2: epic E1 closed + epic-decomposed + no readiness labels"

# =============================================================================
# B3: milestone — same outcome.
# =============================================================================
M1=$(make_bead milestone "stress-test M1 milestone no children")
MOL2=$(make_wisp "$M1" "stress-m1")
DECISION=$(run_gate "$M1" "$MOL2")
[ "$DECISION" = "handled" ] \
    || fail "B3: milestone M1 decision expected 'handled', got '$DECISION'"
STATUS=$(bead_status "$M1")
[ "$STATUS" = "closed" ] \
    || fail "B3: milestone M1 status expected 'closed', got '$STATUS'"
has_label "$M1" epic-decomposed \
    || fail "B3: milestone M1 missing 'epic-decomposed' label"
pass "B3: childless milestone → handled + closed + epic-decomposed"

# =============================================================================
# B4: feature with 1 plain-labeled child — decision=handled + epic-decomposed.
# =============================================================================
F1=$(make_bead feature "stress-test F1 feature with child")
# Create child under F1 (plain task, no formula-gate labels).
C1=$(bd create --parent "$F1" --title "stress-test C1 child of F1" --type task --priority 4 --json \
    | jq -r 'if type=="array" then .[0].id else .id end // empty')
[ -z "$C1" ] && fail "B4: failed to create child C1 under F1"
bd label add "$C1" stress-test-fixture >/dev/null 2>&1
CREATED_BEADS+=("$C1")

MOL3=$(make_wisp "$F1" "stress-f1")
DECISION=$(run_gate "$F1" "$MOL3")
[ "$DECISION" = "handled" ] \
    || fail "B4: feature F1 with 1 plain child decision expected 'handled', got '$DECISION'"
has_label "$F1" epic-decomposed \
    || fail "B4: feature F1 missing 'epic-decomposed' label"
pass "B4: feature-with-children → handled + epic-decomposed"

# =============================================================================
# B5: childless feature — decision=not-container; NO epic-decomposed.
# =============================================================================
F2=$(make_bead feature "stress-test F2 childless feature")
MOL4=$(make_wisp "$F2" "stress-f2")
DECISION=$(run_gate "$F2" "$MOL4")
[ "$DECISION" = "not-container" ] \
    || fail "B5: childless feature F2 decision expected 'not-container', got '$DECISION'"
if has_label "$F2" epic-decomposed; then
    fail "B5: childless feature F2 MUST NOT carry 'epic-decomposed' (helper did not run decomposition)"
fi
pass "B5: childless feature → not-container; no epic-decomposed"

# F2's wisp is NOT burned by the not-container path; burn it explicitly so
# cleanup doesn't have to.
bd mol burn "$MOL4" --force >/dev/null 2>&1 || true

# =============================================================================
# B6: HEP path — epic with produced-bead-NONEXISTENT-xyzzy label.
# decision=handled; child human bead exists under source; source reverts
# to status=open; source does NOT carry `human` label.
# =============================================================================
E2=$(make_bead epic "stress-test E2 HEP epic")
bd label add "$E2" "produced-bead-NONEXISTENT-xyzzy" >/dev/null 2>&1
MOL5=$(make_wisp "$E2" "stress-hep")
DECISION=$(run_gate "$E2" "$MOL5")
[ "$DECISION" = "handled" ] \
    || fail "B6: HEP epic E2 decision expected 'handled', got '$DECISION'"
# Source must revert to open (HEP path).
STATUS=$(bead_status "$E2")
[ "$STATUS" = "open" ] \
    || fail "B6: HEP epic E2 status expected 'open' (HEP reverts), got '$STATUS'"
# Source must NOT carry `human` label (single-bead-human invariant).
if has_label "$E2" human; then
    fail "B6: HEP epic E2 MUST NOT carry 'human' label (single-bead-human invariant)"
fi
# Child human bead must exist under E2.
HEP_CHILD=$(bd list --parent "$E2" --status open,in_progress --limit 0 --json 2>/dev/null \
    | jq -r '.[] | select((.labels // []) | index("human")) | .id' | head -1)
[ -n "$HEP_CHILD" ] \
    || fail "B6: no human-labeled child of E2 found after HEP"
# Track child for cleanup.
CREATED_BEADS+=("$HEP_CHILD")
pass "B6: HEP epic → handled; child human bead $HEP_CHILD exists; source reverted to open; source has no 'human' label"

echo "GROUP B: container-gate brainstorm-finalize tests passed."
