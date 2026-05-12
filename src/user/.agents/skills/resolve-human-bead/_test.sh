#!/usr/bin/env bash
# Red-phase tests for bead agents-config-7bk.13:
#   "resolve-human-bead skill + HEP rollout"
#
# These tests fail until the resolve-human-bead skill exists, the slash
# command is in place, the start-bead/implement-bead/run-queue surfaces are
# rolled over to HEP, and the HEP citations land in beads.md.
#
# Discovery: this file sits in src/user/.agents/skills/ so the project test
# runner picks it up, but every assertion targets paths under
# src/plugins/beads/. The shared "resolve-human-bead" entry under .agents
# is the home for these contract tests; the actual SKILL.md ships in the
# beads plugin.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
# HERE = src/user/.agents/skills/resolve-human-bead; repo root is five
# levels up (resolve-human-bead -> skills -> .agents -> user -> src -> root).
REPO_ROOT="$(cd "$HERE/../../../../.." && pwd)"

SKILL_MD="$REPO_ROOT/src/plugins/beads/.agents/skills/resolve-human-bead/SKILL.md"
CMD_MD="$REPO_ROOT/src/plugins/beads/.claude/commands/resolve-human-bead.md"
START_MD="$REPO_ROOT/src/plugins/beads/.agents/skills/start-bead/SKILL.md"
IMPL_MD="$REPO_ROOT/src/plugins/beads/.agents/skills/implement-bead/SKILL.md"
RUNQUEUE_MD="$REPO_ROOT/src/plugins/beads/.agents/skills/run-queue/SKILL.md"
BEADS_RULES_MD="$REPO_ROOT/src/plugins/beads/.claude/rules/beads.md"
ARCH_DOC="$REPO_ROOT/docs/specs/bead-pipeline-architecture.md"

FAIL=0

# ----- helpers -------------------------------------------------------------

# pass <label>
pass() { echo "  ok: $1"; }

# fail <label> [detail]
fail() {
  echo "  FAIL: $1"
  if [ "${2:-}" != "" ]; then
    echo "        $2"
  fi
  FAIL=1
}

# require_file <path> <label>
require_file() {
  if [ -f "$1" ]; then
    pass "$2 exists ($1)"
    return 0
  fi
  fail "$2 missing" "expected file: $1"
  return 1
}

# grep_in <file> <pattern> <label>     (ERE)
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

# section_has <file> <section-header-pattern> <body-pattern> <label>
# Verifies <body-pattern> appears AFTER the first match of <section-header-pattern>.
section_has() {
  local file="$1" header="$2" body="$3" lab="$4"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  awk -v header="$header" -v body="$body" '
    BEGIN { in_section=0 }
    {
      if ($0 ~ header) { in_section=1; next }
      if (in_section && $0 ~ body) { found=1; exit }
    }
    END { exit found ? 0 : 1 }
  ' "$file"
  if [ $? -eq 0 ]; then
    pass "$lab"
    return 0
  fi
  fail "$lab" "did not find body /$body/ after header /$header/ in $file"
  return 1
}

# order_check <file> <first-pattern> <second-pattern> <label>
# Verifies <first-pattern> appears at or before the line of <second-pattern>.
order_check() {
  local file="$1" first="$2" second="$3" lab="$4"
  if [ ! -f "$file" ]; then
    fail "$lab" "file not found: $file"
    return 1
  fi
  local fl sl
  fl=$(grep -nE -- "$first" "$file" | head -n1 | cut -d: -f1 || true)
  sl=$(grep -nE -- "$second" "$file" | head -n1 | cut -d: -f1 || true)
  if [ -z "$fl" ]; then
    fail "$lab" "first pattern not found: $first"
    return 1
  fi
  if [ -z "$sl" ]; then
    fail "$lab" "second pattern not found: $second"
    return 1
  fi
  if [ "$fl" -le "$sl" ]; then
    pass "$lab (first@${fl} <= second@${sl})"
    return 0
  fi
  fail "$lab" "ordering wrong: /$first/ at line $fl is AFTER /$second/ at line $sl"
  return 1
}

# ===========================================================================
# AC1 — SKILL.md exists with class-detection branches, canonical probe,
#       destructive-action enumeration, Red Flags prohibiting bare primitives.
# ===========================================================================
echo "[ac1_skill_md_contract]"

require_file "$SKILL_MD" "AC1 SKILL.md"

