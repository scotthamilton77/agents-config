#!/usr/bin/env bash
# Red-phase tests for AC "whats-next collect.py: container filter, planning-ready, typed ancestry, --mode flag".
# Covers:
#   T1. is_container(id, type): epic/milestone are containers regardless of
#       child count; feature is a container only when it has active children.
#   T2. is_brainstorm_candidate excludes BRAINSTORM_EXCLUDED_TYPES
#       (milestone, epic, feature, decision).
#   T3. --mode flag: all 5 values (all | brainstorm | implementation |
#       planning | human) are accepted, and an invalid choice is rejected.
#   T4. (REMOVED — was an impl-detail probe on hasattr(mod,'enrich')).
#       End-to-end JSON shape covered by T5/T6/T7.
#   T5. End-to-end typed-ancestor extraction:
#       With a known ancestry chain milestone→feature→epic→task in the bd shim,
#       the task's enriched record carries exact milestone_col / feature_col /
#       parent_epic_col / type values. planning_ready section surfaces the
#       childless container (the milestone in this fixture has no other
#       children except the chain, but the chain's feature/epic have active
#       descendants; assertion: planning_ready contains AT LEAST one of the
#       expected ancestors when shim simulates a childless container).
#   T6. Mode key matrix: run all 5 modes and assert the EXACT set of top-level
#       section keys emitted. Per spec §"Output schema": absent sections must
#       be ABSENT from JSON, not empty arrays.
#   T7. (folded into T6).
#   T8. Childless feature with implementation-ready is a leaf impl bead:
#       surfaces under --mode implementation; excluded from --mode planning.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT_PY="$SCRIPT_DIR/collect.py"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[ -f "$COLLECT_PY" ] || fail "collect.py not found at $COLLECT_PY"
command -v python3 >/dev/null 2>&1 || fail "python3 required"

# -----------------------------------------------------------------------------
# T1. is_container() — type and child-count semantics.
# -----------------------------------------------------------------------------
# is_container signature per spec Change 1: is_container(bead_id, bead_type).
# It reads an active_child_count dict at module scope (built in main); for the
# unit probe we install a controlled active_child_count.
python3 - "$COLLECT_PY" <<'PY' || fail "T1: is_container missing/incorrect"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, "is_container"), "is_container function not defined"
# Inject a deterministic active_child_count for the test. Implementations may
# either expose a module-level dict the function reads, or accept the dict as
# an arg. Probe both shapes.
import inspect
sig = inspect.signature(mod.is_container)
nparams = len(sig.parameters)
if nparams == 2:
    # Two-arg form: function reads module-level dict.
    if hasattr(mod, "active_child_count"):
        mod.active_child_count = {"feat-with-kids": 2}
    else:
        # Implementation may expose under different name; set anyway.
        setattr(mod, "active_child_count", {"feat-with-kids": 2})
    assert mod.is_container("anything", "epic") is True,      "epic must be container"
    assert mod.is_container("anything", "milestone") is True, "milestone must be container"
    assert mod.is_container("feat-with-kids", "feature") is True, \
        "feature WITH active children must be a container"
    assert mod.is_container("childless-feat", "feature") is False, \
        "feature WITHOUT active children must NOT be a container"
    for t in ("task", "bug", "chore", "spike", "story", "decision"):
        assert mod.is_container("x", t) is False, f"{t} must not be container"
elif nparams == 3:
    # Three-arg form: function takes child-count dict explicitly.
    cc = {"feat-with-kids": 2}
    assert mod.is_container("anything", "epic", cc) is True
    assert mod.is_container("anything", "milestone", cc) is True
    assert mod.is_container("feat-with-kids", "feature", cc) is True
    assert mod.is_container("childless-feat", "feature", cc) is False
else:
    raise AssertionError(f"is_container has unexpected arity {nparams}; expected 2 or 3")
PY
pass "T1: is_container() classifies types correctly"

# -----------------------------------------------------------------------------
# T2. is_brainstorm_candidate excludes container-design types.
# -----------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T2: is_brainstorm_candidate does not exclude container-design types"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
def mk(t):
    return {"id": "x-1", "issue_type": t, "labels": []}
for t in ("milestone", "epic", "feature", "decision"):
    res = mod.is_brainstorm_candidate(mk(t))
    assert res is False, f"is_brainstorm_candidate must reject type={t} (got {res!r})"
for t in ("task", "bug", "chore", "story", "spike"):
    res = mod.is_brainstorm_candidate(mk(t))
    assert res is True, f"is_brainstorm_candidate must accept type={t} (got {res!r})"
PY
pass "T2: is_brainstorm_candidate excludes container-design types"

# -----------------------------------------------------------------------------
# T3. --mode flag: argparse accepts all 5 values; rejects bogus.
# -----------------------------------------------------------------------------
# A throwaway empty bd shim suffices: collect.py exits 1 on "no data" which we
# tolerate; we only fail on argparse rejection (exit 2 / "invalid choice" /
# "unrecognized arguments").
TMP_T3=$(mktemp -d)
trap 'rm -rf "$TMP_T3"' EXIT
cat > "$TMP_T3/bd" <<'SHIM'
#!/usr/bin/env bash
echo '[]'
SHIM
chmod +x "$TMP_T3/bd"

probe_mode() {
    local mode="$1"
    local out ec
    if [ "$mode" = "_default_" ]; then
        out=$(PATH="$TMP_T3:$PATH" python3 "$COLLECT_PY" --limit 0 2>&1)
    else
        out=$(PATH="$TMP_T3:$PATH" python3 "$COLLECT_PY" --mode "$mode" --limit 0 2>&1)
    fi
    ec=$?
    # argparse rejection signals: exit 2 + 'invalid choice' OR 'unrecognized arguments'
    if [ "$ec" -eq 2 ] && echo "$out" | grep -qE 'invalid choice|unrecognized arguments'; then
        fail "T3: --mode $mode rejected by argparse (out: $out)"
    fi
    # Allow exit 0 (success) or 1 (no data from shim). 2 with non-argparse text
    # is also acceptable for "_default_" probe.
    return 0
}

for m in _default_ all brainstorm implementation planning human; do
    probe_mode "$m"
done
pass "T3a: --mode flag accepts all, brainstorm, implementation, planning, human"

# Invalid mode must be rejected.
bogus_out=$(PATH="$TMP_T3:$PATH" python3 "$COLLECT_PY" --mode bogus --limit 0 2>&1)
bogus_ec=$?
[ "$bogus_ec" -ne 0 ] \
    || fail "T3b: --mode bogus must exit non-zero (got 0; out: $bogus_out)"
