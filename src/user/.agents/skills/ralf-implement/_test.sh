#!/usr/bin/env bash
# Red-phase tests for bead agents-config-abn9.10:
#   "Update RALF skills + formula prose for worker-report-v1 and Scheme A renames"
#
# These tests are expected to FAIL against the current tree state because:
#   * ralf-implement/ still carries the OLD prompt-template filenames
#     (implementer-prompt.md, fresh-eyes-prompt.md, foreign-eyes-prompt.md,
#     foreign-agent-prompt.md) and the new Scheme A filenames do not yet exist.
#   * SKILL.md has no worker-report-v1, subagent_type, convergence predicate,
#     or worker-audit policy language yet.
#   * implement-feature.formula.toml / fix-bug.formula.toml do not yet carry
#     the header pointer comment or the `subagent_type: tdd-green-team` arg.
#
# Pattern follows the dep-health-check skill's _test.sh (pass/fail helpers,
# grep_in, grep_in_fixed, grep_not_in, require_file).

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
# HERE = src/user/.agents/skills/ralf-implement; repo root is five levels up.
REPO_ROOT="$(cd "$HERE/../../../../.." && pwd)"

SKILL_DIR="$REPO_ROOT/src/user/.agents/skills/ralf-implement"
SKILL_MD="$SKILL_DIR/SKILL.md"

# New (Scheme A) template files — these MUST exist after implementation.
NEW_IMPLEMENTER="$SKILL_DIR/subagent-implementer.md"
NEW_FRESH_EYES="$SKILL_DIR/subagent-fresh-eyes.md"
NEW_FOREIGN_CYCLE="$SKILL_DIR/subagent-foreign-cycle.md"
NEW_FOREIGN_CLI="$SKILL_DIR/foreign-cli-instructions.md"

# Old (pre-rename) template files — these MUST NOT exist after implementation.
OLD_IMPLEMENTER="$SKILL_DIR/implementer-prompt.md"
OLD_FRESH_EYES="$SKILL_DIR/fresh-eyes-prompt.md"
OLD_FOREIGN_EYES="$SKILL_DIR/foreign-eyes-prompt.md"
OLD_FOREIGN_AGENT="$SKILL_DIR/foreign-agent-prompt.md"

FORMULA_IMPL="$REPO_ROOT/src/plugins/beads/.beads/formulas/implement-feature.formula.toml"
FORMULA_FIX="$REPO_ROOT/src/plugins/beads/.beads/formulas/fix-bug.formula.toml"

BEAD_IMPLEMENTOR="$REPO_ROOT/src/plugins/beads/.agents/agents/bead-implementor.md"

FAIL=0

# ----- helpers -------------------------------------------------------------

pass() { echo "  ok: $1"; }

fail() {
  echo "  FAIL: $1"
  if [ "${2:-}" != "" ]; then
    echo "        $2"
  fi
  FAIL=1
}

require_file() {
  if [ -f "$1" ]; then
    pass "$2 exists ($1)"
    return 0
  fi
  fail "$2 missing" "expected file: $1"
  return 1
}

require_no_file() {
  if [ ! -e "$1" ]; then
    pass "$2 absent ($1)"
    return 0
  fi
  fail "$2 should NOT exist" "found: $1"
  return 1
}

# grep_in <file> <ERE pattern> <label>
grep_in() {
  local file="$1" pat="$2" lab="$3"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  if grep -Eq -- "$pat" "$file"; then
    pass "$lab"
    return 0
  fi
  fail "$lab" "pattern not found in $file: $pat"
  return 1
}

# grep_in_fixed <file> <fixed-string> <label>
grep_in_fixed() {
  local file="$1" pat="$2" lab="$3"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  if grep -Fq -- "$pat" "$file"; then
    pass "$lab"
    return 0
  fi
  fail "$lab" "string not found in $file: $pat"
  return 1
}

# grep_not_in <file> <fixed-string> <label>
grep_not_in() {
  local file="$1" pat="$2" lab="$3"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  if grep -Fq -- "$pat" "$file"; then
    fail "$lab" "forbidden string present in $file: $pat"
    return 1
  fi
  pass "$lab"
  return 0
}

# ===========================================================================
# AC9 / AC16 — Filesystem rename (Scheme A): new template files MUST exist;
#              old template files MUST NOT exist on disk after the rename.
# ===========================================================================
echo "[ac9_filesystem_rename_scheme_a]"