# Class-detection branches — six per description, but AC1 in the bead's AC
# field names five required ones. Test the five from the AC field, plus
# the merge-gate sub-class which is the highest-priority detection per
# the design (matches the seven-scenario branch list in the description).
grep_in_fixed "$SKILL_MD" "HEP escalation"          "AC1 branch: HEP escalation"
grep_in_fixed "$SKILL_MD" "[h] follow-up"           "AC1 branch: [h] follow-up"
grep_in_fixed "$SKILL_MD" "orphan"                  "AC1 branch: orphan"
grep_in       "$SKILL_MD" "([iI]nconsistent.?state|[Rr]epair.?branch)" "AC1 branch: inconsistent-state/repair"
grep_in_fixed "$SKILL_MD" "source-bead pivot"       "AC1 branch: source-bead pivot"
grep_in_fixed "$SKILL_MD" "merge-gate"              "AC1 branch: merge-gate hand-off sub-class"

# Canonical detection probe (jq) — the spec mandates an inline, verified probe.
# Probe shape verified live against bd show --json: dep objects expose
# `dependency_type` (not `.type`) and `.id` (not `.issue_id`). The previous
# `.type` / `.issue_id` shape is bd ready --json's wire, not bd show's.
grep_in_fixed "$SKILL_MD" 'bd show'                              "AC1 probe: uses bd show"
grep_in_fixed "$SKILL_MD" 'dependencies'                         "AC1 probe: references dependencies field"
grep_in_fixed "$SKILL_MD" 'select(.dependency_type=="blocks")'   "AC1 probe: verified jq path .dependency_type==blocks"
grep_in_fixed "$SKILL_MD" 'bd label list'                        "AC1 probe: bd label list used"
grep_in_fixed "$SKILL_MD" 'index("human")'                       "AC1 probe: jq index(\"human\") check"
# Forbid the broken bd-ready-shape probe text in the canonical bd-show probe.
# Match the probe-shape composition rather than bare field names — this
# allows contrast prose ("the .type / .issue_id shape is bd ready --json's")
# while still rejecting any live probe text that uses the wrong shape.
grep_not_in "$SKILL_MD" 'select(.type=="blocks")' \
  "AC1 probe: does NOT use the broken .type==blocks shape (that is bd ready --json's shape, not bd show --json's)"
grep_not_in "$SKILL_MD" '| .issue_id' \
  "AC1 probe: does NOT pipe to broken .issue_id field (bd show --json deps expose .id)"

# Destructive-action enumeration — three actions per spec.
grep_in_fixed "$SKILL_MD" "bd mol squash"     "AC1 destructive: bd mol squash listed"
grep_in_fixed "$SKILL_MD" "bd human dismiss"  "AC1 destructive: bd human dismiss listed"
grep_in       "$SKILL_MD" "bd close <source-id>|bd close \\\$?source" "AC1 destructive: bd close on source listed"

# Red Flags section explicitly prohibits bare primitives.
section_has "$SKILL_MD" "^#+ +.*[Rr]ed [Ff]lags" "bd label remove .* human"   "AC1 Red Flags: bare bd label remove human prohibited"
section_has "$SKILL_MD" "^#+ +.*[Rr]ed [Ff]lags" "bd close"                   "AC1 Red Flags: bare bd close on human-labeled bead prohibited"

# ===========================================================================
# AC2 — Slash-command wrapper exists; no-op message on no-human-state targets.
# ===========================================================================
echo "[ac2_command_md_contract]"

require_file "$CMD_MD" "AC2 command file"
grep_in_fixed "$CMD_MD" '$ARGUMENTS' "AC2 command: passes \$ARGUMENTS to skill"
# No-op message MUST be explicit one-liner per spec.
grep_in "$CMD_MD" "No human escalation found" "AC2 command: documents no-op one-liner"
# Must not auto-create human beads in the no-op path.
grep_in "$CMD_MD" "(zero exit|exits? cleanly|exit 0)" "AC2 command: documents clean exit on no-op"

# ===========================================================================
# AC3 — Scenario A: bd human respond; description-edit BEFORE close.
# ===========================================================================
echo "[ac3_scenario_a]"

require_file "$SKILL_MD" "AC3 SKILL.md"
grep_in_fixed "$SKILL_MD" "bd human respond" "AC3 Scenario A invokes bd human respond"
# Description-edit step must appear before the close (bd human respond IS the close).
section_has "$SKILL_MD" "^#+ +.*Scenario A|^- +.*A\\." "edit.*description|description.*edit" "AC3 Scenario A documents description-edit step"
order_check "$SKILL_MD" \
  "[Dd]escription.*[Ee]dit|[Ee]dit.*source bead's? description" \
  "Scenario A.*bd human respond|A\\..*bd human respond" \
  "AC3 Scenario A: description-edit BEFORE close"