echo "$bogus_out" | grep -qE 'invalid choice|unrecognized arguments' \
    || fail "T3b: --mode bogus must surface argparse rejection (out: $bogus_out)"
pass "T3b: --mode flag rejects invalid choices"

# -----------------------------------------------------------------------------
# T5. Typed-ancestor extraction with a known ancestry chain in the shim.
# Chain: proj-ms1 (milestone) → proj-feat1 (feature) → proj-epic1 (epic) → proj-task1 (task).
# We assert exact column values on the displayed task.
# -----------------------------------------------------------------------------
TMP_T5=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5"' EXIT

cat > "$TMP_T5/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    echo '[]' ;;
  "list --status open,in_progress --limit 0 --json")
    # active_child_count source: each non-closed bead with its parent. Chain:
    # task has parent epic; epic has parent feature; feature has parent
    # milestone. Container at top has no other children (childless).
    cat <<'JSON'
[
  {"id":"proj-task1","issue_type":"task","status":"open","priority":1,"title":"Do a thing","labels":[],"parent":"proj-epic1"},
  {"id":"proj-epic1","issue_type":"epic","status":"open","priority":1,"title":"Some epic","labels":[],"parent":"proj-feat1"},
  {"id":"proj-feat1","issue_type":"feature","status":"open","priority":1,"title":"Some feature","labels":[],"parent":"proj-ms1"},
  {"id":"proj-ms1","issue_type":"milestone","status":"open","priority":1,"title":"M1","labels":[]}
]
JSON
    ;;
  "ready --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-task1","issue_type":"task","status":"open","priority":1,"title":"Do a thing","labels":[],"parent":"proj-epic1","created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json")
    # Childless container surfaces in planning-ready.
    echo '[{"id":"proj-empty-ms","issue_type":"milestone","status":"open","priority":1,"title":"Empty MS","labels":[]}]' ;;
  "list --type epic --ready --limit 0 --json")
    echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    echo '[]' ;;
  "show proj-feat1 --json")
    echo '[{"id":"proj-feat1","issue_type":"feature","priority":1,"title":"Some feature","labels":[],"parent":"proj-ms1"}]' ;;
  "show proj-ms1 --json")
    echo '[{"id":"proj-ms1","issue_type":"milestone","priority":1,"title":"M1","labels":[]}]' ;;
  "show proj-epic1 --json")
    echo '[{"id":"proj-epic1","issue_type":"epic","priority":1,"title":"Some epic","labels":[],"parent":"proj-feat1"}]' ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T5/bd"

OUT_T5_FILE="$TMP_T5/out.json"
PATH="$TMP_T5:$PATH" python3 "$COLLECT_PY" >"$OUT_T5_FILE" 2>"$TMP_T5/err"
ec=$?
[ "$ec" -eq 0 ] || fail "T5: collect.py exited $ec with shim (stderr: $(cat "$TMP_T5/err"))"

OUT_T5_FILE="$OUT_T5_FILE" python3 - <<'PY' || fail "T5: typed-ancestor extraction wrong or planning_ready missing expected entries"
import json, os, sys
out = json.load(open(os.environ["OUT_T5_FILE"]))
# `all` mode (the default when no flag): must contain all four section keys.
assert "human" in out, "all mode must include human"
assert "planning_ready" in out, "all mode must include planning_ready"
assert "brainstorm" in out, "all mode must include brainstorm"
assert "implementation" in out, \
    "all mode must include 'implementation' key (per spec: 4 sections)"

# Find proj-task1 in the brainstorm section (no impl-ready label).
brainstorm = out.get("brainstorm", [])
task = next((b for b in brainstorm if b.get("id") == "proj-task1"), None)
assert task is not None, f"proj-task1 missing from brainstorm; got: {[b.get('id') for b in brainstorm]}"

# Exact typed-ancestor column values (short_id form, prefix-stripped).
# Project prefix detection collapses to 'proj' (common across all ids).
assert task["milestone_col"] == "ms1", \
    f"milestone_col expected 'ms1', got {task.get('milestone_col')!r}"
assert task["feature_col"] == "feat1", \
    f"feature_col expected 'feat1', got {task.get('feature_col')!r}"
assert task["parent_epic_col"] == "epic1", \
    f"parent_epic_col expected 'epic1', got {task.get('parent_epic_col')!r}"
assert task["type"] == "task", \
    f"type expected 'task', got {task.get('type')!r}"

# Planning-ready surfaces the childless container (proj-empty-ms).
pr = out.get("planning_ready", [])
pr_ids = [b.get("id") for b in pr]
assert "proj-empty-ms" in pr_ids, \
    f"planning_ready must include childless container proj-empty-ms; got: {pr_ids}"
PY
pass "T5: typed-ancestor extraction emits exact milestone/feature/parent_epic/type; planning_ready surfaces childless container"

# -----------------------------------------------------------------------------
# T6. Mode key matrix: exact top-level section-key sets per mode.
# Per spec §"--mode contract": absent sections are ABSENT from JSON,
# not empty arrays. Top-level 'mode' field carries the mode value.
# `in_flight` is mode-independent (like `totals`/`mode`/`project_prefix`/
# `limit`) and is ALWAYS present regardless of mode — asserted below.
# -----------------------------------------------------------------------------
TMP_T6=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6"' EXIT

cat > "$TMP_T6/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    echo '[{"id":"proj-h1","issue_type":"task","status":"open","priority":1,"title":"H","labels":["human"]}]' ;;
  "list --status open,in_progress --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-impl1","issue_type":"task","status":"open","priority":1,"title":"Impl","labels":["implementation-ready"]},
  {"id":"proj-brain1","issue_type":"task","status":"open","priority":1,"title":"Brainstormable","labels":[]},
  {"id":"proj-empty-ep","issue_type":"epic","status":"open","priority":1,"title":"Empty epic","labels":[]},
  {"id":"proj-h1","issue_type":"task","status":"open","priority":1,"title":"H","labels":["human"]}
]
JSON
    ;;
  "ready --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-impl1","issue_type":"task","status":"open","priority":1,"title":"Impl","labels":["implementation-ready"],"created_at":"2026-05-01"},
  {"id":"proj-brain1","issue_type":"task","status":"open","priority":1,"title":"Brainstormable","labels":[],"created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json")
    echo '[{"id":"proj-empty-ep","issue_type":"epic","status":"open","priority":1,"title":"Empty epic","labels":[]}]' ;;
  "list --type feature --ready --limit 0 --json") echo '[]' ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T6/bd"

