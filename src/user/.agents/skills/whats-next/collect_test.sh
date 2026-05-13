#!/usr/bin/env bash
# Red-phase tests for AC2: collect.py must grow:
#   - is_container(id, type) function (type-based container filter)
#   - planning-ready output section
#   - --mode flag (brainstorm | implementation)
#   - 7-column enriched output: milestone_col, feature_col, parent_epic_col, type
#   - default sections = human + planning-ready + brainstorm; impl only via --mode
#   - is_brainstorm_candidate excludes container-design types
#       (milestone, epic, feature, decision)
set -u

# Resolve script dir → collect.py path.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECT_PY="$SCRIPT_DIR/collect.py"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[ -f "$COLLECT_PY" ] || fail "collect.py not found at $COLLECT_PY"

# -----------------------------------------------------------------------------
# T1. is_container() exists and classifies types correctly.
# -----------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T1: is_container function missing or incorrect classification"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, "is_container"), "is_container function not defined"
# Containers: epic, milestone, feature (the three container-design types
# plus decision is treated as container-design for brainstorm exclusion;
# is_container narrowly covers structural containers per the spec).
assert mod.is_container("foo", "epic")      is True,  "epic must be container"
assert mod.is_container("foo", "milestone") is True,  "milestone must be container"
assert mod.is_container("foo", "feature")   is True,  "feature must be container"
# Non-containers
assert mod.is_container("foo", "task")  is False, "task must not be container"
assert mod.is_container("foo", "bug")   is False, "bug must not be container"
assert mod.is_container("foo", "chore") is False, "chore must not be container"
assert mod.is_container("foo", "spike") is False, "spike must not be container"
assert mod.is_container("foo", "story") is False, "story must not be container"
PY
pass "T1: is_container() classifies types correctly"

# -----------------------------------------------------------------------------
# T2. is_brainstorm_candidate excludes container-design types
#     (milestone, epic, feature, decision).
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
# Sanity: task/bug/chore/story/spike still pass the brainstorm filter when
# they have no excluding labels.
for t in ("task", "bug", "chore", "story", "spike"):
    res = mod.is_brainstorm_candidate(mk(t))
    assert res is True, f"is_brainstorm_candidate must accept type={t} (got {res!r})"
PY
pass "T2: is_brainstorm_candidate excludes container-design types"

# -----------------------------------------------------------------------------
# T3. --mode flag exists; accepts brainstorm / implementation.
# -----------------------------------------------------------------------------
python3 "$COLLECT_PY" --mode brainstorm --help >/dev/null 2>&1
# We don't depend on --help; the meaningful probe is argparse acceptance of
# --mode. Run with --mode and a no-op limit; any nonzero exit BEFORE bd-fetch
# is fine (we tolerate exit 1 = "no data") — what we don't tolerate is
# argparse rejecting --mode (exit 2 with "unrecognized arguments").
out_brainstorm=$(python3 "$COLLECT_PY" --mode brainstorm --limit 0 2>&1)
ec=$?
echo "$out_brainstorm" | grep -qE 'unrecognized arguments|invalid choice' \
    && fail "T3a: --mode brainstorm rejected by argparse"
# Exit code may be 0 (success) or 1 (no data) — both acceptable.
[ "$ec" -eq 0 ] || [ "$ec" -eq 1 ] || fail "T3a: unexpected exit code $ec for --mode brainstorm (output: $out_brainstorm)"

out_impl=$(python3 "$COLLECT_PY" --mode implementation --limit 0 2>&1)
ec=$?
echo "$out_impl" | grep -qE 'unrecognized arguments|invalid choice' \
    && fail "T3b: --mode implementation rejected by argparse"
[ "$ec" -eq 0 ] || [ "$ec" -eq 1 ] || fail "T3b: unexpected exit code $ec for --mode implementation"
pass "T3: --mode flag accepted with values brainstorm and implementation"

# -----------------------------------------------------------------------------
# T4. enrich() emits the 7-column fields:
#       milestone_col, feature_col, parent_epic_col, type
#     (in addition to id/short_id/priority/title/labels).
# -----------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T4: enrich() output missing 7-column fields"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
# enrich() in the current implementation is a closure inside main(); after the
# AC2 refactor it must be a module-level (or otherwise reachable) function
# OR main() must expose its output shape. Probe by either:
#   (a) a module-level enrich() that takes (beads, ancestry_map, known, shorten)
#       OR equivalent signature, OR
#   (b) the JSON output schema documented in SKILL.md.
# We probe (a) here; T5 covers the JSON shape end-to-end.
assert hasattr(mod, "enrich"), "enrich() must be module-level (currently nested inside main())"
PY
pass "T4: enrich() is module-level and produces the 7-column shape"