require_file "$NEW_IMPLEMENTER"   "AC9 subagent-implementer.md present"
require_file "$NEW_FRESH_EYES"    "AC9 subagent-fresh-eyes.md present"
require_file "$NEW_FOREIGN_CYCLE" "AC9 subagent-foreign-cycle.md present"
require_file "$NEW_FOREIGN_CLI"   "AC9 foreign-cli-instructions.md present"

require_no_file "$OLD_IMPLEMENTER"    "AC9 implementer-prompt.md removed"
require_no_file "$OLD_FRESH_EYES"     "AC9 fresh-eyes-prompt.md removed"
require_no_file "$OLD_FOREIGN_EYES"   "AC9 foreign-eyes-prompt.md removed"
require_no_file "$OLD_FOREIGN_AGENT"  "AC9 foreign-agent-prompt.md removed"

# ===========================================================================
# AC1 — SKILL.md consumes worker-report-v1: evidence blocks + derived gate
#       roll-up; dispatches inner doer via Agent tool with required
#       subagent_type; references implement-bead §4 per-dispatch primitive;
#       synthesizes status:failed on crash or malformed worker output.
# ===========================================================================
echo "[ac1_worker_report_v1_consumption]"

require_file "$SKILL_MD" "AC1 ralf-implement SKILL.md"

grep_in_fixed "$SKILL_MD" "worker-report-v1" \
  "AC1 SKILL.md references worker-report-v1"
grep_in "$SKILL_MD" "(evidence block|evidence\\.tests|evidence sub-?block)" \
  "AC1 SKILL.md mentions worker-report-v1 evidence blocks"
grep_in "$SKILL_MD" "(derived gate|gate roll.?up|derived.gate roll.?up)" \
  "AC1 SKILL.md mentions derived gate roll-up"
grep_in_fixed "$SKILL_MD" "Agent tool" \
  "AC1 SKILL.md dispatches inner doer via Agent tool"
grep_in_fixed "$SKILL_MD" "subagent_type" \
  "AC1 SKILL.md requires subagent_type on dispatch"
grep_in "$SKILL_MD" "implement-bead/SKILL\\.md.*(§4|section 4|per.?dispatch)" \
  "AC1 SKILL.md references implement-bead/SKILL.md §4 per-dispatch primitive"
grep_in "$SKILL_MD" "(synthesi[sz]e|synthesized).*status.*failed" \
  "AC1 SKILL.md synthesizes status:failed on crash/malformed output"
grep_in "$SKILL_MD" "(crash|malformed)" \
  "AC1 SKILL.md cites crash/malformed-output trigger for synthesis"

# ===========================================================================
# AC2 — Interactive subagent_type prompt offers tdd-green-team + general-purpose
#       ONLY; tdd-red-team and bug-diagnoser NOT offered. User declining both
#       aborts with diagnostic. Non-interactive (non_interactive:true OR
#       RALF_NONINTERACTIVE=1) with missing subagent_type fails fast.
# ===========================================================================
echo "[ac2_subagent_type_prompt]"

grep_in_fixed "$SKILL_MD" "tdd-green-team" \
  "AC2 SKILL.md offers tdd-green-team as prompt option"
grep_in_fixed "$SKILL_MD" "general-purpose" \
  "AC2 SKILL.md offers general-purpose as prompt option"

# tdd-red-team and bug-diagnoser MUST NOT be offered as prompt options. The
# names may appear elsewhere (e.g. in the worker-audit-* documentation), so
# the prohibition is on the prompt-option list itself — we test that the
# SKILL.md contains an explicit "not offered" / "excluded" statement.
grep_in "$SKILL_MD" "(tdd-red-team).*(not offered|excluded|NOT.*offer|do not offer|are NOT offered)" \
  "AC2 SKILL.md states tdd-red-team is NOT offered as a prompt option"
grep_in "$SKILL_MD" "(bug-diagnoser).*(not offered|excluded|NOT.*offer|do not offer|are NOT offered)" \
  "AC2 SKILL.md states bug-diagnoser is NOT offered as a prompt option"

grep_in "$SKILL_MD" "(decline|declining).*(abort|diagnostic)" \
  "AC2 SKILL.md aborts with diagnostic when user declines both prompt options"

