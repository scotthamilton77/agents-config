#!/usr/bin/env bash
# scripts/smoke/setup.sh
# Smoke test harness for the bead pipeline architecture (bead 7bk.9).
#
# Sets up a scratch project directory with a minimal source/test layout,
# a project-config.toml, an initialized beads tracker, and a seed bead.
# Exits non-zero with a TODO marker because end-to-end driver invocation
# is not yet wired into this harness — wire it in before flipping the exit.
#
# Usage: bash scripts/smoke/setup.sh
# Environment variables:
#   SMOKE_DIR  - override the scratch directory (default: /tmp/bead-pipeline-smoke-<ts>)

set -euo pipefail

TIMESTAMP=$(date +%s)
SMOKE_DIR="${SMOKE_DIR:-/tmp/bead-pipeline-smoke-${TIMESTAMP}}"

echo "==> Creating smoke scratch directory: ${SMOKE_DIR}"
mkdir -p "${SMOKE_DIR}"

# ---------------------------------------------------------------------------
# Minimal project structure
# ---------------------------------------------------------------------------
echo "==> Writing project files"

mkdir -p "${SMOKE_DIR}/src"
cat > "${SMOKE_DIR}/src/hello.sh" <<'SRCEOF'
#!/usr/bin/env bash
echo "hello from smoke project"
SRCEOF
chmod +x "${SMOKE_DIR}/src/hello.sh"

mkdir -p "${SMOKE_DIR}/tests"
cat > "${SMOKE_DIR}/tests/test_hello.sh" <<'TESTEOF'
#!/usr/bin/env bash
# Intentionally failing placeholder test — red-tests stage will replace it.
echo "FAIL: test_hello not yet implemented"
exit 1
TESTEOF
chmod +x "${SMOKE_DIR}/tests/test_hello.sh"

# ---------------------------------------------------------------------------
# project-config.toml (minimal subset matching actual schema per section 5.1)
# ---------------------------------------------------------------------------
cat > "${SMOKE_DIR}/project-config.toml" <<'CFGEOF'
[project]
name = "smoke-test-project"
default-formula = "implement-feature"

[gates]
build = ""
typecheck = ""
lint = ""
test = "echo 'no tests'"
CFGEOF

# ---------------------------------------------------------------------------
# Initialize beads tracker
# ---------------------------------------------------------------------------
echo "==> Initialising beads in ${SMOKE_DIR}"
cd "${SMOKE_DIR}"
if ! command -v bd &>/dev/null; then
  echo "ERROR: 'bd' not found on PATH — install beads before running smoke tests"
  exit 1
fi
bd init --prefix smoke 2>&1 | sed 's/^/    /'

# ---------------------------------------------------------------------------
# Seed bead
# ---------------------------------------------------------------------------
echo "==> Creating seed bead"
SEED_ID=$(bd create --type feature --priority 2 \
  --title "Smoke: hello-world feature" \
  --description "Trivial feature to exercise the full bead pipeline end-to-end." \
  --json 2>/dev/null | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)

if [ -z "${SEED_ID}" ]; then
  # bd create may print id differently; fall back to listing
  SEED_ID=$(bd list --json 2>/dev/null | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
fi
echo "    Seed bead id: ${SEED_ID:-<unknown>}"

# ---------------------------------------------------------------------------
# TODO: invoke scripts/bead-driver-test.sh against ${SMOKE_DIR} to exercise
# the full pipeline end-to-end. Until that wiring lands, exit non-zero so
# CI flags this harness as incomplete.
# ---------------------------------------------------------------------------
echo ""
echo "TODO: end-to-end driver invocation not yet wired into this harness."
echo "      Seed bead and scratch project are ready at: ${SMOKE_DIR}"
echo "      Wire in: bash scripts/bead-driver-test.sh --once (with REPO_ROOT=${SMOKE_DIR})"
echo ""
echo "Smoke setup complete. Scratch dir: ${SMOKE_DIR}"
exit 1  # Controlled failure until end-to-end driver invocation is wired in.
