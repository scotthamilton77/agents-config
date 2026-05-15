#!/usr/bin/env bash
# PR #72 stress-test — GROUP D: narrowed feature-container logic.
#
# Validates the PR #72 narrowed Rule B contract: a feature is treated as
# a container only when it has ≥1 non-closed children that are NOT
# formula-gate children (i.e. labels exclude `merge-gate` AND `human`).
# Per the Filter Matrix in collect.py: container features route to
# planning; non-container features route to implementation.
#
# Each test creates a sacrificial feature with a specific child profile,
# then runs TWO probes:
#   (a) Routing probe: a small Python harness imports collect.py and
#       evaluates is_container() against the constructed child profile
#       (faithful to collect.py's filter logic — same code path that
#       drives planning vs implementation routing).
#   (b) Gate decision probe: invoke bd-finalize-container-gate.sh with
#       the same fixture; assert decision token matches expected routing.
#
# Coverage:
#   D1. Feature F3 with 1 plain-labeled child → handled + planning routing
#   D2. Feature F4 with 1 merge-gate-labeled child → not-container + implementation routing
#   D3. Feature F5 with 1 human-labeled child → not-container + implementation routing
#   D4. Feature F6 with mixed children {1 plain, 1 merge-gate, 1 human} →
#       handled + planning routing
#   D5. Outcome alignment: 'handled' ↔ planning; 'not-container' ↔ implementation
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
COLLECT_PY="$REPO_ROOT/src/user/.agents/skills/whats-next/collect.py"
[ -f "$HELPER" ]     || { echo "FAIL: gate helper not found at $HELPER" >&2; exit 1; }
[ -f "$COLLECT_PY" ] || { echo "FAIL: collect.py not found at $COLLECT_PY" >&2; exit 1; }

command -v bd      >/dev/null 2>&1 || { echo "FAIL: bd CLI not on PATH" >&2; exit 1; }
command -v jq      >/dev/null 2>&1 || { echo "FAIL: jq required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 required" >&2; exit 1; }

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

