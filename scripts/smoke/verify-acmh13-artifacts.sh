#!/usr/bin/env bash
# scripts/smoke/verify-acmh13-artifacts.sh
# Mechanical AC verification for bead agents-config-acmh.13
# (Tier-2 agent cleanups: replace bead-implementor with role-named workers).
#
# Each assertion below maps to an [m]-tagged acceptance criterion.
# This script MUST fail during the red phase (before implementation), and
# pass once the green phase has produced the new agents, formulas, specs,
# and edits to existing files.
#
# Exit codes:
#   0  — all checks pass
#   1  — one or more checks failed
#
# Usage: bash scripts/smoke/verify-acmh13-artifacts.sh [REPO_ROOT]
#   REPO_ROOT defaults to two levels above this script.

# -e intentionally omitted: run every check, accumulate counts, exit at end.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

PASS=0
FAIL=0

pass() {
  echo "  PASS  $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "  FAIL  $1"
  if [ -n "${2:-}" ]; then echo "        $2"; fi
  FAIL=$((FAIL + 1))
}

# --- helpers -------------------------------------------------------------

check_file_exists() {
  local label="$1" path="$2"
  if [ -f "$path" ]; then pass "$label"; else fail "$label" "missing: $path"; fi
}

check_file_absent() {
  local label="$1" path="$2"
  if [ ! -e "$path" ]; then pass "$label"; else fail "$label" "should not exist: $path"; fi
}

# grep -F fixed string; pattern must appear in path
check_contains() {
  local label="$1" path="$2" pattern="$3"
  if [ -f "$path" ] && grep -qF -- "$pattern" "$path"; then
    pass "$label"
  else
    fail "$label" "expected '$pattern' in: $path"
  fi
}

# grep -E regex; pattern must appear in path
check_contains_regex() {
  local label="$1" path="$2" pattern="$3"
  if [ -f "$path" ] && grep -qE -- "$pattern" "$path"; then
    pass "$label"
  else
    fail "$label" "expected regex /$pattern/ in: $path"
  fi
}

# Fixed string must NOT appear in path (file may exist or not).
check_not_contains() {
  local label="$1" path="$2" pattern="$3"
  if [ ! -f "$path" ]; then
    fail "$label" "file missing (cannot verify absence of '$pattern'): $path"
    return
  fi
  if grep -qF -- "$pattern" "$path"; then
    fail "$label" "'$pattern' unexpectedly present in: $path"
  else
    pass "$label"
  fi
}

# Recursive: pattern must NOT appear anywhere under the directory.
check_dir_no_match() {
  local label="$1" dir="$2" pattern="$3"
  if [ ! -d "$dir" ]; then
    fail "$label" "directory missing: $dir"
    return
  fi
  local hits
  hits="$(grep -rFn -- "$pattern" "$dir" 2>/dev/null || true)"
  if [ -z "$hits" ]; then
    pass "$label"
  else
    fail "$label" "found unexpected matches for '$pattern' under $dir:
${hits}"
  fi
}

echo "==> AC verification for bead agents-config-acmh.13"
echo "    Repo root: ${REPO_ROOT}"
echo ""

# Paths used repeatedly
IMPL_FORMULA="${REPO_ROOT}/src/plugins/beads/.beads/formulas/implement-feature.formula.toml"
FIX_FORMULA="${REPO_ROOT}/src/plugins/beads/.beads/formulas/fix-bug.formula.toml"
DOCS_FORMULA="${REPO_ROOT}/src/plugins/beads/.beads/formulas/docs-only.formula.toml"
ARCH_DOC="${REPO_ROOT}/docs/specs/bead-pipeline-architecture.md"
DOCS_EDITS_AGENT="${REPO_ROOT}/src/plugins/beads/.agents/agents/docs-edits-team.md"
PRFIX_AGENT="${REPO_ROOT}/src/plugins/beads/.agents/agents/pr-comment-fixer-team.md"
DOCS_EDITS_SPEC="${REPO_ROOT}/docs/specs/docs-edits-report-v1.md"
PRFIX_SPEC="${REPO_ROOT}/docs/specs/pr-comment-fix-report-v1.md"
WORKER_REPORT_SPEC="${REPO_ROOT}/docs/specs/worker-report-v1.md"
PR_SKILL="${REPO_ROOT}/src/user/.agents/skills/wait-for-pr-comments/SKILL.md"
TECH_LEAD="${REPO_ROOT}/src/user/.agents/agents/tech-lead.md"
QR_AGENT="${REPO_ROOT}/src/user/.agents/agents/quality-reviewer.md"
BEAD_IMPLEMENTOR="${REPO_ROOT}/src/plugins/beads/.agents/agents/bead-implementor.md"
VERIFY_ARTIFACTS="${REPO_ROOT}/scripts/smoke/verify-artifacts.sh"

