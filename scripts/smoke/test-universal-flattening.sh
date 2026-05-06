#!/usr/bin/env bash
# scripts/smoke/test-universal-flattening.sh
#
# Verifies that AGENTS.md.template (and GEMINI.md.template) are flattened
# for all tools using the DYNAMIC-INCLUDE markers.
#
# This test is expected to FAIL until the universal flattening logic is implemented.

set -euo pipefail

# Worktree Root (absolute path)
WORKTREE_ROOT="/Users/scott/src/projects/agents-config/.claude/worktrees/feat/agents-config-jyb.1-universal-instruction-flattening"

# Use a temporary directory for the test
TEST_ROOT=$(mktemp -d /tmp/universal-flattening-test-XXXXXX)
MOCK_HOME="${TEST_ROOT}/home"
MOCK_PROJECT="${TEST_ROOT}/project"

echo "==> Setting up mock environment at ${TEST_ROOT}"

mkdir -p "${MOCK_HOME}/.claude"
mkdir -p "${MOCK_HOME}/.gemini"
mkdir -p "${MOCK_HOME}/.config/opencode"

mkdir -p "${MOCK_PROJECT}/src/user/.agents"
mkdir -p "${MOCK_PROJECT}/src/user/.claude"
mkdir -p "${MOCK_PROJECT}/src/user/.gemini"
mkdir -p "${MOCK_PROJECT}/src/user/.opencode"
mkdir -p "${MOCK_PROJECT}/scripts"

# Copy install.sh to mock project
cp "${WORKTREE_ROOT}/scripts/install.sh" "${MOCK_PROJECT}/scripts/install.sh"

# Create a content file to include
echo "Shared Agent Content" > "${MOCK_PROJECT}/shared-content.md"

# Create templates with DYNAMIC-INCLUDE
cat > "${MOCK_PROJECT}/src/user/.opencode/AGENTS.md.template" <<EOF
# OpenCode Agents
<!-- DYNAMIC-INCLUDE: shared-content.md -->
EOF

cat > "${MOCK_PROJECT}/src/user/.claude/AGENTS.md.template" <<EOF
# Claude Agents
<!-- DYNAMIC-INCLUDE: shared-content.md -->
EOF

cat > "${MOCK_PROJECT}/src/user/.gemini/GEMINI.md.template" <<EOF
# Gemini Instructions
<!-- DYNAMIC-INCLUDE: shared-content.md -->
EOF

# Run install.sh
export PROJECT_ROOT="${MOCK_PROJECT}"
export HOME="${MOCK_HOME}"

echo "==> Running install.sh"
# Use --tools to limit scope and avoid auto-detection issues in a minimal mock
bash "${MOCK_PROJECT}/scripts/install.sh" --yes --verbose --tools=opencode,claude,gemini

echo "==> Verifying results"

FAILED=0

# OpenCode should be flattened (existing behavior)
if grep -q "Shared Agent Content" "${MOCK_HOME}/.config/opencode/AGENTS.md"; then
    echo "OK: OpenCode AGENTS.md is flattened"
else
    echo "FAIL: OpenCode AGENTS.md is NOT flattened"
    FAILED=1
fi

# Claude should BE flattened (expected feature)
if grep -q "Shared Agent Content" "${MOCK_HOME}/.claude/AGENTS.md"; then
    echo "OK: Claude AGENTS.md is flattened"
else
    echo "FAIL: Claude AGENTS.md is NOT flattened"
    FAILED=1
fi

# Gemini should BE flattened (expected feature)
if grep -q "Shared Agent Content" "${MOCK_HOME}/.gemini/GEMINI.md"; then
    echo "OK: Gemini GEMINI.md is flattened"
else
    echo "FAIL: Gemini GEMINI.md is NOT flattened"
    FAILED=1
fi

if [ $FAILED -eq 1 ]; then
    echo "==> Universal flattening test FAILED (Expected for RED step)"
    exit 1
else
    echo "==> Universal flattening test PASSED"
    exit 0
fi