# Per-mode expected SECTION key sets (the keys spec §"--mode contract" lists).
# Section keys: human, planning_ready, brainstorm, implementation.
# (Top-level meta keys like 'mode', 'totals', 'limit', 'project_prefix' may
# also appear; we assert on the SECTION-key subset only.)
expect_all='human planning_ready brainstorm implementation'
expect_brainstorm='brainstorm'
expect_impl='implementation'
expect_planning='planning_ready'
expect_human='human'

assert_mode_keys() {
    local mode_arg="$1" expect_set="$2" mode_value="$3"
    local out ec
    if [ "$mode_arg" = "_default_" ]; then
        out=$(PATH="$TMP_T6:$PATH" python3 "$COLLECT_PY" 2>"$TMP_T6/err")
    else
        out=$(PATH="$TMP_T6:$PATH" python3 "$COLLECT_PY" --mode "$mode_arg" 2>"$TMP_T6/err")
    fi
    ec=$?
    [ "$ec" -eq 0 ] || fail "T6: collect.py --mode $mode_arg exited $ec (stderr: $(cat "$TMP_T6/err"))"
    local outfile="$TMP_T6/out.${mode_arg}.json"
    echo "$out" > "$outfile"
    OUTFILE="$outfile" EXPECT="$expect_set" MODE_VALUE="$mode_value" \
    python3 - <<'PY' || fail "T6: mode '$mode_arg' key set wrong"
import json, os, sys
out = json.load(open(os.environ["OUTFILE"]))
section_keys = {"human", "planning_ready", "brainstorm", "implementation"}
expect = set(os.environ["EXPECT"].split())
present = section_keys & set(out.keys())
if present != expect:
    raise SystemExit(f"section keys mismatch: expected {expect}, got {present} "
                     f"(all keys: {sorted(out.keys())})")
# Top-level 'mode' field (per spec --mode contract).
mode_val = os.environ["MODE_VALUE"]
if out.get("mode") != mode_val:
    raise SystemExit(f"top-level 'mode' field expected {mode_val!r}, got {out.get('mode')!r}")
# `in_flight` is mode-independent: it must appear in EVERY mode's output
# (the new always-present contract). This shim has no in_progress beads,
# so the value is an empty list.
if "in_flight" not in out:
    raise SystemExit(f"'in_flight' must be present in every mode; keys: {sorted(out.keys())}")
if out.get("totals", {}).get("in_flight") != len(out["in_flight"]):
    raise SystemExit(f"totals.in_flight must match len(in_flight); "
                     f"totals={out.get('totals')}, in_flight={out['in_flight']}")
PY
}

assert_mode_keys _default_       "$expect_all"        all
assert_mode_keys all             "$expect_all"        all
assert_mode_keys brainstorm      "$expect_brainstorm" brainstorm
assert_mode_keys implementation  "$expect_impl"       implementation
assert_mode_keys planning        "$expect_planning"   planning
assert_mode_keys human           "$expect_human"      human
pass "T6: --mode emits exact section-key set per spec §--mode contract (all | brainstorm | implementation | planning | human); in_flight always present"

# -----------------------------------------------------------------------------
# T8. is_impl_candidate handles `feature` leaf-impl beads (regression for
# PR #72 comment 3234282015 / 3234282059).
# brainstorm-bead finalize creates the implementation bead Y with
# issue_type=feature + label `implementation-ready`. A childless feature
# carrying that label IS a leaf impl bead and MUST appear under
# `--mode implementation` AND MUST be excluded from `planning_ready`.
# A previous over-broad guard (`btype not in CONTAINER_DESIGN_TYPES`)
# silently dropped this bead from all sections. This test would have
# failed against that regression.
# -----------------------------------------------------------------------------
TMP_T8=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8"' EXIT

cat > "$TMP_T8/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    echo '[]' ;;
  "list --status open,in_progress --limit 0 --json")
    # Childless feature with implementation-ready — the leaf impl bead.
    # No other active beads share this id as parent → active_child_count is 0.
    cat <<'JSON'
[
  {"id":"proj-leaffeat","issue_type":"feature","status":"open","priority":1,"title":"Leaf impl bead","labels":["implementation-ready"]}
]
JSON
    ;;
  "ready --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-leaffeat","issue_type":"feature","status":"open","priority":1,"title":"Leaf impl bead","labels":["implementation-ready"],"created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    # `--ready` may return the childless feature; planning_ready filter
    # must still drop it because of the implementation-ready label.
    cat <<'JSON'
[
  {"id":"proj-leaffeat","issue_type":"feature","status":"open","priority":1,"title":"Leaf impl bead","labels":["implementation-ready"]}
]
JSON
    ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T8/bd"

# (a) --mode implementation: leaf feature MUST appear.
OUT_T8_IMPL="$TMP_T8/impl.json"
PATH="$TMP_T8:$PATH" python3 "$COLLECT_PY" --mode implementation \
    >"$OUT_T8_IMPL" 2>"$TMP_T8/err.impl"
ec=$?
[ "$ec" -eq 0 ] \
    || fail "T8a: collect.py --mode implementation exited $ec (stderr: $(cat "$TMP_T8/err.impl"))"

OUT_T8_IMPL="$OUT_T8_IMPL" python3 - <<'PY' \
    || fail "T8a: childless feature with implementation-ready missing from implementation section"
import json, os, sys
out = json.load(open(os.environ["OUT_T8_IMPL"]))
impl = out.get("implementation", [])
ids = [b.get("id") for b in impl]
assert "proj-leaffeat" in ids, \
    f"leaf-impl feature must appear under implementation; got: {ids}"
# Also verify the type is preserved end-to-end.
match = next(b for b in impl if b.get("id") == "proj-leaffeat")
assert match.get("type") == "feature", \
    f"enriched type should be 'feature'; got {match.get('type')!r}"
PY
pass "T8a: childless feature with implementation-ready surfaces under --mode implementation"

# (b) --mode planning: leaf feature MUST NOT appear in planning_ready.
OUT_T8_PLAN="$TMP_T8/planning.json"
PATH="$TMP_T8:$PATH" python3 "$COLLECT_PY" --mode planning \
    >"$OUT_T8_PLAN" 2>"$TMP_T8/err.plan"