# ===========================================================================
# AC4 — Scenario B: bd create + bd dep add <source> <new> BEFORE bd human respond.
# ===========================================================================
echo "[ac4_scenario_b]"

grep_in_fixed "$SKILL_MD" "bd create"                "AC4 Scenario B invokes bd create"
grep_in       "$SKILL_MD" 'bd dep add'               "AC4 Scenario B invokes bd dep add"
order_check "$SKILL_MD" \
  "Scenario B.*bd create|B\\..*bd create|bd create .*--type task" \
  "Scenario B.*bd human respond|B\\..*bd human respond" \
  "AC4 Scenario B: bd create BEFORE bd human respond"
order_check "$SKILL_MD" \
  "Scenario B.*bd dep add|B\\..*bd dep add|bd dep add <source" \
  "Scenario B.*bd human respond|B\\..*bd human respond" \
  "AC4 Scenario B: bd dep add BEFORE bd human respond"

# ===========================================================================
# AC5 — Scenario C: ONLY bd human respond; no other state changes.
# ===========================================================================
echo "[ac5_scenario_c]"

# Scenario C should explicitly say "only" / "no other state changes".
section_has "$SKILL_MD" "Scenario C|^- +.*C\\." "ONLY|only.*bd human respond|no other state changes" \
  "AC5 Scenario C documents only-bd-human-respond"

# ===========================================================================
# AC6 — Scenario D: bd mol squash (with confirmation) BEFORE bd human respond.
# ===========================================================================
echo "[ac6_scenario_d]"

grep_in_fixed "$SKILL_MD" "bd mol squash" "AC6 Scenario D invokes bd mol squash"
section_has "$SKILL_MD" "Scenario D|^- +.*D\\." "([Cc]onfirm|confirmation|user confirmation)" \
  "AC6 Scenario D documents user confirmation for squash"
order_check "$SKILL_MD" \
  "Scenario D.*bd mol squash|D\\..*bd mol squash" \
  "Scenario D.*bd human respond|D\\..*bd human respond" \
  "AC6 Scenario D: bd mol squash BEFORE bd human respond"

# ===========================================================================
# AC7 — Scenario E: bd human dismiss AND bd close <source-id>;
#       NOT bd human respond.
# ===========================================================================
echo "[ac7_scenario_e]"

grep_in_fixed "$SKILL_MD" "bd human dismiss" "AC7 Scenario E invokes bd human dismiss"
grep_in       "$SKILL_MD" "bd close <source-id>|bd close \\\$?source" "AC7 Scenario E invokes bd close on source"
section_has "$SKILL_MD" "Scenario E|^- +.*E\\." "([Cc]onfirm|confirmation)" \
  "AC7 Scenario E documents separate confirmations"
section_has "$SKILL_MD" "Scenario E|^- +.*E\\." "(MUST NOT|must not|NOT invoke).*bd human respond" \
  "AC7 Scenario E: explicitly NOT bd human respond"

# ===========================================================================
# AC8 — Scenario F: bd label add <follow-up> verified-by-human AND plain
#       bd close; NOT bd human respond, NOT bd human dismiss.
# ===========================================================================
echo "[ac8_scenario_f]"

grep_in_fixed "$SKILL_MD" "verified-by-human"       "AC8 Scenario F applies verified-by-human label"
section_has "$SKILL_MD" "Scenario F|^- +.*F\\." "bd label add.*verified-by-human" \
  "AC8 Scenario F: bd label add verified-by-human"
section_has "$SKILL_MD" "Scenario F|^- +.*F\\." "(plain )?bd close" \
  "AC8 Scenario F: plain bd close"
section_has "$SKILL_MD" "Scenario F|^- +.*F\\." "(NOT|not).*bd human respond" \
  "AC8 Scenario F: explicitly NOT bd human respond"
section_has "$SKILL_MD" "Scenario F|^- +.*F\\." "(NOT|not).*bd human dismiss" \
  "AC8 Scenario F: explicitly NOT bd human dismiss"

# ===========================================================================
# AC9 — Multi-blocker handling: >1 open human-labeled blocker triggers
#       list-and-prompt; one per invocation.
# ===========================================================================
echo "[ac9_multi_blocker]"

grep_in "$SKILL_MD" "(multi.?blocker|multiple .*blockers|>1.*blocker|more than one.*blocker)" \
  "AC9 documents multi-blocker case"
grep_in "$SKILL_MD" "(one per invocation|one .*per invocation|resolve one)" \
  "AC9 documents one-resolved-per-invocation"