# Create a child under $1 with labels $2 (space-separated).
make_child() {
    local parent="$1" title="$2"; shift 2
    local labels="$*"
    local id
    id=$(bd create --parent "$parent" --title "$title" --type task --priority 4 --json \
        | jq -r 'if type=="array" then .[0].id else .id end // empty')
    [ -z "$id" ] && fail "make_child: failed to create child under $parent"
    bd label add "$id" stress-test-fixture >/dev/null 2>&1
    for L in $labels; do
        bd label add "$id" "$L" >/dev/null 2>&1
    done
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

# Routing probe: invoke collect.py's is_container with the constructed
# active_child_count map derived from live bd children of $feature_id.
# Echoes 'planning' if classified as container, 'implementation' otherwise.
classify_routing() {
    local feature_id="$1"
    COLLECT_PY="$COLLECT_PY" FEATURE_ID="$feature_id" python3 - <<'PY'
import importlib.util, json, os, subprocess, sys
spec = importlib.util.spec_from_file_location("collect_mod", os.environ["COLLECT_PY"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
fid = os.environ["FEATURE_ID"]
# Build active_child_count using the same exclusion logic as collect.py main:
# merge-gate and human children are filtered out.
proc = subprocess.run(
    ["bd", "list", "--parent", fid, "--status", "open,in_progress",
     "--limit", "0", "--json"],
    capture_output=True, text=True, timeout=30,
)
if proc.returncode != 0:
    print(f"ERR: bd list failed: {proc.stderr}", file=sys.stderr)
    sys.exit(2)
if proc.stdout.strip():
    try:
        children = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"ERR: bd list returned invalid JSON: {e}\nstdout: {proc.stdout[:500]}", file=sys.stderr)
        sys.exit(2)
else:
    children = []
count = 0
for c in children:
    labels = c.get("labels", []) or []
    if "merge-gate" in labels or ("human" in labels and "hep-pause" not in labels):
        continue
    count += 1
mod.active_child_count = {fid: count}
is_container = mod.is_container(fid, "feature")
print("planning" if is_container else "implementation")
PY
}

# Track expected decision↔routing pairs for D5 final assertion.
declare -a EXPECTATIONS=()

# =============================================================================
# D1: feature F3 with 1 plain-labeled child → handled + planning routing.
# =============================================================================
F3=$(make_bead feature "stress-test F3 feature + plain child")
make_child "$F3" "F3 plain child" >/dev/null

ROUTING=$(classify_routing "$F3")
[ "$ROUTING" = "planning" ] \
    || fail "D1: collect.py routing for F3 expected 'planning', got '$ROUTING'"

MOL_F3=$(make_wisp "$F3" "stress-d1")
DECISION=$(run_gate "$F3" "$MOL_F3")
[ "$DECISION" = "handled" ] \
    || fail "D1: gate decision for F3 expected 'handled', got '$DECISION'"
EXPECTATIONS+=("D1:handled:planning:$DECISION:$ROUTING")
pass "D1: feature + plain child → gate=handled, routing=planning"

# =============================================================================
# D2: feature F4 with 1 merge-gate-labeled child → not-container +
# implementation routing.
# =============================================================================
F4=$(make_bead feature "stress-test F4 feature + merge-gate child")
make_child "$F4" "F4 merge-gate child" merge-gate >/dev/null

ROUTING=$(classify_routing "$F4")
[ "$ROUTING" = "implementation" ] \
    || fail "D2: collect.py routing for F4 expected 'implementation', got '$ROUTING'"

MOL_F4=$(make_wisp "$F4" "stress-d2")
DECISION=$(run_gate "$F4" "$MOL_F4")
[ "$DECISION" = "not-container" ] \
    || fail "D2: gate decision for F4 expected 'not-container', got '$DECISION'"
bd mol burn "$MOL_F4" --force >/dev/null 2>&1 || true
EXPECTATIONS+=("D2:not-container:implementation:$DECISION:$ROUTING")
pass "D2: feature + merge-gate child → gate=not-container, routing=implementation"

# =============================================================================
# D3: feature F5 with 1 human-labeled child → not-container + implementation.
# =============================================================================
F5=$(make_bead feature "stress-test F5 feature + human child")
make_child "$F5" "F5 human child" human >/dev/null

ROUTING=$(classify_routing "$F5")
[ "$ROUTING" = "implementation" ] \
    || fail "D3: collect.py routing for F5 expected 'implementation', got '$ROUTING'"

MOL_F5=$(make_wisp "$F5" "stress-d3")
DECISION=$(run_gate "$F5" "$MOL_F5")
[ "$DECISION" = "not-container" ] \
    || fail "D3: gate decision for F5 expected 'not-container', got '$DECISION'"
bd mol burn "$MOL_F5" --force >/dev/null 2>&1 || true
EXPECTATIONS+=("D3:not-container:implementation:$DECISION:$ROUTING")
pass "D3: feature + human child → gate=not-container, routing=implementation"

# =============================================================================
# D4: feature F6 with mixed children {1 plain, 1 merge-gate, 1 human} →
# handled + planning routing (plain child triggers container status; the
# formula-gate children are filtered out, but the plain one is not).
# =============================================================================
F6=$(make_bead feature "stress-test F6 feature + mixed children")
make_child "$F6" "F6 plain child"       >/dev/null
make_child "$F6" "F6 merge-gate child" merge-gate >/dev/null
make_child "$F6" "F6 human child"      human      >/dev/null

ROUTING=$(classify_routing "$F6")
[ "$ROUTING" = "planning" ] \
    || fail "D4: collect.py routing for F6 expected 'planning', got '$ROUTING'"

MOL_F6=$(make_wisp "$F6" "stress-d4")
DECISION=$(run_gate "$F6" "$MOL_F6")
[ "$DECISION" = "handled" ] \
    || fail "D4: gate decision for F6 expected 'handled', got '$DECISION'"
EXPECTATIONS+=("D4:handled:planning:$DECISION:$ROUTING")
pass "D4: feature + mixed children (1 plain + 1 merge-gate + 1 human) → gate=handled, routing=planning"

# =============================================================================
# D5: outcome alignment — 'handled' ↔ planning; 'not-container' ↔ implementation.
# =============================================================================
for entry in "${EXPECTATIONS[@]}"; do
    IFS=: read -r case_id expected_decision expected_routing actual_decision actual_routing <<< "$entry"
    if [ "$expected_decision" = "handled" ] && [ "$actual_routing" != "planning" ]; then
        fail "D5: $case_id — 'handled' decision should align with 'planning' routing; got routing='$actual_routing'"
    fi
    if [ "$expected_decision" = "not-container" ] && [ "$actual_routing" != "implementation" ]; then
        fail "D5: $case_id — 'not-container' decision should align with 'implementation' routing; got routing='$actual_routing'"
    fi
done
pass "D5: outcome alignment — handled↔planning and not-container↔implementation"

echo "GROUP D: narrowed feature-container logic passed."