ec=$?
[ "$ec" -eq 0 ] \
    || fail "T8b: collect.py --mode planning exited $ec (stderr: $(cat "$TMP_T8/err.plan"))"

OUT_T8_PLAN="$OUT_T8_PLAN" python3 - <<'PY' \
    || fail "T8b: leaf-impl feature leaked into planning_ready (must be excluded by impl-ready label)"
import json, os, sys
out = json.load(open(os.environ["OUT_T8_PLAN"]))
pr = out.get("planning_ready", [])
ids = [b.get("id") for b in pr]
assert "proj-leaffeat" not in ids, \
    f"leaf-impl feature MUST be excluded from planning_ready; got: {ids}"
PY
pass "T8b: childless feature with implementation-ready is excluded from --mode planning"

# -----------------------------------------------------------------------------
# T9. Feature-Y impl bead with formula-gate (merge-gate) child must still
# appear in implementation. Regression for PR #72 Copilot R5/R7/R10:
# brainstorm-bead finalize creates Y as type=feature with implementation-
# ready, then attaches an OPEN merge-gate child under it. A naive
# "feature + has any children → container" rule would filter Y out of
# the implementation queue. The narrowed Rule B (active_child_count
# excludes children with merge-gate / human labels) keeps Y visible.
# -----------------------------------------------------------------------------
TMP_T9=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8" "$TMP_T9" ${TMP_T10:+"$TMP_T10"}' EXIT

cat > "$TMP_T9/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    echo '[]' ;;
  "list --status open,in_progress --limit 0 --json")
    # feature-Y impl bead + open merge-gate child + open [Human verify] child.
    # active_child_count for proj-yfeat must filter out both children →
    # count == 0 → proj-yfeat is NOT a container → surfaces in implementation.
    cat <<'JSON'
[
  {"id":"proj-yfeat","issue_type":"feature","status":"open","priority":1,"title":"[Impl] some feature","labels":["implementation-ready","brainstormed"]},
  {"id":"proj-mergegate","issue_type":"task","status":"open","priority":1,"title":"[merge-gate] some-feature","labels":["merge-gate"],"parent":"proj-yfeat"},
  {"id":"proj-humanverify","issue_type":"task","status":"open","priority":1,"title":"[verify] some-feature - check X","labels":["human"],"parent":"proj-yfeat"}
]
JSON
    ;;
  "ready --limit 0 --json")
    # bd ready returns the Y feat (merge-gate / human children carry
    # gating labels of their own, but Y itself is dep-unblocked).
    cat <<'JSON'
[
  {"id":"proj-yfeat","issue_type":"feature","status":"open","priority":1,"title":"[Impl] some feature","labels":["implementation-ready","brainstormed"],"created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-yfeat","issue_type":"feature","status":"open","priority":1,"title":"[Impl] some feature","labels":["implementation-ready","brainstormed"]}
]
JSON
    ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T9/bd"

OUT_T9_IMPL="$TMP_T9/impl.json"
PATH="$TMP_T9:$PATH" python3 "$COLLECT_PY" --mode implementation \
    >"$OUT_T9_IMPL" 2>"$TMP_T9/err.impl"
ec=$?
[ "$ec" -eq 0 ] \
    || fail "T9: collect.py --mode implementation exited $ec with feature-Y+merge-gate fixture (stderr: $(cat "$TMP_T9/err.impl"))"

OUT_T9_IMPL="$OUT_T9_IMPL" python3 - <<'PY' \
    || fail "T9: feature-Y impl bead with merge-gate / human children was wrongly filtered out of implementation queue"
import json, os, sys
out = json.load(open(os.environ["OUT_T9_IMPL"]))
impl = out.get("implementation", [])
ids = [b.get("id") for b in impl]
assert "proj-yfeat" in ids, \
    f"feature-Y with merge-gate/human children MUST appear under implementation (formula-gate children are excluded from active_child_count); got: {ids}"
PY
pass "T9: feature-Y impl bead with merge-gate / [Human verify] children surfaces under --mode implementation (narrowed Rule B)"

# -----------------------------------------------------------------------------
# T10. Mode-isolation regression: --mode <m> must only call bd show for the
# ancestors of beads in the section(s) that mode emits.
#
# Defect under test: the prior unconditional 4-section union construction
# of display_ids in collect.py caused resolve_all_ancestry to fire
# `bd show <parent>` for every section's parents even when only one
# section will be emitted. Under `--mode human`, only the human section's
# parent (h1-parent) should be fetched; the brainstorm/impl/planning
# parents (b1-parent, i1-parent, p1-parent) MUST NOT be fetched.
#
# The shim here is the only T-shim that LOGS its `show` invocations
# (T9's shim does not). Each `bd show <id> ...` invocation appends a
# single line `show <id>` to $TMP_T10/show.log.
# -----------------------------------------------------------------------------
TMP_T10=$(mktemp -d)
# trap already includes ${TMP_T10:+"$TMP_T10"} (set above on the T9 trap line).
SHOW_LOG="$TMP_T10/show.log"
: > "$SHOW_LOG"
export SHOW_LOG

cat > "$TMP_T10/bd" <<SHIM
#!/usr/bin/env bash
# Log only \`bd show <id> ...\` invocations, one event per line.
if [ "\$1" = "show" ]; then
  echo "show \$2" >> "$SHOW_LOG"
fi
case "\$*" in
  "list --label human --limit 0 --json")
    echo '[{"id":"proj-h1","issue_type":"task","status":"open","priority":1,"title":"H","labels":["human"],"parent":"h1-parent"}]' ;;
  "list --status open,in_progress --limit 0 --json")
    # Active inventory contains ONLY the four leaf beads — none of their
    # parents. This forces resolve_all_ancestry to issue \`bd show <parent>\`
    # for every parent it encounters in display_ids.
    cat <<'JSON'