grep_in "$SKILL_MD" "(list.*prompt|prompt the user to pick|prompts user)" \
  "AC9 documents list-and-prompt UX"

# ===========================================================================
# AC10 — Inconsistent-state class: detects orphaned-escalation & stale-dep;
#        surfaces without auto-resolving; offers concrete repair actions.
# ===========================================================================
echo "[ac10_inconsistent_state]"

grep_in "$SKILL_MD" "(orphan(ed)?[- ]escalation|escalation .*orphan)" \
  "AC10 detects orphaned-escalation case"
grep_in "$SKILL_MD" "(stale.?dep|stale dep edge|dep .*still .*open|stale dependency)" \
  "AC10 detects stale-dep case"
grep_in "$SKILL_MD" "(does not auto.?resolve|do NOT silently auto.?resolve|surface.*without auto.?resolving|surfaces .*without auto)" \
  "AC10 surfaces without auto-resolving"
grep_in "$SKILL_MD" "(repair action|concrete repair|repair options?)" \
  "AC10 offers concrete repair actions"

# ===========================================================================
# AC11 — start-bead Route D AUTO-INVOKES resolve-human-bead in same session
#        via Skill tool; covers bead-itself-human OR bead-blocked-by-human.
# ===========================================================================
echo "[ac11_start_bead_route_d]"

require_file "$START_MD" "AC11 start-bead SKILL.md"
grep_in_fixed "$START_MD" "Route D"                                "AC11 Route D documented"
grep_in       "$START_MD" "(AUTO.?INVOKES?|auto.?invokes?)"        "AC11 Route D AUTO-INVOKES language"
grep_in_fixed "$START_MD" "resolve-human-bead"                     "AC11 Route D names resolve-human-bead"
grep_in       "$START_MD" "(Skill tool|via the Skill tool|via Skill)" "AC11 Route D uses Skill tool"
grep_in       "$START_MD" "(bead-itself.?human|has +.human. label)"   "AC11 Route D trigger: bead-itself-human"
grep_in       "$START_MD" "(blocked.?by.?human|human.?labeled blocker)" "AC11 Route D trigger: bead-blocked-by-human"

# AC11 also covers the HEP single-bead-human invariant for start-bead: the
# Step-2 fall-throughs (length-0 with suspected unlabeled molecule and
# length-2+ undisambiguable molecules) must NOT bare-stamp `human` on the
# source bead — they must execute the HEP escalation procedure instead.
grep_not_in "$START_MD" "bd label add <bead-id> human" \
  "AC11 start-bead no longer bare-stamps human on source bead (HEP single-bead invariant)"
grep_in "$START_MD" "(HEP|Human.?Escalation Pattern)" \
  "AC11 start-bead references HEP for Step-2 escalation"

# ===========================================================================
# AC12 — implement-bead no longer stamps human on source/step-beads; all
#        flag-human paths use HEP per beads.md HEP section + arch §5.6.
# ===========================================================================
echo "[ac12_implement_bead_hep_rollout]"

require_file "$IMPL_MD" "AC12 implement-bead SKILL.md"
# The bare-stamp patterns must be gone.
grep_not_in "$IMPL_MD" "bd label add <source-bead-id> human" \
  "AC12 implement-bead no longer stamps human on source bead"
grep_not_in "$IMPL_MD" "bd label add <step-bead-id> human" \
  "AC12 implement-bead no longer stamps human on step bead"
grep_not_in "$IMPL_MD" "stamp \`human\` on BOTH the step-bead AND source bead" \
  "AC12 implement-bead no longer documents BOTH-bead stamp"
# It MUST instead invoke the HEP escalation procedure and cite the authorities.
grep_in "$IMPL_MD" "(HEP|Human.?Escalation Pattern)" \
  "AC12 implement-bead references HEP procedure"
grep_in "$IMPL_MD" "(§5\\.6|section 5\\.6|5\\.6)" \
  "AC12 implement-bead cites arch §5.6"
grep_in "$IMPL_MD" "(beads\\.md|HEP section)" \
  "AC12 implement-bead cites beads.md HEP section"

# ===========================================================================
# AC13 — run-queue: no bare label removal advice; spec-gap escalation uses HEP.
# ===========================================================================
echo "[ac13_run_queue_hep]"

require_file "$RUNQUEUE_MD" "AC13 run-queue SKILL.md"
# The current "bd label remove <id> human" advisory must be gone.
grep_not_in "$RUNQUEUE_MD" "bd label remove <id> human" \
  "AC13 run-queue no longer advises bare bd label remove human"