# ============================================================
# R1.1 — implement-feature formula red-tests stage
# ============================================================
echo "[R1.1] implement-feature.formula.toml — red-tests dispatches tdd-red-team"
check_contains "R1.1a: red-tests dispatches tdd-red-team" \
  "$IMPL_FORMULA" "tdd-red-team"
check_contains_regex "R1.1b: dispatch instruction mentions multi-AC[ -]mode" \
  "$IMPL_FORMULA" "multi-AC( mode)?"
check_not_contains "R1.1c: no bead-implementor references" \
  "$IMPL_FORMULA" "bead-implementor"

# ============================================================
# R1.2 — fix-bug formula red-tests stage
# ============================================================
echo ""
echo "[R1.2] fix-bug.formula.toml — red-tests dispatches tdd-red-team (single-regression)"
check_contains "R1.2a: red-tests dispatches tdd-red-team" \
  "$FIX_FORMULA" "tdd-red-team"
check_contains_regex "R1.2b: dispatch instruction mentions single-regression( mode)?" \
  "$FIX_FORMULA" "single-regression( mode)?"
check_not_contains "R1.2c: no bead-implementor references" \
  "$FIX_FORMULA" "bead-implementor"

# ============================================================
# R1.3 — fix-bug diagnose stage dispatches bug-diagnoser
# ============================================================
echo ""
echo "[R1.3] fix-bug.formula.toml — diagnose dispatches bug-diagnoser"
check_contains "R1.3a: diagnose stage dispatches bug-diagnoser" \
  "$FIX_FORMULA" "bug-diagnoser"
# R1.3b covered by R1.2c (whole-file no bead-implementor)

# ============================================================
# R1.4 — docs-only formula apply-edits dispatches docs-edits-team
# ============================================================
echo ""
echo "[R1.4] docs-only.formula.toml — apply-edits dispatches docs-edits-team"
check_contains "R1.4a: apply-edits dispatches docs-edits-team" \
  "$DOCS_FORMULA" "docs-edits-team"
check_not_contains "R1.4b: no bead-implementor references" \
  "$DOCS_FORMULA" "bead-implementor"

# ============================================================
# R1.5 — bead-pipeline-architecture.md cleanup + new rows
# ============================================================
echo ""
echo "[R1.5] bead-pipeline-architecture.md — no bead-implementor + new agent rows"
check_not_contains "R1.5a: no bead-implementor in architecture doc" \
  "$ARCH_DOC" "bead-implementor"
check_contains "R1.5b: §6 mentions tdd-red-team" \
  "$ARCH_DOC" "tdd-red-team"
check_contains "R1.5c: §6 mentions tdd-green-team" \
  "$ARCH_DOC" "tdd-green-team"
check_contains "R1.5d: §6 mentions bug-diagnoser" \
  "$ARCH_DOC" "bug-diagnoser"
check_contains "R1.5e: §6 mentions docs-edits-team" \
  "$ARCH_DOC" "docs-edits-team"
check_contains "R1.5f: §6 mentions pr-comment-fixer-team" \
  "$ARCH_DOC" "pr-comment-fixer-team"
check_contains "R1.5g: docs-edits-team row links to docs-edits-report-v1.md" \
  "$ARCH_DOC" "docs-edits-report-v1.md"
check_contains "R1.5h: pr-comment-fixer-team row links to pr-comment-fix-report-v1.md" \
  "$ARCH_DOC" "pr-comment-fix-report-v1.md"