[
  {"id":"proj-h1","issue_type":"task","status":"open","priority":1,"title":"H","labels":["human"],"parent":"h1-parent"},
  {"id":"proj-b1","issue_type":"task","status":"open","priority":1,"title":"B","labels":[],"parent":"b1-parent"},
  {"id":"proj-i1","issue_type":"task","status":"open","priority":1,"title":"I","labels":["implementation-ready"],"parent":"i1-parent"},
  {"id":"proj-p1","issue_type":"feature","status":"open","priority":1,"title":"P","labels":[],"parent":"p1-parent"}
]
JSON
    ;;
  "ready --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-b1","issue_type":"task","status":"open","priority":1,"title":"B","labels":[],"parent":"b1-parent","created_at":"2026-05-01"},
  {"id":"proj-i1","issue_type":"task","status":"open","priority":1,"title":"I","labels":["implementation-ready"],"parent":"i1-parent","created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    echo '[{"id":"proj-p1","issue_type":"feature","status":"open","priority":1,"title":"P","labels":[],"parent":"p1-parent"}]' ;;
  "show h1-parent --json")
    echo '[{"id":"h1-parent","issue_type":"task","parent":"","title":"parent bead","status":"open","priority":2,"labels":[]}]' ;;
  "show b1-parent --json")
    echo '[{"id":"b1-parent","issue_type":"task","parent":"","title":"parent bead","status":"open","priority":2,"labels":[]}]' ;;
  "show i1-parent --json")
    echo '[{"id":"i1-parent","issue_type":"task","parent":"","title":"parent bead","status":"open","priority":2,"labels":[]}]' ;;
  "show p1-parent --json")
    echo '[{"id":"p1-parent","issue_type":"task","parent":"","title":"parent bead","status":"open","priority":2,"labels":[]}]' ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T10/bd"

OUT_T10="$TMP_T10/human.json"
PATH="$TMP_T10:$PATH" python3 "$COLLECT_PY" --mode human \
    >"$OUT_T10" 2>"$TMP_T10/err.human"
ec=$?
[ "$ec" -eq 0 ] \
    || fail "T10: collect.py --mode human exited $ec (stderr: $(cat "$TMP_T10/err.human"))"

# Group (a) — sanity assertions (do NOT discriminate fixed vs unfixed).
OUT_T10="$OUT_T10" python3 - <<'PY' \
    || fail "T10a: --mode human output shape wrong (top-level section keys)"
import json, os
out = json.load(open(os.environ["OUT_T10"]))
assert "human" in out, f"--mode human must emit 'human' key; got: {sorted(out.keys())}"
human_ids = [b.get("id") for b in out.get("human", [])]
assert "proj-h1" in human_ids, f"human section must include proj-h1; got: {human_ids}"
for k in ("brainstorm", "implementation", "planning_ready"):
    assert k not in out, f"--mode human MUST NOT emit '{k}' (got keys: {sorted(out.keys())})"
PY
pass "T10a: --mode human emits only the 'human' section key and includes proj-h1"

# Group (b) — isolation assertions. THESE FAIL on the unfixed defect.
# (b1) h1-parent MUST be in the log (the human section's parent is always
#      legitimately fetched, fixed or unfixed).
grep -qE '^show h1-parent$' "$SHOW_LOG" \
    || fail "T10b1: expected 'show h1-parent' in $SHOW_LOG (log: $(cat "$SHOW_LOG"))"

# (b2) None of {b1-parent, i1-parent, p1-parent} may be fetched — under
#      --mode human, the brainstorm/impl/planning sections are not emitted,
#      so their parents must not be resolved.
for forbidden in b1-parent i1-parent p1-parent; do
    if grep -qE "^show ${forbidden}\$" "$SHOW_LOG"; then
        fail "T10b2: --mode human leaked 'show $forbidden' — display_ids must be scoped to the active mode's sections (log: $(cat "$SHOW_LOG"))"
    fi
done
pass "T10b: --mode human fetches only h1-parent; brainstorm/impl/planning parents are not fetched (display_ids scoped to emitted sections)"

# -----------------------------------------------------------------------------
# T11. HEP escalation child discrimination via `hep-pause` label.
#
# Scenario: A feature bead (no readiness labels) has exactly one open child
# carrying BOTH `human` AND `hep-pause` labels — the post-fix shape of a HEP
# escalation bead (HEB) sitting under a container source.
#
# Expected behavior (after fix): the production active_child_count loop
# COUNTS the hep-pause child → is_container() returns True for the feature
# → the feature is hidden from planning_ready (active container).
#
# Current (buggy) behavior: the count-construction loop excludes any
# `human`-labeled child unconditionally → active_child_count == 0 →
# is_container() returns False → feature treated as childless → SURFACES
# in planning_ready → TEST FAILS.
#
# Test method: end-to-end via collect.py --mode planning so the production
# filter is exercised. Assertion: the feature is NOT in planning_ready
# (it has an active hep-pause child, so it is a container).
# -----------------------------------------------------------------------------
TMP_T11=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8" "$TMP_T9" ${TMP_T10:+"$TMP_T10"} "$TMP_T11"' EXIT

cat > "$TMP_T11/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    # The hep-pause child also carries `human` so it surfaces here.
    echo '[{"id":"proj-hebchild","issue_type":"task","status":"open","priority":1,"title":"Human input needed","labels":["human","hep-pause"],"parent":"proj-hepfeat"}]' ;;
  "list --status open,in_progress --limit 0 --json")
    # Feature (no readiness labels) + ONE child carrying human+hep-pause.
    # Under the FIX, the child IS counted → feature is a container.
    # Under current code, the child is excluded → count=0 → feature is
    # treated as childless and leaks into planning_ready.
    cat <<'JSON'
[
  {"id":"proj-hepfeat","issue_type":"feature","status":"open","priority":1,"title":"feature paused via HEP","labels":[]},
  {"id":"proj-hebchild","issue_type":"task","status":"open","priority":1,"title":"Human input needed","labels":["human","hep-pause"],"parent":"proj-hepfeat"}
]
JSON
    ;;
  "ready --limit 0 --json")
    # Feature is dep-unblocked (container HEP gates via parent-child shape,
    # not a blocks edge).
    cat <<'JSON'
