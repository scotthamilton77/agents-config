#!/usr/bin/env bash
# scripts/smoke/verify-artifacts.sh
# Artifact existence check for bead 7bk.9 (Per-step claude -p orchestration).
#
# Checks that every artifact the bead is required to produce actually exists.
# Intended to be run at the END of the green phase; MUST fail during the red
# phase because the artifacts do not yet exist.
#
# Exit codes:
#   0  — all checks pass
#   1  — one or more checks failed
#
# Usage: bash scripts/smoke/verify-artifacts.sh [REPO_ROOT]
#   REPO_ROOT defaults to the directory two levels above this script.

# -e is intentionally absent: we want ALL checks to run and accumulate into
# PASS/FAIL counts before deciding the exit code at the end, not bail on the
# first failed check_file / check_executable / check_file_contains call.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${1:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

PASS=0
FAIL=0

check_file() {
  local label="$1"
  local path="$2"
  if [ -f "${path}" ]; then
    echo "  PASS  ${label}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${label}"
    echo "        expected: ${path}"
    FAIL=$((FAIL + 1))
  fi
}

check_executable() {
  local label="$1"
  local path="$2"
  if [ -x "${path}" ]; then
    echo "  PASS  ${label}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${label}"
    echo "        expected executable: ${path}"
    FAIL=$((FAIL + 1))
  fi
}

check_file_contains() {
  local label="$1"
  local path="$2"
  local pattern="$3"
  if [ -f "${path}" ] && grep -qF "${pattern}" "${path}"; then
    echo "  PASS  ${label}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${label}"
    echo "        expected '${pattern}' in: ${path}"
    FAIL=$((FAIL + 1))
  fi
}

# verify_flattening (bead jyb.5):
#   Run install.sh into a sandbox HOME and verify that DYNAMIC-INCLUDE
#   markers in each tool's instruction template were actually replaced
#   with the contents of the referenced shared templates.
#
#   For each of Claude, Codex, Gemini, and OpenCode we check that the
#   assembled top-level instruction file contains representative strings
#   from AGENT-PERSONA.md.template, USER-PERSONA.md.template, and
#   INSTRUCTIONS.md.template — and that none of the raw DYNAMIC-INCLUDE
#   markers leaked through unprocessed.
#
#   This is a positive flattening assertion: existence of the file is
#   already covered by check_file; this function answers the harder
#   question "did the install actually inline the shared content?"
verify_flattening() {
  local label_prefix="$1"
  local instructions_path="$2"

  # Representative substrings from each shared template that gets
  # DYNAMIC-INCLUDE'd into every tool's AGENTS.md / GEMINI.md.
  check_file_contains \
    "${label_prefix}: AGENT-PERSONA content inlined" \
    "${instructions_path}" \
    "snarky, arrogant, boastful"
  check_file_contains \
    "${label_prefix}: USER-PERSONA content inlined" \
    "${instructions_path}" \
    "54yo architect, Sci-Fi nerd"
  check_file_contains \
    "${label_prefix}: INSTRUCTIONS laws block inlined" \
    "${instructions_path}" \
    "L0 Codebase"
  check_file_contains \
    "${label_prefix}: INSTRUCTIONS decision-matrix inlined" \
    "${instructions_path}" \
    "verify-facts"

  # Negative check: an unprocessed marker means flattening was skipped.
  # Match the marker syntax (`<!-- DYNAMIC-INCLUDE`) rather than the bare
  # word — the inlined INSTRUCTIONS template legitimately mentions
  # "DYNAMIC-INCLUDE" in a prose comment about the mechanism itself.
  local label="${label_prefix}: no unprocessed DYNAMIC-INCLUDE markers"
  if [ -f "${instructions_path}" ] \
       && ! grep -qE '<!-- DYNAMIC-INCLUDE(-RULES)?:' "${instructions_path}"; then
    echo "  PASS  ${label}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${label}"
    echo "        unexpected DYNAMIC-INCLUDE marker in: ${instructions_path}"
    FAIL=$((FAIL + 1))
  fi
}

echo "==> Artifact verification for bead 7bk.9"
echo "    Repo root: ${REPO_ROOT}"
echo ""