check_contains "R1.5i: tdd-red-team row links to tdd-red-report-v1.md" \
  "$ARCH_DOC" "tdd-red-report-v1.md"
check_contains "R1.5j: tdd-green-team row links to tdd-green-report-v1.md" \
  "$ARCH_DOC" "tdd-green-report-v1.md"
check_contains "R1.5k: bug-diagnoser row links to bug-diagnoser-report-v1.md" \
  "$ARCH_DOC" "bug-diagnoser-report-v1.md"

# ============================================================
# R1.6 — bead-implementor.md deleted
# ============================================================
echo ""
echo "[R1.6] bead-implementor agent file removed"
check_file_absent "R1.6: bead-implementor.md does not exist" "$BEAD_IMPLEMENTOR"

# ============================================================
# R1.6.x — verify-artifacts.sh asserts the five worker agents, not bead-implementor
# ============================================================
echo ""
echo "[R1.6.x] verify-artifacts.sh updated (worker roster, not bead-implementor)"
check_not_contains "R1.6.x.a: no bead-implementor agent assertion in verify-artifacts.sh" \
  "$VERIFY_ARTIFACTS" "bead-implementor"
check_contains "R1.6.x.b: asserts tdd-red-team.md" \
  "$VERIFY_ARTIFACTS" "tdd-red-team.md"
check_contains "R1.6.x.c: asserts tdd-green-team.md" \
  "$VERIFY_ARTIFACTS" "tdd-green-team.md"
check_contains "R1.6.x.d: asserts bug-diagnoser.md" \
  "$VERIFY_ARTIFACTS" "bug-diagnoser.md"
check_contains "R1.6.x.e: asserts docs-edits-team.md" \
  "$VERIFY_ARTIFACTS" "docs-edits-team.md"
check_contains "R1.6.x.f: asserts pr-comment-fixer-team.md" \
  "$VERIFY_ARTIFACTS" "pr-comment-fixer-team.md"

# ============================================================
# R1.6.y — tests/ has no bead-implementor references
# ============================================================
echo ""
echo "[R1.6.y] tests/ free of bead-implementor"
check_dir_no_match "R1.6.y: no bead-implementor in tests/" \
  "${REPO_ROOT}/tests" "bead-implementor"

# ============================================================
# R2.1 — docs-edits-team agent file
# ============================================================
echo ""
echo "[R2.1] docs-edits-team agent definition"
check_file_exists "R2.1a: docs-edits-team.md exists" "$DOCS_EDITS_AGENT"
check_contains "R2.1b: frontmatter model: opus" \
  "$DOCS_EDITS_AGENT" "model: opus"
check_contains "R2.1c: frontmatter effort: high" \
  "$DOCS_EDITS_AGENT" "effort: high"
check_contains "R2.1d: frontmatter color: cyan" \
  "$DOCS_EDITS_AGENT" "color: cyan"
check_contains_regex "R2.1e: tools list includes Read/Edit/Write/Grep/Glob/Bash" \
  "$DOCS_EDITS_AGENT" "tools:.*Read.*Edit.*Write.*Grep.*Glob.*Bash"
check_contains "R2.1f: body cites docs/specs/docs-edits-report-v1.md" \
  "$DOCS_EDITS_AGENT" "docs/specs/docs-edits-report-v1.md"
# Body contains zero `bd ` invocations (bd subcommand calls). Pattern matches
# 'bd ' followed by a non-newline character to avoid matching incidental words.
if [ -f "$DOCS_EDITS_AGENT" ]; then
  if grep -qE '\bbd [a-z]' "$DOCS_EDITS_AGENT"; then
    fail "R2.1g: no bd subcommand calls in body" "found bd <subcommand> in $DOCS_EDITS_AGENT"
  else
    pass "R2.1g: no bd subcommand calls in body"
  fi
else
  fail "R2.1g: no bd subcommand calls in body" "file missing: $DOCS_EDITS_AGENT"
fi