[
  {"id":"proj-hepfeat","issue_type":"feature","status":"open","priority":1,"title":"feature paused via HEP","labels":[],"created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    # Childless-looking feature is returned by the --ready query; planning
    # filter must drop it because active_child_count > 0 (after fix).
    cat <<'JSON'
[
  {"id":"proj-hepfeat","issue_type":"feature","status":"open","priority":1,"title":"feature paused via HEP","labels":[]}
]
JSON
    ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T11/bd"

OUT_T11="$TMP_T11/planning.json"
PATH="$TMP_T11:$PATH" python3 "$COLLECT_PY" --mode planning \
    >"$OUT_T11" 2>"$TMP_T11/err.plan"
ec=$?
[ "$ec" -eq 0 ] \
    || fail "T11: collect.py --mode planning exited $ec (stderr: $(cat "$TMP_T11/err.plan"))"

OUT_T11="$OUT_T11" python3 - <<'PY' \
    || fail "T11: HEP-paused feature (one human+hep-pause child) leaked into planning_ready (active-child filter must count hep-pause children)"
import json, os
out = json.load(open(os.environ["OUT_T11"]))
pr = out.get("planning_ready", [])
ids = [b.get("id") for b in pr]
assert "proj-hepfeat" not in ids, (
    f"feature with one open human+hep-pause child MUST NOT appear in "
    f"planning_ready (it is an active container; the hep-pause child must "
    f"be counted toward active_child_count); got planning_ready ids: {ids}"
)
PY
pass "T11: HEP-paused feature with one human+hep-pause child is recognized as a container (excluded from planning_ready)"

# -----------------------------------------------------------------------------
# T12. Feature with `implementation-ready` whose ONLY active child carries
# `human+hep-pause` must NOT surface in --mode implementation.
#
# Scenario: A feature carrying `implementation-ready` has exactly one open
# child carrying ['human','hep-pause'] — the post-fix HEP shape. The
# feature is a paused container, not a leaf impl bead.
#
# Expected behavior (after fix): active_child_count == 1 → is_container()
# True → is_impl_candidate() False → feature NOT in implementation section.
#
# Current (buggy) behavior: hep-pause child wrongly excluded → count == 0 →
# is_container() False → feature TREATED AS LEAF IMPL → appears in
# implementation section → TEST FAILS.
# -----------------------------------------------------------------------------
TMP_T12=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8" "$TMP_T9" ${TMP_T10:+"$TMP_T10"} "$TMP_T11" "$TMP_T12"' EXIT

cat > "$TMP_T12/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    # The hep-pause child carries `human` so it surfaces here too — but the
    # human SECTION just shows it (irrelevant to the implementation
    # assertion below).
    echo '[{"id":"proj-hebchild","issue_type":"task","status":"open","priority":1,"title":"Human input needed","labels":["human","hep-pause"],"parent":"proj-pausedfeat"}]' ;;
  "list --status open,in_progress --limit 0 --json")
    # Feature with implementation-ready + ONLY a human+hep-pause child.
    # Under the FIX, the child is counted → feature is a container →
    # excluded from implementation. Under current code, the child is
    # excluded → count=0 → feature treated as a leaf impl bead → leaks
    # into implementation queue.
    cat <<'JSON'
[
  {"id":"proj-pausedfeat","issue_type":"feature","status":"open","priority":1,"title":"[Impl] feature paused via HEP","labels":["implementation-ready"]},
  {"id":"proj-hebchild","issue_type":"task","status":"open","priority":1,"title":"Human input needed","labels":["human","hep-pause"],"parent":"proj-pausedfeat"}
]
JSON
    ;;
  "ready --limit 0 --json")
    # bd ready returns the paused feature (it has impl-ready label and no
    # blocking dep, since HEP for containers uses parent-child gating, not
    # a blocks edge).
    cat <<'JSON'
[
  {"id":"proj-pausedfeat","issue_type":"feature","status":"open","priority":1,"title":"[Impl] feature paused via HEP","labels":["implementation-ready"],"created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    cat <<'JSON'
[
  {"id":"proj-pausedfeat","issue_type":"feature","status":"open","priority":1,"title":"[Impl] feature paused via HEP","labels":["implementation-ready"]}
]
JSON
    ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T12/bd"

OUT_T12="$TMP_T12/impl.json"
PATH="$TMP_T12:$PATH" python3 "$COLLECT_PY" --mode implementation \
    >"$OUT_T12" 2>"$TMP_T12/err.impl"
ec=$?
[ "$ec" -eq 0 ] \
    || fail "T12: collect.py --mode implementation exited $ec (stderr: $(cat "$TMP_T12/err.impl"))"

OUT_T12="$OUT_T12" python3 - <<'PY' \
    || fail "T12: paused feature with only human+hep-pause child leaked into implementation queue (active-child filter must count hep-pause children)"
import json, os
out = json.load(open(os.environ["OUT_T12"]))
impl = out.get("implementation", [])
ids = [b.get("id") for b in impl]
assert "proj-pausedfeat" not in ids, (
    f"feature with implementation-ready and ONLY a human+hep-pause child "
    f"MUST NOT appear in implementation (it is a HEP-paused container, not "
    f"a leaf impl bead); got implementation ids: {ids}"
)
PY
pass "T12: HEP-paused feature (impl-ready + only human+hep-pause child) is excluded from --mode implementation"

# -----------------------------------------------------------------------------
# T13. --label filter: restricts every section to beads whose own `labels`
# array contains the requested label (case-insensitive exact match). Beads
# without the label are dropped from human / brainstorm / implementation /
# planning_ready, and `totals` reflect the filtered counts.
# -----------------------------------------------------------------------------
TMP_T13=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8" "$TMP_T9" ${TMP_T10:+"$TMP_T10"} "$TMP_T11" "$TMP_T12" "$TMP_T13"' EXIT

cat > "$TMP_T13/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --limit 0 --json")
    # Two human beads; only one carries `install`.
    cat <<'JSON'
[
  {"id":"proj-h-inst","issue_type":"task","status":"open","priority":1,"title":"installer human","labels":["human","install"]},
  {"id":"proj-h-other","issue_type":"task","status":"open","priority":1,"title":"other human","labels":["human"]}
]
JSON
    ;;
  "list --status open,in_progress --limit 0 --json")
    # Mirror the ready set so the fail-closed active-child guard is satisfied.
    cat <<'JSON'
[
  {"id":"proj-b-inst","issue_type":"task","status":"open","priority":1,"title":"installer brainstorm","labels":["install"]},
  {"id":"proj-b-other","issue_type":"task","status":"open","priority":1,"title":"other brainstorm","labels":[]},
  {"id":"proj-i-inst","issue_type":"task","status":"open","priority":1,"title":"installer impl","labels":["install","implementation-ready"]},
  {"id":"proj-i-other","issue_type":"task","status":"open","priority":1,"title":"other impl","labels":["implementation-ready"]}
]
JSON
    ;;
  "ready --limit 0 --json")
    # Brainstorm + impl candidates, mixed install / non-install.
    cat <<'JSON'