grep_in_fixed "$SKILL_MD" "non_interactive" \
  "AC2 SKILL.md documents non_interactive caller argument"
grep_in_fixed "$SKILL_MD" "RALF_NONINTERACTIVE" \
  "AC2 SKILL.md documents RALF_NONINTERACTIVE env var"
grep_in "$SKILL_MD" "(fail.?fast|fails fast|fail fast)" \
  "AC2 SKILL.md non-interactive missing-subagent_type fails fast"

# ===========================================================================
# AC3 — worker-audit-<agent-name>[-iter<N>] label policy documented:
#       applies only to named workers (tdd-red-team, tdd-green-team,
#       bug-diagnoser); general-purpose + non-worker doers SHOULD NOT carry
#       worker-audit-*. Filed as upstream agents-config-go1w.
# ===========================================================================
echo "[ac3_worker_audit_label_policy]"

grep_in_fixed "$SKILL_MD" "worker-audit-" \
  "AC3 SKILL.md documents worker-audit-<agent-name> label policy"
grep_in "$SKILL_MD" "worker-audit.*iter" \
  "AC3 SKILL.md documents -iter<N> suffix on worker-audit labels"
grep_in "$SKILL_MD" "Audit-label scope" \
  "AC3 SKILL.md references implement-bead Audit-label scope"
grep_in_fixed "$SKILL_MD" "general-purpose" \
  "AC3 SKILL.md mentions general-purpose in worker-audit policy"
grep_in_fixed "$SKILL_MD" "agents-config-go1w" \
  "AC3 SKILL.md cites upstream tracking item agents-config-go1w"

# ===========================================================================
# AC4 — Explicit convergence predicate enumerates BOTH status and derived-gate
#       signals; PASS_WITH_RESERVATIONS / FAIL at cycle cap defined; R1.4.1
#       extends synthesis path for malformed evidence sub-blocks.
# ===========================================================================
echo "[ac4_convergence_predicate]"

grep_in "$SKILL_MD" "(convergence predicate|convergence candidate)" \
  "AC4 SKILL.md uses 'convergence predicate' / 'convergence candidate' terminology"
grep_in "$SKILL_MD" "status=failed.*(NOT.*convergence|not a convergence)" \
  "AC4 SKILL.md: status=failed is NOT a convergence candidate"
grep_in "$SKILL_MD" "status=complete.*gate=pass" \
  "AC4 SKILL.md: status=complete + gate=pass branch documented"
grep_in "$SKILL_MD" "status=complete.*gate=n/a|gate=n/a.*status=complete" \
  "AC4 SKILL.md: status=complete + gate=n/a branch documented"
grep_in "$SKILL_MD" "gate=(fail|partial)|gate.*(fail.*partial|partial.*fail)" \
  "AC4 SKILL.md: gate=fail|partial branch documented (iterate)"
grep_in_fixed "$SKILL_MD" "PASS_WITH_RESERVATIONS" \
  "AC4 SKILL.md retains PASS_WITH_RESERVATIONS at cycle cap"
grep_in "$SKILL_MD" "fresh.?eyes.*(decide|alone)" \
  "AC4 SKILL.md: fresh-eyes alone decides convergence"
grep_in "$SKILL_MD" "malformed.*evidence.*(sub.?block|tests)" \
  "AC4 SKILL.md: malformed evidence sub-blocks → synthesized status=failed (R1.4.1)"
grep_in_fixed "$SKILL_MD" "Worker emitted malformed report" \
  "AC4 SKILL.md documents canonical escalations[].reason text"

# ===========================================================================
# AC5 — Per-cycle loop: quality-reviewer + simplify run ONLY on convergence
#       candidates; simplify advisory-only with measurable re-run trigger;
#       N/A case when evidence.tests.command is empty; verify-checklist
#       removed as per-iteration step. Cycle cap = 3, sequence
#       Codex/Gemini/pure-Claude; degradation cascade.
# ===========================================================================
echo "[ac5_per_cycle_loop]"

grep_in "$SKILL_MD" "quality-reviewer.*(only|ONLY).*convergence candidate" \
  "AC5 SKILL.md: quality-reviewer runs only on convergence candidates"
grep_in "$SKILL_MD" "simplify.*(only|ONLY).*convergence candidate" \
  "AC5 SKILL.md: simplify runs only on convergence candidates"