# ============================================================
# R2.2 — pr-comment-fixer-team agent file
# ============================================================
echo ""
echo "[R2.2] pr-comment-fixer-team agent definition"
check_file_exists "R2.2a: pr-comment-fixer-team.md exists" "$PRFIX_AGENT"
check_contains "R2.2b: frontmatter model: opus" \
  "$PRFIX_AGENT" "model: opus"
check_contains "R2.2c: frontmatter effort: high" \
  "$PRFIX_AGENT" "effort: high"
check_contains "R2.2d: frontmatter color: orange" \
  "$PRFIX_AGENT" "color: orange"
check_contains_regex "R2.2e: tools list includes Read/Edit/Write/Grep/Glob/Bash" \
  "$PRFIX_AGENT" "tools:.*Read.*Edit.*Write.*Grep.*Glob.*Bash"
check_contains "R2.2f: body cites docs/specs/pr-comment-fix-report-v1.md" \
  "$PRFIX_AGENT" "docs/specs/pr-comment-fix-report-v1.md"
if [ -f "$PRFIX_AGENT" ]; then
  if grep -qE '\bbd [a-z]' "$PRFIX_AGENT"; then
    fail "R2.2g: no bd subcommand calls in body" "found bd <subcommand> in $PRFIX_AGENT"
  else
    pass "R2.2g: no bd subcommand calls in body"
  fi
else
  fail "R2.2g: no bd subcommand calls in body" "file missing: $PRFIX_AGENT"
fi

# ============================================================
# R2.2 contract-purity — pr-comment-fixer-team is beads-agnostic
# ============================================================
echo ""
echo "[R2.2 contract-purity] pr-comment-fixer-team has no beads-infrastructure logic"
check_not_contains "R2.2cp.a: no .beads references in body" \
  "$PRFIX_AGENT" ".beads"
# Already covered by R2.2g, but re-state with clearer label
if [ -f "$PRFIX_AGENT" ]; then
  if grep -qE '\bbd [a-z]' "$PRFIX_AGENT"; then
    fail "R2.2cp.b: no bd subcommand calls" "agent must not branch on beads infra"
  else
    pass "R2.2cp.b: no bd subcommand calls"
  fi
fi
check_contains_regex "R2.2cp.c: agent writes to caller-provided path (mentions 'report path' or 'absolute')" \
  "$PRFIX_AGENT" "(report path|absolute)"

# ============================================================
# R2.3 — docs-edits-report-v1.md spec
# ============================================================
echo ""
echo "[R2.3] docs-edits-report-v1.md spec"
check_file_exists "R2.3a: docs-edits-report-v1.md exists" "$DOCS_EDITS_SPEC"
check_contains "R2.3b: links to worker-report-v1.md" \
  "$DOCS_EDITS_SPEC" "worker-report-v1.md"
check_contains "R2.3c: defines files_changed field" \
  "$DOCS_EDITS_SPEC" "files_changed"
check_contains "R2.3d: defines commit_sha field" \
  "$DOCS_EDITS_SPEC" "commit_sha"
check_contains "R2.3e: defines summary field" \
  "$DOCS_EDITS_SPEC" "summary"
check_contains "R2.3f: defines skipped_items field" \
  "$DOCS_EDITS_SPEC" "skipped_items"

# ============================================================
# R2.3 rollup — worker-report-v1.md updated for docs-edits-team
# ============================================================
echo ""
echo "[R2.3 rollup] worker-report-v1.md references docs-edits-team"
check_contains "R2.3r.a: 1.3 Per-agent extensions row for docs-edits-team" \
  "$WORKER_REPORT_SPEC" "docs-edits-team"
check_contains "R2.3r.b: Quick Reference table includes docs-edits-report-v1.md" \
  "$WORKER_REPORT_SPEC" "docs-edits-report-v1.md"

# ============================================================
# R2.4 — pr-comment-fix-report-v1.md spec
# ============================================================
echo ""
echo "[R2.4] pr-comment-fix-report-v1.md spec"
check_file_exists "R2.4a: pr-comment-fix-report-v1.md exists" "$PRFIX_SPEC"
check_contains "R2.4b: links to worker-report-v1.md" \
  "$PRFIX_SPEC" "worker-report-v1.md"