[
  {"id":"proj-b-inst","issue_type":"task","status":"open","priority":1,"title":"installer brainstorm","labels":["install"],"created_at":"2026-05-01"},
  {"id":"proj-b-other","issue_type":"task","status":"open","priority":1,"title":"other brainstorm","labels":[],"created_at":"2026-05-01"},
  {"id":"proj-i-inst","issue_type":"task","status":"open","priority":1,"title":"installer impl","labels":["install","implementation-ready"],"created_at":"2026-05-01"},
  {"id":"proj-i-other","issue_type":"task","status":"open","priority":1,"title":"other impl","labels":["implementation-ready"],"created_at":"2026-05-01"}
]
JSON
    ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json")
    # Childless planning-ready features, mixed install / non-install.
    cat <<'JSON'
[
  {"id":"proj-p-inst","issue_type":"feature","status":"open","priority":1,"title":"installer feature","labels":["install"]},
  {"id":"proj-p-other","issue_type":"feature","status":"open","priority":1,"title":"other feature","labels":[]}
]
JSON
    ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T13/bd"

# (a) --label install (lowercase exact)
OUT_T13="$TMP_T13/all.json"
PATH="$TMP_T13:$PATH" python3 "$COLLECT_PY" --label install >"$OUT_T13" 2>"$TMP_T13/err"
ec=$?
[ "$ec" -eq 0 ] || fail "T13a: collect.py --label install exited $ec (stderr: $(cat "$TMP_T13/err"))"

OUT_T13="$OUT_T13" python3 - <<'PY' || fail "T13a: --label install did not filter every section to install-labeled beads"
import json, os
out = json.load(open(os.environ["OUT_T13"]))
def ids(k): return [b.get("id") for b in out.get(k, [])]
assert ids("human") == ["proj-h-inst"], f"human: {ids('human')}"
assert ids("brainstorm") == ["proj-b-inst"], f"brainstorm: {ids('brainstorm')}"
assert ids("implementation") == ["proj-i-inst"], f"implementation: {ids('implementation')}"
assert ids("planning_ready") == ["proj-p-inst"], f"planning_ready: {ids('planning_ready')}"
# `in_flight` is mode-independent and always present in totals (no in_progress
# beads in this fixture → count 0), exempt from --label filtering.
t = out["totals"]
assert t == {"human":1,"planning_ready":1,"brainstorm":1,"implementation":1,"in_flight":0}, f"totals: {t}"
PY
pass "T13a: --label install filters all sections to install-labeled beads; totals reflect filter"

# (b) case-insensitive: --label INSTALL yields the same set.
OUT_T13B="$TMP_T13/ci.json"
PATH="$TMP_T13:$PATH" python3 "$COLLECT_PY" --label INSTALL --mode brainstorm >"$OUT_T13B" 2>"$TMP_T13/err.b"
ec=$?
[ "$ec" -eq 0 ] || fail "T13b: collect.py --label INSTALL exited $ec (stderr: $(cat "$TMP_T13/err.b"))"
OUT_T13B="$OUT_T13B" python3 - <<'PY' || fail "T13b: --label is not case-insensitive"
import json, os
out = json.load(open(os.environ["OUT_T13B"]))
ids = [b.get("id") for b in out.get("brainstorm", [])]
assert ids == ["proj-b-inst"], f"brainstorm (INSTALL): {ids}"
PY
pass "T13b: --label match is case-insensitive"

# -----------------------------------------------------------------------------
# T14. Completeness: `bd ready` MUST be invoked with `--limit 0` so the
# brainstorm/implementation source set (and its totals) is not silently
# capped at bd's default 100-row page. Regression for the hidden-results bug.
# The shim logs every invocation's full arg list.
# -----------------------------------------------------------------------------
TMP_T14=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8" "$TMP_T9" ${TMP_T10:+"$TMP_T10"} "$TMP_T11" "$TMP_T12" "$TMP_T13" "$TMP_T14"' EXIT
CALL_LOG="$TMP_T14/calls.log"
: > "$CALL_LOG"
export CALL_LOG

cat > "$TMP_T14/bd" <<SHIM
#!/usr/bin/env bash
echo "\$*" >> "$CALL_LOG"
case "\$*" in
  "list --label human --limit 0 --json") echo '[]' ;;
  "list --status open,in_progress --limit 0 --json")
    echo '[{"id":"proj-b1","issue_type":"task","status":"open","priority":1,"title":"B","labels":[]}]' ;;
  "ready --limit 0 --json")
    echo '[{"id":"proj-b1","issue_type":"task","status":"open","priority":1,"title":"B","labels":[],"created_at":"2026-05-01"}]' ;;
  "list --type milestone --ready --limit 0 --json") echo '[]' ;;
  "list --type epic --ready --limit 0 --json") echo '[]' ;;
  "list --type feature --ready --limit 0 --json") echo '[]' ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T14/bd"

PATH="$TMP_T14:$PATH" python3 "$COLLECT_PY" --mode brainstorm >/dev/null 2>"$TMP_T14/err"
ec=$?
[ "$ec" -eq 0 ] || fail "T14: collect.py exited $ec (stderr: $(cat "$TMP_T14/err"))"
grep -qE '^ready --limit 0 --json$' "$CALL_LOG" \
    || fail "T14: bd ready must be called with '--limit 0' to avoid the 100-row cap (calls: $(cat "$CALL_LOG"))"
pass "T14: bd ready is invoked with --limit 0 (no silent 100-row cap)"

# -----------------------------------------------------------------------------
# T15. parse_bd_timestamp always returns a timezone-aware datetime (or None).
# Regression for PR #231 comment 3525472321: an offsetless ISO string parsed
# to a NAIVE datetime, which raised TypeError in claim_age_days() (subtracting
# from an aware datetime.now) and in build_in_flight's sort key (comparing
# against an aware datetime.max). Non-string input must return None, not raise.
# -----------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T15: parse_bd_timestamp naive/non-string handling incorrect"
import importlib.util, sys
from datetime import datetime, timezone
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Offsetless (naive) ISO string → aware datetime coerced to UTC.
aware = mod.parse_bd_timestamp("2026-07-04T17:58:57")
assert aware is not None, "offsetless timestamp must parse, not return None"
assert aware.tzinfo is not None, "offsetless parse must be coerced to an aware datetime"
assert aware.utcoffset() == timezone.utc.utcoffset(None), "naive parse must be coerced to UTC"
# Aware arithmetic against now(utc) must not raise (the reported TypeError).
_ = datetime.now(timezone.utc) - aware

# Z-suffixed timestamp stays aware.
zaware = mod.parse_bd_timestamp("2026-07-04T17:58:57Z")
assert zaware is not None and zaware.tzinfo is not None, "Z-suffixed parse must be aware"