grep_in "$SKILL_MD" "simplify.*advisory" \
  "AC5 SKILL.md: simplify is advisory-only"
grep_in_fixed "$SKILL_MD" "evidence.tests.command" \
  "AC5 SKILL.md: simplify re-runs evidence.tests.command after edits"
grep_in "$SKILL_MD" "(re-?run|rerun).*evidence\\.tests\\.command" \
  "AC5 SKILL.md: simplify re-run trigger language"
grep_in "$SKILL_MD" "(previously.?passing|previously passing).*(failing|fails)" \
  "AC5 SKILL.md: previously-passing test now failing → reject simplify output"
grep_in "$SKILL_MD" "N/A.*(case|branch)|evidence\\.tests\\.command.*(empty|absent)" \
  "AC5 SKILL.md: N/A case (empty/absent evidence.tests.command) documented"

# verify-checklist must NOT be listed as a per-iteration step. The string may
# survive in historical-context prose, but not as a numbered step. We test the
# narrower invariant: SKILL.md must include language explicitly removing it.
grep_in "$SKILL_MD" "verify-checklist.*(removed|no longer)" \
  "AC5 SKILL.md states verify-checklist removed as per-iteration step"

grep_in_fixed "$SKILL_MD" "RALF_IMPLEMENT_DEFAULT_CYCLES=3" \
  "AC5 SKILL.md retains default cycle cap = 3"
grep_in "$SKILL_MD" "cycle 1.*Codex.*gpt-5\\.5|Codex.*gpt-5\\.5.*cycle 1" \
  "AC5 SKILL.md: cycle 1 = Codex (gpt-5.5)"
grep_in "$SKILL_MD" "cycle 2.*Gemini|Gemini.*cycle 2" \
  "AC5 SKILL.md: cycle 2 = Gemini"
grep_in "$SKILL_MD" "cycle 3.*pure.?Claude|pure.?Claude.*cycle 3" \
  "AC5 SKILL.md: cycle 3+ = pure-Claude"

grep_in "$SKILL_MD" "Codex.*degraded.*Gemini.*fallback|degradation cascade" \
  "AC5 SKILL.md documents degradation cascade Codex→Gemini→pure-Claude"
grep_in "$SKILL_MD" "evidence.?store" \
  "AC5 SKILL.md mentions evidence-store canonicalization"

# ===========================================================================
# AC6 — Iteration-routing references each prompt template by concrete relative
#       path AS DOCUMENTATION REFERENCES (new Scheme A names).
# ===========================================================================
echo "[ac6_template_path_references]"

grep_in_fixed "$SKILL_MD" "./subagent-implementer.md" \
  "AC6 SKILL.md references ./subagent-implementer.md"
grep_in_fixed "$SKILL_MD" "./subagent-fresh-eyes.md" \
  "AC6 SKILL.md references ./subagent-fresh-eyes.md"
grep_in_fixed "$SKILL_MD" "./subagent-foreign-cycle.md" \
  "AC6 SKILL.md references ./subagent-foreign-cycle.md"
grep_in_fixed "$SKILL_MD" "./foreign-cli-instructions.md" \
  "AC6 SKILL.md references ./foreign-cli-instructions.md"

grep_in "$SKILL_MD" "(codex-companion\\.mjs|gemini).*(stdin|pipe)" \
  "AC6 SKILL.md notes foreign-cli-instructions.md is piped to codex/gemini on stdin"

# ===========================================================================
# AC7 — ralf:required label semantics documented (this skill is canonical home).
# ===========================================================================
echo "[ac7_ralf_required_label_canonical]"

grep_in_fixed "$SKILL_MD" "ralf:required" \
  "AC7 SKILL.md documents ralf:required label"
grep_in "$SKILL_MD" "(canonical|canonical home).*ralf:required|ralf:required.*(canonical|canonical home)" \
  "AC7 SKILL.md asserts canonical-home status for ralf:required"

# ===========================================================================
# AC8 — Implementation ordering: R3.1 (ralf-implement rename) is in scope;
#       R3.2 (ralf-review rename) and R2.3 (new ralf-review files) are deferred
#       to agents-config-abn9.13. SKILL.md must note the deferral so future
#       readers do not assume ralf-review/ was renamed in this work.
# ===========================================================================
echo "[ac8_ralf_review_deferred]"