check_contains "R2.4c: defines comment_id field" \
  "$PRFIX_SPEC" "comment_id"
check_contains "R2.4d: defines comment_thread_id field" \
  "$PRFIX_SPEC" "comment_thread_id"
check_contains "R2.4e: defines classification field" \
  "$PRFIX_SPEC" "classification"
check_contains "R2.4f: defines action field" \
  "$PRFIX_SPEC" "action"
check_contains "R2.4g: defines fix_summary field" \
  "$PRFIX_SPEC" "fix_summary"
check_contains "R2.4h: defines commit_sha field" \
  "$PRFIX_SPEC" "commit_sha"
check_contains "R2.4i: defines already_addressed_by_sha field" \
  "$PRFIX_SPEC" "already_addressed_by_sha"
check_contains "R2.4j: defines escalation_reason field" \
  "$PRFIX_SPEC" "escalation_reason"

# ============================================================
# R2.4 rollup — worker-report-v1.md updated for pr-comment-fixer-team
# ============================================================
echo ""
echo "[R2.4 rollup] worker-report-v1.md references pr-comment-fixer-team"
check_contains "R2.4r.a: 1.3 Per-agent extensions row for pr-comment-fixer-team" \
  "$WORKER_REPORT_SPEC" "pr-comment-fixer-team"
check_contains "R2.4r.b: Quick Reference table includes pr-comment-fix-report-v1.md" \
  "$WORKER_REPORT_SPEC" "pr-comment-fix-report-v1.md"

# ============================================================
# R2.5 — wait-for-pr-comments SKILL.md dispatches pr-comment-fixer-team
# ============================================================
echo ""
echo "[R2.5] wait-for-pr-comments SKILL.md updated"
check_contains_regex "R2.5a: subagent_type: pr-comment-fixer-team" \
  "$PR_SKILL" 'subagent_type:[[:space:]]*"?pr-comment-fixer-team"?'
check_not_contains "R2.5b: no bead-implementor in SKILL.md" \
  "$PR_SKILL" "bead-implementor"
# path construction logic present — either worker-audit or .pr-comment-fixer-
if [ -f "$PR_SKILL" ]; then
  if grep -qE "worker-audit|\.pr-comment-fixer-" "$PR_SKILL"; then
    pass "R2.5c: path-construction logic present (worker-audit or .pr-comment-fixer-)"
  else
    fail "R2.5c: path-construction logic present (worker-audit or .pr-comment-fixer-)" \
      "neither 'worker-audit' nor '.pr-comment-fixer-' found in $PR_SKILL"
  fi
else
  fail "R2.5c: path-construction logic present" "file missing: $PR_SKILL"
fi

# ============================================================
# R3.1 — tech-lead 'Do NOT Dispatch When' section
# ============================================================
echo ""
echo "[R3.1] tech-lead.md — Do NOT Dispatch When section"
check_contains_regex "R3.1a: H2 'Do NOT Dispatch When' (or equivalent)" \
  "$TECH_LEAD" "^## Do NOT Dispatch When"
check_contains_regex "R3.1b: section references start-bead/implement-bead/run-queue routing" \
  "$TECH_LEAD" "(start-bead|implement-bead|run-queue)"

# ============================================================
# R3.2a — tech-lead caller-provided roster
# ============================================================
echo ""
echo "[R3.2] tech-lead.md — caller-provided roster"
check_contains_regex "R3.2a: 'caller-provided (callable )?roster'" \
  "$TECH_LEAD" "caller-provided( callable)? roster"

# R3.2b: at most one .claude/agents reference, and if present must be near
# 'example' or 'fallback'.
if [ -f "$TECH_LEAD" ]; then
  COUNT=$(grep -cE "\.claude/agents" "$TECH_LEAD" || true)
  if [ "$COUNT" -eq 0 ]; then
    pass "R3.2b: zero .claude/agents references (acceptable: 0 or 1)"
  elif [ "$COUNT" -eq 1 ]; then
    # The single matching line must contain 'example' or 'fallback'
    LINE=$(grep -nE "\.claude/agents" "$TECH_LEAD" | head -1)
    if echo "$LINE" | grep -qiE "example|fallback"; then
      pass "R3.2b: single .claude/agents reference is example/fallback ($LINE)"
    else
      fail "R3.2b: single .claude/agents reference must be example/fallback" "$LINE"
    fi
  else
    fail "R3.2b: at most 1 .claude/agents reference" "found $COUNT references"
  fi