# The current "bd label add <bead-id> human" spec-gap escalation must be gone.
grep_not_in "$RUNQUEUE_MD" "bd label add <bead-id> human" \
  "AC13 run-queue no longer advises bare bd label add human for spec-gap"
# HEP must be referenced as the replacement.
grep_in "$RUNQUEUE_MD" "(HEP|Human.?Escalation Pattern)" \
  "AC13 run-queue references HEP for spec-gap escalation"
grep_in "$RUNQUEUE_MD" "(§5\\.6|section 5\\.6|5\\.6)" \
  "AC13 run-queue cites arch §5.6"

# ===========================================================================
# AC14 — HEP-affected skill files cite beads.md HEP section and arch §5.6
#        as authoritative.
# ===========================================================================
echo "[ac14_authority_citations]"

for f in "$SKILL_MD" "$IMPL_MD" "$RUNQUEUE_MD" "$START_MD"; do
  base="${f##*/}"
  parent="${f%/*}"
  parent_base="${parent##*/}"
  label="$parent_base/$base"
  if [ ! -f "$f" ]; then
    fail "AC14 $label citation: arch §5.6" "file not found: $f"
    fail "AC14 $label citation: beads.md HEP" "file not found: $f"
    continue
  fi
  if grep -Eq -- "(§5\\.6|section 5\\.6|5\\.6)" "$f"; then
    pass "AC14 $label cites arch §5.6"
  else
    fail "AC14 $label cites arch §5.6" "no §5.6 reference in $f"
  fi
  if grep -Eq -- "(beads\\.md|HEP section)" "$f"; then
    pass "AC14 $label cites beads.md HEP section"
  else
    fail "AC14 $label cites beads.md HEP section" "no beads.md/HEP-section reference in $f"
  fi
done

# Sanity: the authority docs themselves must define the HEP section.
grep_in "$ARCH_DOC" "Human-Escalation Pattern" "AC14 arch doc defines Human-Escalation Pattern (§5.6)"
grep_in_fixed "$BEADS_RULES_MD" "HEP" "AC14 beads.md mentions HEP"

# ===========================================================================
# AC15 — Smoke 1 (HEP scenario C round-trip) executed; PR description
#        records actual output of fixture-recipe steps 3 and 5.
# AC16 — Smoke 2 ([h] follow-up scenario F, synthetic fixture) executed;
#        PR description records limitation and verifications.
#
# These are manual smoke tests recorded in the PR description, but we still
# require an in-tree evidence marker (e.g., docs/specs/.../smoke-evidence.md
# or NOTES.md alongside the skill) so the red-phase gate notices when the
# implementer skips them entirely.
# ===========================================================================
echo "[ac15_ac16_smoke_evidence]"

SMOKE_EVIDENCE_CANDIDATES=(
  "$REPO_ROOT/src/plugins/beads/.agents/skills/resolve-human-bead/SMOKE-EVIDENCE.md"
  "$REPO_ROOT/src/plugins/beads/.agents/skills/resolve-human-bead/smoke-evidence.md"
  "$REPO_ROOT/docs/specs/resolve-human-bead-smoke-evidence.md"
)

SMOKE_FILE=""
for cand in "${SMOKE_EVIDENCE_CANDIDATES[@]}"; do
  if [ -f "$cand" ]; then
    SMOKE_FILE="$cand"
    break
  fi
done

if [ -z "$SMOKE_FILE" ]; then
  fail "AC15/AC16 smoke-evidence file present" \
    "expected one of: ${SMOKE_EVIDENCE_CANDIDATES[*]}"
else
  pass "AC15/AC16 smoke-evidence file present: $SMOKE_FILE"
  grep_in_fixed "$SMOKE_FILE" "Smoke 1" "AC15 Smoke 1 section recorded"
  grep_in_fixed "$SMOKE_FILE" "scenario C" "AC15 Smoke 1 scenario C round-trip recorded"
  grep_in_fixed "$SMOKE_FILE" "Smoke 2" "AC16 Smoke 2 section recorded"
  grep_in       "$SMOKE_FILE" "(synthetic fixture|hand.?crafted fixture|\\[h\\] follow.?up)" \
    "AC16 Smoke 2 synthetic-fixture protocol recorded"
  grep_in       "$SMOKE_FILE" "([Ll]imitation|limitation noted)" \
    "AC16 Smoke 2 records limitation"
fi

# ----- final --------------------------------------------------------------
if [ "$FAIL" -ne 0 ]; then
  echo "[resolve-human-bead/_test.sh] OVERALL: FAIL"
  exit 1
fi
echo "[resolve-human-bead/_test.sh] OVERALL: PASS"
exit 0