# Scope item 2: slash command
check_file \
  "implement-bead slash command exists" \
  "${REPO_ROOT}/src/plugins/beads/.claude/commands/implement-bead.md"

# Worker agent family (role-named, post-acmh.13 split)
check_file \
  "tdd-red-team agent exists" \
  "${REPO_ROOT}/src/plugins/beads/.agents/agents/tdd-red-team.md"
check_file \
  "tdd-green-team agent exists" \
  "${REPO_ROOT}/src/plugins/beads/.agents/agents/tdd-green-team.md"
check_file \
  "bug-diagnoser agent exists" \
  "${REPO_ROOT}/src/plugins/beads/.agents/agents/bug-diagnoser.md"
check_file \
  "docs-edits-team agent exists" \
  "${REPO_ROOT}/src/plugins/beads/.agents/agents/docs-edits-team.md"
check_file \
  "pr-comment-fixer-team agent exists" \
  "${REPO_ROOT}/src/plugins/beads/.agents/agents/pr-comment-fixer-team.md"

# Scope item 4: shell driver script
check_file \
  "bead-driver-test.sh exists" \
  "${REPO_ROOT}/scripts/bead-driver-test.sh"

# Scope item 4 / setup.sh: setup script must itself be executable
check_executable \
  "scripts/smoke/setup.sh is executable" \
  "${REPO_ROOT}/scripts/smoke/setup.sh"

# Scope item 9: project-config.toml at repo root
check_file \
  "project-config.toml exists at repo root" \
  "${REPO_ROOT}/project-config.toml"

# Scope item 5: implement-feature formula has 8 role-named stages (check "preflight")
check_file_contains \
  "implement-feature.formula.toml contains 'preflight' stage" \
  "${REPO_ROOT}/src/plugins/beads/.beads/formulas/implement-feature.formula.toml" \
  "preflight"

# Scope item 6: fix-bug formula has diagnose stage
check_file_contains \
  "fix-bug.formula.toml contains 'diagnose' stage name" \
  "${REPO_ROOT}/src/plugins/beads/.beads/formulas/fix-bug.formula.toml" \
  '"diagnose"'

# ── DYNAMIC-INCLUDE flattening (bead jyb.5) ────────────────────────────────
# Drive a sandboxed install and verify shared template content was actually
# inlined into each tool's assembled instruction file. install.sh writes to
# ~/.<tool>/ and ~/.config/opencode/, so we point HOME at a scratch dir.
echo ""
echo "==> Universal-flattening checks (bead jyb.5)"

if ! command -v jq &>/dev/null; then
  echo "  SKIP  install.sh requires jq; flattening checks not run"
else
  SANDBOX_HOME="$(mktemp -d "${TMPDIR:-/tmp}/verify-artifacts-flatten.XXXXXXXX")"
  echo "    Sandbox HOME: ${SANDBOX_HOME}"

  # Force the install to target every tool that supports DYNAMIC-INCLUDE
  # (claude, codex, gemini, opencode). --plugins= disables plugin
  # auto-detection so the test does not depend on the host bd/beads state.
  install_log="${SANDBOX_HOME}/install.log"
  if HOME="${SANDBOX_HOME}" \
       bash "${REPO_ROOT}/scripts/install.sh" \
            --yes \
            --tools=claude,codex,gemini,opencode \
            --plugins= \
            >"${install_log}" 2>&1; then
    echo "    install.sh: OK"
  else
    echo "    install.sh: FAILED (see ${install_log})"
    FAIL=$((FAIL + 1))
  fi

  verify_flattening "claude/AGENTS.md"   "${SANDBOX_HOME}/.claude/AGENTS.md"
  verify_flattening "codex/AGENTS.md"    "${SANDBOX_HOME}/.codex/AGENTS.md"
  verify_flattening "gemini/GEMINI.md"   "${SANDBOX_HOME}/.gemini/GEMINI.md"
  verify_flattening "opencode/AGENTS.md" "${SANDBOX_HOME}/.config/opencode/AGENTS.md"
fi

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ "${FAIL}" -gt 0 ]; then
  echo "FAIL — ${FAIL} artifact(s) missing or incorrect"
  exit 1
fi

echo "PASS — all artifacts verified"
exit 0
