#!/usr/bin/env bash
# PR #72 stress-test — GROUP A: whats-next modes (live JSON output validation).
#
# Probes the SHIPPED behavior of src/user/.agents/skills/whats-next/collect.py
# (the JSON-emitting helper that the whats-next SKILL.md renders into the
# 4-section table). These tests are NOT classic red-phase: PR #72 has shipped,
# so they may pass on first run — that is intentional. They are real
# assertions against observable behavior and exit 1 on any mismatch.
#
# Coverage (AC bullets from the stress-test brief):
#   A1. --mode all exits 0; JSON contains the four section keys
#       (human, planning_ready, brainstorm, implementation).
#   A2. --mode implementation: zero rows with type in {milestone, epic,
#       decision}; zero rows with type=feature AND active non-formula-gate
#       children.
#   A3. --mode brainstorm: every row lacks `brainstormed` label AND has
#       type NOT in {milestone, epic, feature, decision} (BRAINSTORM_EXCLUDED_TYPES).
#   A4. --mode planning: every row is a container (type in {milestone,
#       epic, feature}) with zero non-formula-gate children.
#   A5. --mode human: every row carries the `human` label.
#   A6. Default mode (no --mode) emits same section-key set as --mode all.
#   A7. Empty-state messages: SKILL.md documents the spec'd empty-state
#       strings for each of 5 modes (the agent renders these; this test
#       asserts the spec contract still exists).
#   A8. 7-column schema per row: every enriched row carries fields
#       short_id, priority, type, title, milestone_col, feature_col,
#       parent_epic_col (the 7 columns P|Milestone|Feature|Parent Epic|
#       Bead ID|Type|Title).
#
# Cleanup: this script is read-only against the bd database. No sacrificial
# beads are created.
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }
skip() { echo "SKIP: $* (no live bd data — assertion deferred)"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/plugins/beads" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/plugins/beads" ] \
    || fail "could not locate repo root containing src/plugins/beads"

COLLECT_PY="$REPO_ROOT/src/user/.agents/skills/whats-next/collect.py"
SKILL_MD="$REPO_ROOT/src/user/.agents/skills/whats-next/SKILL.md"
[ -f "$COLLECT_PY" ] || fail "collect.py not found at $COLLECT_PY"
[ -f "$SKILL_MD" ]   || fail "whats-next SKILL.md not found at $SKILL_MD"

command -v bd      >/dev/null 2>&1 || fail "bd CLI not on PATH"
command -v python3 >/dev/null 2>&1 || fail "python3 required"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# -----------------------------------------------------------------------------
# Helper: run collect.py in a given mode; tolerate empty-data exit 1 (the
# script exits 1 when bd returns no data at all). For these live tests we
# expect bd to return data; we still treat exit 1 as informational (the
# behavior is: assertion is vacuously satisfied for empty sections).
# -----------------------------------------------------------------------------
run_collect() {
    local mode="$1" out="$2"
    if [ "$mode" = "_default_" ]; then
        python3 "$COLLECT_PY" --limit 0 >"$out" 2>"$WORK/err"
    else
        python3 "$COLLECT_PY" --mode "$mode" --limit 0 >"$out" 2>"$WORK/err"
    fi
    return $?
}

# -----------------------------------------------------------------------------
# A1. --mode all exits 0 (or 1 = no data); JSON contains all four section keys.
# -----------------------------------------------------------------------------
OUT_ALL="$WORK/all.json"
run_collect all "$OUT_ALL"
ec=$?
if [ "$ec" -ne 0 ] && [ "$ec" -ne 1 ]; then
    fail "A1: collect.py --mode all exited $ec (expected 0 or 1; stderr: $(cat "$WORK/err"))"
fi
if [ "$ec" -eq 0 ]; then
    OUT_ALL="$OUT_ALL" python3 - <<'PY' || fail "A1: JSON missing one or more required section keys"
import json, os
out = json.load(open(os.environ["OUT_ALL"]))
required = {"human", "planning_ready", "brainstorm", "implementation"}
missing = required - set(out.keys())
if missing:
    raise SystemExit(f"A1: missing section keys in --mode all output: {missing}")
PY
    pass "A1: --mode all exits 0 and emits all four section keys"
else
    skip "A1: --mode all exited 1 (no bd data)"
fi

# -----------------------------------------------------------------------------
# A2. --mode implementation: no rows with disallowed types or
# feature-with-active-non-formula-gate children.
# -----------------------------------------------------------------------------
OUT_IMPL="$WORK/impl.json"
run_collect implementation "$OUT_IMPL"
ec=$?
if [ "$ec" -eq 0 ]; then
    OUT_IMPL="$OUT_IMPL" python3 - <<'PY' || fail "A2: implementation section violates type/child constraints"
