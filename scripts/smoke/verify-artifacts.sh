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
  if [ -f "${path}" ] && grep -q "${pattern}" "${path}"; then
    echo "  PASS  ${label}"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  ${label}"
    echo "        expected '${pattern}' in: ${path}"
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

# Scope item 7: bead-implementor agent
check_file \
  "bead-implementor agent exists" \
  "${REPO_ROOT}/src/plugins/beads/.agents/agents/bead-implementor.md"

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

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"

if [ "${FAIL}" -gt 0 ]; then
  echo "FAIL — ${FAIL} artifact(s) missing or incorrect"
  exit 1
fi

echo "PASS — all artifacts verified"
exit 0