# Non-string / missing input → None, never raising.
for bad in (None, 12345, [], {}, ""):
    assert mod.parse_bd_timestamp(bad) is None, f"non-string/empty input {bad!r} must return None"
PY
pass "T15: parse_bd_timestamp returns aware datetimes and None for non-string/missing input"

# -----------------------------------------------------------------------------
# T16. backlog_grooming_nag: best-effort `work groom --status` call.
#   (a) work unavailable (not on PATH) -> key absent, collect.py still exits 0.
#   (b) work available, breached:false -> key absent.
#   (c) work available, breached:true, days_since known -> key present with
#       the day count folded into the message.
#   (d) work exits non-zero (e.g. E_NOT_CONFIGURED, this repo's real case
#       today since its own groom-state-bead is still blank) -> key absent.
# All four self-silence: none may raise or change collect.py's exit code.
# -----------------------------------------------------------------------------
TMP_T16=$(mktemp -d)
trap 'rm -rf "$TMP_T3" "$TMP_T5" "$TMP_T6" "$TMP_T8" "$TMP_T9" ${TMP_T10:+"$TMP_T10"} "$TMP_T11" "$TMP_T12" "$TMP_T13" "$TMP_T14" "$TMP_T16"' EXIT

cat > "$TMP_T16/bd" <<'SHIM'
#!/usr/bin/env bash
# One human bead keeps collect.py off its "nothing anywhere" exit-1 bail
# (empty_raw everywhere) -- every other query returns empty.
case "$*" in
  "list --label human --limit 0 --json")
    echo '[{"id":"proj-h1","issue_type":"task","status":"open","priority":1,"title":"H","labels":["human"]}]' ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMP_T16/bd"

# (a) no `work` shim at all -- collect.py's `work_groom_status` must catch
# FileNotFoundError and return None; the whole run must still exit 0.
OUT_T16A="$TMP_T16/a.json"
PATH="$TMP_T16:$PATH" python3 "$COLLECT_PY" --mode human >"$OUT_T16A" 2>"$TMP_T16/err.a"
ec=$?
[ "$ec" -eq 0 ] || fail "T16a: collect.py exited $ec with no 'work' on PATH (stderr: $(cat "$TMP_T16/err.a"))"
python3 -c "
import json
out = json.load(open('$OUT_T16A'))
assert 'backlog_grooming_nag' not in out, f'nag must be absent when work is unavailable; got: {out}'
" || fail "T16a: backlog_grooming_nag must be absent when 'work' is not on PATH"
pass "T16a: backlog_grooming_nag absent when 'work' is not on PATH (self-silenced)"

# (b) `work groom --status` succeeds, breached:false -> key absent.
cat > "$TMP_T16/work" <<'SHIM'
#!/usr/bin/env bash
echo '{"protocol":"1.0","ok":true,"data":{"backlog_last_groomed":"2026-07-14T00:00:00Z","days_since":2,"nag_days":7,"breached":false},"error":null}'
SHIM
chmod +x "$TMP_T16/work"
OUT_T16B="$TMP_T16/b.json"
PATH="$TMP_T16:$PATH" python3 "$COLLECT_PY" --mode human >"$OUT_T16B" 2>"$TMP_T16/err.b"
ec=$?
[ "$ec" -eq 0 ] || fail "T16b: collect.py exited $ec with breached:false (stderr: $(cat "$TMP_T16/err.b"))"
python3 -c "
import json
out = json.load(open('$OUT_T16B'))
assert 'backlog_grooming_nag' not in out, f'nag must be absent when not breached; got: {out}'
" || fail "T16b: backlog_grooming_nag must be absent when not breached"
pass "T16b: backlog_grooming_nag absent when work groom --status reports breached:false"

# (c) breached:true, days_since known -> key present, day count folded in.
cat > "$TMP_T16/work" <<'SHIM'
#!/usr/bin/env bash
echo '{"protocol":"1.0","ok":true,"data":{"backlog_last_groomed":"2026-07-01T00:00:00Z","days_since":17,"nag_days":7,"breached":true},"error":null}'
SHIM
chmod +x "$TMP_T16/work"
OUT_T16C="$TMP_T16/c.json"
PATH="$TMP_T16:$PATH" python3 "$COLLECT_PY" --mode human >"$OUT_T16C" 2>"$TMP_T16/err.c"
ec=$?
[ "$ec" -eq 0 ] || fail "T16c: collect.py exited $ec with breached:true (stderr: $(cat "$TMP_T16/err.c"))"
python3 -c "
import json
out = json.load(open('$OUT_T16C'))
nag = out.get('backlog_grooming_nag')
assert nag is not None, f'nag must be present when breached; got: {out}'
assert '17' in nag, f'nag must fold in days_since; got: {nag!r}'
assert 'Backlog Grooming' in nag, f'nag must be labeled Backlog Grooming; got: {nag!r}'
" || fail "T16c: backlog_grooming_nag must be present and carry the day count when breached"
pass "T16c: backlog_grooming_nag present with day count when work groom --status reports breached:true"

# (d) `work` exits non-zero (E_NOT_CONFIGURED envelope, ok:false) -> key absent.
cat > "$TMP_T16/work" <<'SHIM'
#!/usr/bin/env bash
echo '{"protocol":"1.0","ok":false,"data":null,"error":{"code":"E_NOT_CONFIGURED","message":"nope","detail":{}}}'
exit 1
SHIM
chmod +x "$TMP_T16/work"
OUT_T16D="$TMP_T16/d.json"
PATH="$TMP_T16:$PATH" python3 "$COLLECT_PY" --mode human >"$OUT_T16D" 2>"$TMP_T16/err.d"
ec=$?
[ "$ec" -eq 0 ] || fail "T16d: collect.py exited $ec with an E_NOT_CONFIGURED work envelope (stderr: $(cat "$TMP_T16/err.d"))"
python3 -c "
import json
out = json.load(open('$OUT_T16D'))
assert 'backlog_grooming_nag' not in out, f'nag must be absent on an ok:false envelope; got: {out}'
" || fail "T16d: backlog_grooming_nag must be absent when work groom --status returns ok:false"
pass "T16d: backlog_grooming_nag absent when work groom --status returns an ok:false envelope (e.g. E_NOT_CONFIGURED)"

echo "All collect.py red-phase tests reached — script exits 0 only when every assertion above passes."
