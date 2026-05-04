#!/usr/bin/env bash
# scripts/smoke/setup.sh
# Smoke test harness for the bead pipeline architecture (bead 7bk.9).
#
# Red-phase: sets up the scratch environment and seed bead, but does NOT
# yet invoke bead-driver-test.sh (which doesn't exist yet).  Exits with a
# clear TODO message so CI sees a controlled failure.
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
# Intentionally failing placeholder test (red phase)
echo "FAIL: test_hello not yet implemented"
exit 1
TESTEOF
chmod +x "${SMOKE_DIR}/tests/test_hello.sh"

# ---------------------------------------------------------------------------
# project-config.toml (minimal schema — will be validated once scope item 9 lands)
# ---------------------------------------------------------------------------
cat > "${SMOKE_DIR}/project-config.toml" <<'CFGEOF'
[project]
name = "smoke-test-project"
language = "bash"

[bead-pipeline]
# Smoke-only: driver path will be validated by bead-driver-test.sh
driver = "scripts/bead-driver-test.sh"
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
# TODO: invoke bead-driver-test.sh once scope item 4 is implemented
# ---------------------------------------------------------------------------
echo ""
echo "TODO: scripts/bead-driver-test.sh does not exist yet."
echo "      This is expected during the red phase (bead 7bk.9 scope item 4)."
echo "      Re-run this script after the green phase to exercise the full pipeline."
echo ""
echo "Smoke setup complete. Scratch dir: ${SMOKE_DIR}"
exit 1  # Controlled red-phase failure — driver not yet available
