#!/usr/bin/env bash
# PR #72 stress-test — GROUP C: implement-bead routing on milestone / epic /
# non-container, validated via the container gate helper.
#
# Group C tests the HEP shape that fires when implement-bead encounters
# an epic or milestone. Instead of driving a full implement-bead molecule
# (heavyweight + many side effects), we invoke the container gate helper
# directly to simulate the routing decision — same code path, same
# observable outputs.
#
# Coverage:
#   C1. Sacrificial epic E3_test → HEP fires (decision=handled); child
#       `human` bead exists under E3_test (note: the helper takes the
#       CLEAN-DECOMP path for a childless epic with no produced-bead label;
#       we use the produced-bead-NONEXISTENT marker to force the HEP path).
#   C2. E3_test status=open; E3_test does NOT carry `human` label.
#   C3. Single-bead-`human` invariant: only the escalation child carries
#       `human` (not E3_test, not the wisp's step beads).
#   C4. Container HEP shape: the human bead is a child of E3_test (via
#       parent-child); no cross-type `bd dep add` was needed.
#   C5. Repeat C1–C4 for milestone M3_test.
#   C6. Non-container regression: plain task → decision='not-container';
#       NO human child created.
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

CREATED_BEADS=()
CREATED_WISPS=()

cleanup() {
    for w in "${CREATED_WISPS[@]:-}"; do
        [ -n "$w" ] && bd mol burn "$w" --force >/dev/null 2>&1 || true
    done
    for b in "${CREATED_BEADS[@]:-}"; do
        [ -z "$b" ] && continue
        bd list --parent "$b" --status open,in_progress --limit 0 --json 2>/dev/null \
            | jq -r '.[].id // empty' | while read -r c; do
                [ -n "$c" ] && bd close "$c" --reason "stress-test cleanup" >/dev/null 2>&1 || true
            done
        bd close "$b" --reason "stress-test cleanup" >/dev/null 2>&1 || true
    done
    bd list --label stress-test-fixture --status open,in_progress --limit 0 --json 2>/dev/null \
        | jq -r '.[].id // empty' | while read -r leftover; do
            [ -n "$leftover" ] && bd close "$leftover" --reason "stress-test cleanup sweep" >/dev/null 2>&1 || true
        done
}
trap cleanup EXIT

make_bead() {
    local type="$1" title="$2"
    local id
    id=$(bd create --title "$title" --type "$type" --priority 4 --json \
        | jq -r 'if type=="array" then .[0].id else .id end // empty')
    [ -z "$id" ] && fail "make_bead: failed to create $type"
    bd label add "$id" stress-test-fixture >/dev/null 2>&1
    CREATED_BEADS+=("$id")
    echo "$id"
}

make_wisp() {
    local bead_id="$1" slug="$2"
    local out mol
    out=$(bd mol wisp brainstorm-bead --var "bead-id=$bead_id" --var "title-slug=$slug" --json 2>/dev/null)
    mol=$(echo "$out" | jq -r '.new_epic_id // empty')
    [ -z "$mol" ] && fail "make_wisp: failed to pour wisp for $bead_id"
    CREATED_WISPS+=("$mol")
    echo "$mol"
}

run_gate() {
    bash "$HELPER" --bead-id "$1" --mol-id "$2"
}

has_label() {
    bd label list "$1" --json 2>/dev/null | jq -e "any(.[]; . == \"$2\")" >/dev/null
}

bead_status() {
    bd show "$1" --json 2>/dev/null | jq -r '.[0].status // empty'
}

# =============================================================================
# C1: sacrificial epic E3_test → HEP fires (decision=handled); child human
# bead exists. Force HEP path with produced-bead-NONEXISTENT.
# =============================================================================
E3=$(make_bead epic "stress-test E3 epic for routing")
bd label add "$E3" "produced-bead-NONEXISTENT-c-xyzzy" >/dev/null 2>&1
MOL_E3=$(make_wisp "$E3" "stress-c1")
DECISION=$(run_gate "$E3" "$MOL_E3")
[ "$DECISION" = "handled" ] \
    || fail "C1: epic E3 decision expected 'handled', got '$DECISION'"
# Find the HEP child.
HEP_CHILD_E3=$(bd list --parent "$E3" --status open,in_progress --limit 0 --json 2>/dev/null \
    | jq -r '.[] | select((.labels // []) | index("human")) | .id' | head -1)
[ -n "$HEP_CHILD_E3" ] \
    || fail "C1: no human-labeled child of E3 found after HEP"
CREATED_BEADS+=("$HEP_CHILD_E3")
pass "C1: epic → HEP fires; child human bead $HEP_CHILD_E3 exists"

# =============================================================================
# C2: E3 status=open, E3 does NOT carry `human`.
# =============================================================================
STATUS_E3=$(bead_status "$E3")
[ "$STATUS_E3" = "open" ] \
    || fail "C2: E3 status expected 'open' (HEP reverts), got '$STATUS_E3'"