grep_in_fixed "$SKILL_MD" "agents-config-abn9.13" \
  "AC8 SKILL.md cites agents-config-abn9.13 as ralf-review deferral target"
grep_in "$SKILL_MD" "ralf-review.*deferred|deferred.*ralf-review" \
  "AC8 SKILL.md explicitly defers ralf-review rename"

# ===========================================================================
# AC10 — After rename, no active template/skill/formula file references the
#        four OLD template filenames. Intra-template references updated.
#        Excludes _test.sh (this file) and docs/specs/*-design.md.
# ===========================================================================
echo "[ac10_no_old_filename_references]"

# Search src/ for old filenames. The test file itself MUST be excluded, as it
# legitimately names the old files for "absent on disk" assertions. The dated
# design-doc pattern under docs/specs/ is also excluded (R5.1/R5.2 carve-out).
# Active templates, skill files, and formula files are what's tested.
check_old_filename_refs() {
  local old="$1" label="$2"
  local hits
  hits="$( ( grep -r --include='*.md' --include='*.toml' -l -F -- "$old" "$REPO_ROOT/src" 2>/dev/null \
              | grep -v -F "$HERE/_test.sh" \
              | grep -Ev '^.*/docs/specs/[0-9]{4}-[0-9]{2}-[0-9]{2}-.*-design\.md$' \
              | grep -v -F "$REPO_ROOT/src/user/.agents/skills/ralf-review" ) || true )"
  if [ -z "$hits" ]; then
    pass "$label"
  else
    fail "$label" "still referenced in:$(printf '\n%s' "$hits")"
  fi
}

check_old_filename_refs "implementer-prompt.md"    "AC10 no refs to implementer-prompt.md"
check_old_filename_refs "fresh-eyes-prompt.md"     "AC10 no refs to fresh-eyes-prompt.md"
check_old_filename_refs "foreign-eyes-prompt.md"   "AC10 no refs to foreign-eyes-prompt.md"
check_old_filename_refs "foreign-agent-prompt.md"  "AC10 no refs to foreign-agent-prompt.md"

# Intra-template reference update: subagent-foreign-cycle.md's body must
# reference ./foreign-cli-instructions.md, NOT ./foreign-agent-prompt.md.
if [ -f "$NEW_FOREIGN_CYCLE" ]; then
  grep_in_fixed "$NEW_FOREIGN_CYCLE" "./foreign-cli-instructions.md" \
    "AC10 subagent-foreign-cycle.md references ./foreign-cli-instructions.md"
  grep_not_in   "$NEW_FOREIGN_CYCLE" "./foreign-agent-prompt.md" \
    "AC10 subagent-foreign-cycle.md does NOT reference old ./foreign-agent-prompt.md"
fi

# ===========================================================================
# AC11 — Both formula files carry header pointer comment to ralf-implement
#        SKILL.md as the canonical home for ralf:required semantics.
# ===========================================================================
echo "[ac11_formula_header_pointer_comment]"

POINTER='# ralf:required label semantics: see src/user/.agents/skills/ralf-implement/SKILL.md'

grep_in_fixed "$FORMULA_IMPL" "$POINTER" \
  "AC11 implement-feature.formula.toml carries ralf:required pointer comment"
grep_in_fixed "$FORMULA_FIX"  "$POINTER" \
  "AC11 fix-bug.formula.toml carries ralf:required pointer comment"

# ===========================================================================
# AC12 — Both formula files' green-loop dispatch prose includes
#        `subagent_type: tdd-green-team` in the ralf-implement invocation.
#        fix-bug must preserve the root-cause-note argument.
# ===========================================================================
echo "[ac12_subagent_type_in_dispatch_prose]"

grep_in_fixed "$FORMULA_IMPL" "subagent_type: tdd-green-team" \
  "AC12 implement-feature.formula.toml passes subagent_type: tdd-green-team to ralf-implement"
grep_in_fixed "$FORMULA_FIX"  "subagent_type: tdd-green-team" \
  "AC12 fix-bug.formula.toml passes subagent_type: tdd-green-team to ralf-implement"

# fix-bug must continue to pass the root-cause-note argument.
grep_in_fixed "$FORMULA_FIX" "root-cause-note" \
  "AC12 fix-bug.formula.toml preserves root-cause-note argument"