else
  fail "R3.2b: tech-lead.md present" "missing: $TECH_LEAD"
fi

# ============================================================
# R3.3 — tech-lead disallowedTools
# ============================================================
echo ""
echo "[R3.3] tech-lead.md — frontmatter disallowedTools"
check_contains "R3.3: disallowedTools: Write, Edit" \
  "$TECH_LEAD" "disallowedTools: Write, Edit"

# ============================================================
# R4.2 — quality-reviewer Memory Protocol
# ============================================================
echo ""
echo "[R4.2] quality-reviewer.md — Memory Protocol section"
check_contains_regex "R4.2a: H2 'Memory Protocol' (or equivalent)" \
  "$QR_AGENT" "^## Memory Protocol"
check_contains "R4.2b: mentions 'recurring vulnerability patterns'" \
  "$QR_AGENT" "recurring vulnerability patterns"
check_contains "R4.2c: mentions 'project-specific anti-patterns'" \
  "$QR_AGENT" "project-specific anti-patterns"
check_contains "R4.2d: mentions 'prior false-positive corrections'" \
  "$QR_AGENT" "prior false-positive corrections"
check_contains_regex "R4.2e: horizon number 30 present" \
  "$QR_AGENT" "\\b30\\b"
check_contains_regex "R4.2f: 'LRU' or 'least-recently' present" \
  "$QR_AGENT" "LRU|least-recently"
check_contains_regex "R4.2g: hard cap number 50 present" \
  "$QR_AGENT" "\\b50\\b"
check_contains_regex "R4.2h: '(explicit )?human ratification'" \
  "$QR_AGENT" "(explicit )?human ratification"

# ============================================================
# Cross-cutting — bead-implementor must be absent from src/, scripts/, docs/specs/, tests/
# ============================================================
echo ""
echo "[Cross-cutting] bead-implementor absent from src/, scripts/, tests/, docs/specs/"
check_dir_no_match "X.1: no bead-implementor in src/" \
  "${REPO_ROOT}/src" "bead-implementor"
check_dir_no_match "X.2: no bead-implementor in scripts/" \
  "${REPO_ROOT}/scripts" "bead-implementor"
check_dir_no_match "X.3: no bead-implementor in tests/" \
  "${REPO_ROOT}/tests" "bead-implementor"
check_dir_no_match "X.4: no bead-implementor in docs/specs/" \
  "${REPO_ROOT}/docs/specs" "bead-implementor"

# ============================================================
# Quality gates
# ============================================================
echo ""
echo "[Quality] project test suite + install.sh --dry-run"

# Project test suite
echo "  -- running project test suite --"
if ( cd "$REPO_ROOT" && find src/user/.agents/skills -name '*_test.sh' -print0 | sort -z | xargs -0 -I{} sh -c 'echo "[TEST] $1"; bash "$1" || exit 1' _ {} ) >/dev/null 2>&1; then
  pass "Q.1: project test suite exits 0"
else
  fail "Q.1: project test suite exits 0" "skills test suite failed"
fi

# install.sh --dry-run
echo "  -- running install.sh --dry-run --"
if ( cd "$REPO_ROOT" && bash scripts/install.sh --dry-run ) >/dev/null 2>&1; then
  pass "Q.2: install.sh --dry-run exits 0"
else
  fail "Q.2: install.sh --dry-run exits 0" "install.sh --dry-run failed"
fi

# ============================================================
# Results
# ============================================================
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ "${FAIL}" -gt 0 ]; then
  echo "FAIL — ${FAIL} acmh.13 AC check(s) failing"
  exit 1
fi

echo "PASS — all acmh.13 AC checks satisfied"
exit 0