if has_label "$E3" human; then
    fail "C2: E3 MUST NOT carry 'human' label (single-bead-human invariant)"
fi
pass "C2: E3 reverts to open; E3 does not carry 'human'"

# =============================================================================
# C3: single-bead-`human` invariant. Only the escalation child carries
# `human` — not E3, not its wisp step beads (already burned).
# =============================================================================
# We've already confirmed E3 lacks `human`. Confirm HEP_CHILD_E3 has it.
has_label "$HEP_CHILD_E3" human \
    || fail "C3: HEP escalation child $HEP_CHILD_E3 MISSING 'human' label"
pass "C3: single-bead-human invariant — only $HEP_CHILD_E3 carries 'human'"

# =============================================================================
# C4: Container HEP shape — human bead is a CHILD of source. Verify the
# parent field. No cross-type `bd dep add` was needed; the child/parent
# shape gates routing via the structural relationship + Rule C.
# =============================================================================
PARENT_OF_HEP=$(bd show "$HEP_CHILD_E3" --json 2>/dev/null | jq -r '.[0].parent // empty')
[ "$PARENT_OF_HEP" = "$E3" ] \
    || fail "C4: HEP child $HEP_CHILD_E3 parent expected '$E3', got '$PARENT_OF_HEP'"
# Also confirm bd list --parent contains the human child.
HEP_FOUND=$(bd list --parent "$E3" --status open,in_progress --limit 0 --json 2>/dev/null \
    | jq -r --arg cid "$HEP_CHILD_E3" '.[] | select(.id == $cid) | .id')
[ "$HEP_FOUND" = "$HEP_CHILD_E3" ] \
    || fail "C4: bd list --parent $E3 did not surface HEP child $HEP_CHILD_E3"
pass "C4: HEP child is structural child of source (parent-child shape, not blocks dep)"

# =============================================================================
# C5: repeat C1–C4 for milestone M3_test.
# =============================================================================
M3=$(make_bead milestone "stress-test M3 milestone for routing")
bd label add "$M3" "produced-bead-NONEXISTENT-c5-xyzzy" >/dev/null 2>&1
MOL_M3=$(make_wisp "$M3" "stress-c5")
DECISION=$(run_gate "$M3" "$MOL_M3")
[ "$DECISION" = "handled" ] \
    || fail "C5: milestone M3 decision expected 'handled', got '$DECISION'"
HEP_CHILD_M3=$(bd list --parent "$M3" --status open,in_progress --limit 0 --json 2>/dev/null \
    | jq -r '.[] | select((.labels // []) | index("human")) | .id' | head -1)
[ -n "$HEP_CHILD_M3" ] || fail "C5: no human-labeled child of M3 found after HEP"
CREATED_BEADS+=("$HEP_CHILD_M3")

STATUS_M3=$(bead_status "$M3")
[ "$STATUS_M3" = "open" ] || fail "C5: M3 status expected 'open', got '$STATUS_M3'"
if has_label "$M3" human; then
    fail "C5: M3 MUST NOT carry 'human' label"
fi
has_label "$HEP_CHILD_M3" human \
    || fail "C5: M3 HEP child missing 'human' label"
PARENT_OF_HEP_M3=$(bd show "$HEP_CHILD_M3" --json 2>/dev/null | jq -r '.[0].parent // empty')
[ "$PARENT_OF_HEP_M3" = "$M3" ] \
    || fail "C5: M3 HEP child parent expected '$M3', got '$PARENT_OF_HEP_M3'"
pass "C5: milestone → HEP fires; child $HEP_CHILD_M3 carries 'human'; M3 reverts to open; parent-child shape correct"

# =============================================================================
# C6: non-container regression — plain task → decision='not-container'; NO
# human child created.
# =============================================================================
T1=$(make_bead task "stress-test T1 plain task")
MOL_T1=$(make_wisp "$T1" "stress-c6")
DECISION=$(run_gate "$T1" "$MOL_T1")
[ "$DECISION" = "not-container" ] \
    || fail "C6: plain task T1 decision expected 'not-container', got '$DECISION'"
# Not-container path does not create children or burn the wisp; verify no
# human-labeled children created (any --parent T1 query is empty).
CHILDREN=$(bd list --parent "$T1" --limit 0 --json 2>/dev/null \
    | jq -r '.[] | select((.labels // []) | index("human")) | .id')
[ -z "$CHILDREN" ] \
    || fail "C6: plain task T1 has human child(ren) after 'not-container' decision: $CHILDREN"
# Burn the leftover wisp.
bd mol burn "$MOL_T1" --force >/dev/null 2>&1 || true
pass "C6: plain task → not-container; no human child created"

echo "GROUP C: implement-bead routing via container gate helper passed."