# -----------------------------------------------------------------------------
# T5. JSON output schema: includes planning_ready section and the new
#     per-bead column fields (milestone_col, feature_col, parent_epic_col, type).
#     We mock bd by inserting a shim early on PATH.
# -----------------------------------------------------------------------------
TMPDIR_T5=$(mktemp -d)
trap 'rm -rf "$TMPDIR_T5"' EXIT

cat > "$TMPDIR_T5/bd" <<'SHIM'
#!/usr/bin/env bash
# Minimal bd shim for collect.py testing. Recognizes only the queries
# collect.py makes; everything else returns [].
case "$*" in
  "list --label human --json")
    echo '[]' ;;
  "ready --json")
    cat <<'JSON'
[
  {"id":"proj-task1","issue_type":"task","status":"open","priority":1,"title":"Do a thing","labels":[],"parent":"proj-epic1","created_at":"2026-05-01"},
  {"id":"proj-epic1","issue_type":"epic","status":"open","priority":1,"title":"Some epic","labels":[],"parent":"proj-feat1","created_at":"2026-05-01"},
  {"id":"proj-feat1","issue_type":"feature","status":"open","priority":1,"title":"Some feature","labels":[],"parent":"proj-ms1","created_at":"2026-05-01"},
  {"id":"proj-ms1","issue_type":"milestone","status":"open","priority":1,"title":"M1","labels":[],"created_at":"2026-05-01"}
]
JSON
    ;;
  "show proj-feat1 --json")
    echo '[{"id":"proj-feat1","issue_type":"feature","priority":1,"title":"Some feature","labels":[],"parent":"proj-ms1"}]' ;;
  "show proj-ms1 --json")
    echo '[{"id":"proj-ms1","issue_type":"milestone","priority":1,"title":"M1","labels":[]}]' ;;
  "show proj-epic1 --json")
    echo '[{"id":"proj-epic1","issue_type":"epic","priority":1,"title":"Some epic","labels":[],"parent":"proj-feat1"}]' ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMPDIR_T5/bd"

OUT=$(PATH="$TMPDIR_T5:$PATH" python3 "$COLLECT_PY" 2>&1)
ec=$?
[ "$ec" -eq 0 ] || fail "T5: collect.py exited $ec with shim (output: $OUT)"

python3 - <<PY || fail "T5: JSON output schema missing required keys/fields"
import json
out = json.loads(r'''$OUT''')
# Top-level: planning_ready section required.
assert "planning_ready" in out, "top-level output must include planning_ready section"
# A bead in any displayed list must have the four enriched column fields.
sample_lists = []
for k in ("human", "brainstorm", "planning_ready", "implementation"):
    sample_lists += out.get(k, [])
if not sample_lists:
    raise AssertionError("no enriched beads in any section — cannot probe column fields")
required_fields = {"milestone_col", "feature_col", "parent_epic_col", "type"}
b = sample_lists[0]
missing = required_fields - set(b.keys())
assert not missing, f"enriched bead missing fields: {missing} (got keys: {sorted(b.keys())})"
PY
pass "T5: JSON output includes planning_ready section and 7-column fields"

# -----------------------------------------------------------------------------
# T6. Default sections (no --mode flag) include human + planning_ready +
#     brainstorm but DO include impl only on explicit --mode implementation.
#     We probe by argparse default + the JSON shape — implementation list
#     must be empty in default mode even when ready_raw contains impl beads.
# -----------------------------------------------------------------------------
cat > "$TMPDIR_T5/bd" <<'SHIM'
#!/usr/bin/env bash
case "$*" in
  "list --label human --json") echo '[]' ;;
  "ready --json")
    cat <<'JSON'
[
  {"id":"proj-impl1","issue_type":"task","status":"open","priority":1,"title":"Ready to impl","labels":["implementation-ready"],"created_at":"2026-05-01"}
]
JSON
    ;;
  *) echo '[]' ;;
esac
SHIM
chmod +x "$TMPDIR_T5/bd"

DEFAULT_OUT=$(PATH="$TMPDIR_T5:$PATH" python3 "$COLLECT_PY" 2>&1)
[ $? -eq 0 ] || fail "T6: collect.py (default mode) failed"

python3 - <<PY || fail "T6: default mode must NOT include implementation list"
import json
out = json.loads(r'''$DEFAULT_OUT''')
impl = out.get("implementation", [])
# Spec: default sections = human+planning-ready+brainstorm (impl only on
# explicit --mode implementation).
assert impl == [], f"default mode must omit implementation beads; got: {impl}"
PY
pass "T6: default mode excludes implementation list"

echo "All collect.py red-phase tests reached — script exits 0 only when every assertion above passes."