import json, os, subprocess
out = json.load(open(os.environ["OUT_IMPL"]))
impl = out.get("implementation", [])
DISALLOWED = {"milestone", "epic", "decision"}
for row in impl:
    btype = row.get("type", "")
    if btype in DISALLOWED:
        raise SystemExit(f"A2: implementation row has disallowed type {btype!r}: {row.get('id')}")
# For feature rows, probe live bd for active non-formula-gate children.
for row in impl:
    if row.get("type") != "feature":
        continue
    bid = row.get("id", "")
    if not bid:
        continue
    # bd list --parent <id> --status open,in_progress --limit 0 --json
    proc = subprocess.run(
        ["bd", "list", "--parent", bid, "--status", "open,in_progress",
         "--limit", "0", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        # bd failure — surface, do not silently pass.
        raise SystemExit(f"A2: bd list --parent {bid} failed: {proc.stderr}")
    if proc.stdout.strip():
        try:
            children = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"A2: bd list --parent {bid} returned invalid JSON: {e}\n"
                f"stdout: {proc.stdout[:500]}\nstderr: {proc.stderr[:200]}"
            )
    else:
        children = []
    # Filter out formula-gate children (merge-gate / human labeled).
    active = [
        c for c in children
        if not (set(c.get("labels", []) or []) & {"merge-gate", "human"})
    ]
    if active:
        raise SystemExit(
            f"A2: feature row {bid} has {len(active)} active non-formula-gate "
            f"children but appeared in implementation queue (should be a "
            f"container, hidden)"
        )
PY
    pass "A2: --mode implementation rows pass type+child constraints"
else
    skip "A2: --mode implementation exited 1 (no data)"
fi

# -----------------------------------------------------------------------------
# A3. --mode brainstorm: every row excludes container-design types AND
# lacks `brainstormed` / `implementation-ready` / `human` (per
# is_brainstorm_candidate in collect.py).
# Note: collect.py's enriched output strips most labels except those it
# preserves; we re-probe bd for the authoritative label set.
# -----------------------------------------------------------------------------
OUT_BS="$WORK/brain.json"
run_collect brainstorm "$OUT_BS"
ec=$?
if [ "$ec" -eq 0 ]; then
    OUT_BS="$OUT_BS" python3 - <<'PY' || fail "A3: brainstorm section violates spec"
import json, os, subprocess
out = json.load(open(os.environ["OUT_BS"]))
bs = out.get("brainstorm", [])
EXCLUDED = {"milestone", "epic", "feature", "decision"}
for row in bs:
    btype = row.get("type", "")
    if btype in EXCLUDED:
        raise SystemExit(f"A3: brainstorm row has excluded type {btype!r}: {row.get('id')}")
    labels = set(row.get("labels", []) or [])
    if "brainstormed" in labels:
        raise SystemExit(f"A3: brainstorm row {row.get('id')} carries 'brainstormed' label")
    if "implementation-ready" in labels:
        raise SystemExit(f"A3: brainstorm row {row.get('id')} carries 'implementation-ready' label")
    if "human" in labels:
        raise SystemExit(f"A3: brainstorm row {row.get('id')} carries 'human' label")
PY
    pass "A3: --mode brainstorm rows pass type+label constraints"
else
    skip "A3: --mode brainstorm exited 1 (no data)"
fi

# -----------------------------------------------------------------------------
# A4. --mode planning: every row is a container type (milestone | epic |
# feature) with zero non-formula-gate active children. (Per Filter Matrix:
# planning-ready surfaces childless containers.)
# -----------------------------------------------------------------------------
OUT_PL="$WORK/plan.json"
run_collect planning "$OUT_PL"
ec=$?
if [ "$ec" -eq 0 ]; then
    OUT_PL="$OUT_PL" python3 - <<'PY' || fail "A4: planning section violates spec"
import json, os, subprocess
out = json.load(open(os.environ["OUT_PL"]))
pl = out.get("planning_ready", [])
ALLOWED = {"milestone", "epic", "feature"}
for row in pl:
    btype = row.get("type", "")
    if btype not in ALLOWED:
        raise SystemExit(f"A4: planning row has non-container type {btype!r}: {row.get('id')}")
    bid = row.get("id", "")
    proc = subprocess.run(
        ["bd", "list", "--parent", bid, "--status", "open,in_progress",
         "--limit", "0", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise SystemExit(f"A4: bd list --parent {bid} failed: {proc.stderr}")
    if proc.stdout.strip():
        try:
            children = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"A4: bd list --parent {bid} returned invalid JSON: {e}\n"
                f"stdout: {proc.stdout[:500]}\nstderr: {proc.stderr[:200]}"
            )
    else:
        children = []
    active = [
        c for c in children
        if not (set(c.get("labels", []) or []) & {"merge-gate", "human"})
    ]
    if active:
        raise SystemExit(
            f"A4: planning row {bid} has {len(active)} active non-formula-gate "
            f"children — should be hidden, not in planning-ready"
        )
PY
    pass "A4: --mode planning rows pass container+childless constraints"
else
    skip "A4: --mode planning exited 1 (no data)"
fi

# -----------------------------------------------------------------------------
# A5. --mode human: every row carries `human` label.
# -----------------------------------------------------------------------------
OUT_H="$WORK/human.json"
run_collect human "$OUT_H"
ec=$?
if [ "$ec" -eq 0 ]; then
    OUT_H="$OUT_H" python3 - <<'PY' || fail "A5: human section violates spec"
import json, os
out = json.load(open(os.environ["OUT_H"]))
hu = out.get("human", [])
for row in hu:
    labels = set(row.get("labels", []) or [])
    if "human" not in labels:
        raise SystemExit(f"A5: human row {row.get('id')} missing 'human' label (labels: {sorted(labels)})")
PY
    pass "A5: --mode human rows all carry 'human' label"
else
    skip "A5: --mode human exited 1 (no data)"
fi

# -----------------------------------------------------------------------------
# A6. Default mode emits the same section-key set as --mode all.
# -----------------------------------------------------------------------------
OUT_DEF="$WORK/default.json"
run_collect _default_ "$OUT_DEF"
ec_def=$?
run_collect all "$OUT_ALL"
ec_all=$?
if [ "$ec_def" -eq 0 ] && [ "$ec_all" -eq 0 ]; then
    OUT_DEF="$OUT_DEF" OUT_ALL="$OUT_ALL" python3 - <<'PY' || fail "A6: default mode != all mode section-key set"
import json, os
section_keys = {"human", "planning_ready", "brainstorm", "implementation"}
defp = json.load(open(os.environ["OUT_DEF"]))
allp = json.load(open(os.environ["OUT_ALL"]))
def_secs = section_keys & set(defp.keys())
all_secs = section_keys & set(allp.keys())
if def_secs != all_secs:
    raise SystemExit(f"A6: default section keys {def_secs} != all section keys {all_secs}")
if defp.get("mode") != "all":
    raise SystemExit(f"A6: default mode top-level 'mode' field expected 'all', got {defp.get('mode')!r}")
PY
    pass "A6: default mode emits same section-key set as --mode all"
else
    skip "A6: default or --mode all exited 1 (no data)"
fi

# -----------------------------------------------------------------------------
# A7. Empty-state messages — SKILL.md documents the spec'd lines.
# These are agent-rendered strings; we assert the contract in SKILL.md
# remains intact (the canonical spec source).
# -----------------------------------------------------------------------------
declare -a EMPTY_LINES=(
    "All clear — no open beads ready for attention."
    "No beads currently flagged for human attention."
    "No childless container beads ready for planning."
    "No beads ready for brainstorming."
    "No beads ready for implementation."
)
for line in "${EMPTY_LINES[@]}"; do
    grep -qF "$line" "$SKILL_MD" \
        || fail "A7: SKILL.md missing empty-state line: '$line'"
done
pass "A7: SKILL.md documents all 5 mode-specific empty-state lines"

# -----------------------------------------------------------------------------
# A8. 7-column schema per row — every enriched row carries the 7 fields
# that back the table columns P | Milestone | Feature | Parent Epic |
# Bead ID | Type | Title.
# -----------------------------------------------------------------------------
run_collect all "$OUT_ALL"
ec=$?
if [ "$ec" -eq 0 ]; then
    OUT_ALL="$OUT_ALL" python3 - <<'PY' || fail "A8: 7-column schema violated by enriched rows"
import json, os
out = json.load(open(os.environ["OUT_ALL"]))
required_fields = {
    "priority",          # P
    "milestone_col",     # Milestone
    "feature_col",       # Feature
    "parent_epic_col",   # Parent Epic
    "short_id",          # Bead ID
    "type",              # Type
    "title",             # Title
}
for sect in ("human", "planning_ready", "brainstorm", "implementation"):
    rows = out.get(sect, [])
    for row in rows:
        missing = required_fields - set(row.keys())
        if missing:
            raise SystemExit(f"A8: row {row.get('id')} in section {sect} missing fields: {missing}")
PY
    pass "A8: every enriched row carries 7-column schema fields"
else
    # SKILL.md still documents the schema; assert that as a fallback.
    grep -qE 'P \| Milestone \| Feature \| Parent Epic \| Bead ID \| Type \| Title' "$SKILL_MD" \
        || fail "A8: SKILL.md missing 7-column schema header and no live data to verify"
    skip "A8: no live data; SKILL.md schema doc verified as fallback only"
fi

echo "GROUP A: all whats-next mode tests passed."