# ===========================================================================
# AC13 — bead-implementor.md regression check: must NOT exist at the legacy
#        plugin path (delivered by PR #66).
# ===========================================================================
echo "[ac13_bead_implementor_absent]"

require_no_file "$BEAD_IMPLEMENTOR" "AC13 bead-implementor.md (legacy plugin agent) absent"

# ===========================================================================
# AC14 — Repo-wide bead-implementor invariant grep returns zero matches,
#        excluding this test file.
# ===========================================================================
echo "[ac14_bead_implementor_invariant_grep]"

HITS="$( ( grep -r --include='*.md' -l 'bead-implementor' "$REPO_ROOT/src" 2>/dev/null \
            | grep -v -F "$HERE/_test.sh" ) || true )"
if [ -z "$HITS" ]; then
  pass "AC14 no 'bead-implementor' references remain in src/*.md (excluding _test.sh)"
else
  fail "AC14 no 'bead-implementor' references remain in src/*.md" \
    "still present in:$(printf '\n%s' "$HITS")"
fi

# ===========================================================================
# AC15 — Old-filename grep exclusion-list invariants:
#        * docs/specs/YYYY-MM-DD-*-design.md is excluded
#        * src/user/.agents/skills/ralf-review/ is excluded
#        Together with AC10's exclusion shape, this confirms the grep
#        framework is wired correctly.
# ===========================================================================
echo "[ac15_exclusion_list_invariants]"

# Confirm the dated-design-doc exclusion regex matches at least one real path
# in this repo (sanity probe on the exclusion expression itself), then run a
# full sweep with the exclusions to confirm zero leftover hits.
DESIGN_DOCS="$( ( ls "$REPO_ROOT"/docs/specs/2026-*-design.md 2>/dev/null ) || true )"
if [ -n "$DESIGN_DOCS" ]; then
  pass "AC15 dated design-doc exclusion target exists in repo (regex is meaningful)"
else
  fail "AC15 dated design-doc exclusion target exists in repo" \
    "no docs/specs/YYYY-MM-DD-*-design.md present; cannot validate exclusion"
fi

# Full sweep with exclusions; collect any non-excluded hit for any of the four
# old filenames in a single pass so the diagnostic is informative.
ALL_OLD_HITS=""
for old in implementer-prompt.md fresh-eyes-prompt.md foreign-eyes-prompt.md foreign-agent-prompt.md; do
  h="$( ( grep -r --include='*.md' --include='*.toml' -l -F -- "$old" "$REPO_ROOT/src" 2>/dev/null \
            | grep -v -F "$HERE/_test.sh" \
            | grep -Ev '^.*/docs/specs/[0-9]{4}-[0-9]{2}-[0-9]{2}-.*-design\.md$' \
            | grep -v -F "$REPO_ROOT/src/user/.agents/skills/ralf-review" ) || true )"
  if [ -n "$h" ]; then
    ALL_OLD_HITS="$ALL_OLD_HITS
$old:
$h"
  fi
done
if [ -z "$ALL_OLD_HITS" ]; then
  pass "AC15 old-filename sweep with exclusion list returns zero hits"
else
  fail "AC15 old-filename sweep with exclusion list returns zero hits" \
    "leftover hits:$ALL_OLD_HITS"
fi

# ===========================================================================
# AC16 — Docs-only repo validation (filesystem rename invariants summary).
#        Largely covered by AC9 + AC6 + AC10 + AC14 + AC15 above; this section
#        adds the path-reference sweep for the new Scheme A names inside
#        SKILL.md and intra-template references.
# ===========================================================================
echo "[ac16_new_name_path_references]"

# SKILL.md references the new names (also covered by AC6, but kept here for
# the AC16 invariant-summary readability).
for new in subagent-implementer.md subagent-fresh-eyes.md subagent-foreign-cycle.md foreign-cli-instructions.md; do
  grep_in_fixed "$SKILL_MD" "$new" \
    "AC16 SKILL.md references new template name '$new'"
done

# ----- final --------------------------------------------------------------
if [ "$FAIL" -ne 0 ]; then
  echo "[ralf-implement/_test.sh] OVERALL: FAIL"
  exit 1
fi
echo "[ralf-implement/_test.sh] OVERALL: PASS"
exit 0
