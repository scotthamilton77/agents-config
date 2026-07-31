.PHONY: ci ci-installer test-installer lint-installer format-check-installer \
        typecheck-installer cov-installer audit-installer lint-actions \
        verify-entry-installer \
        ci-prgroom test-prgroom lint-prgroom format-check-prgroom \
        typecheck-prgroom cov-prgroom audit-prgroom verify-entry-prgroom \
        ci-workcli test-workcli lint-workcli format-check-workcli \
        typecheck-workcli cov-workcli audit-workcli verify-entry-workcli \
        itest-workcli \
        ci-vizsuite test-vizsuite lint-vizsuite format-check-vizsuite \
        typecheck-vizsuite cov-vizsuite audit-vizsuite verify-entry-vizsuite \
        ci-grind test-grind lint-grind format-check-grind \
        typecheck-grind cov-grind audit-grind verify-entry-grind \
        ci-gitclean test-gitclean lint-gitclean format-check-gitclean \
        typecheck-gitclean cov-gitclean audit-gitclean verify-entry-gitclean \
        ci-executor test-executor lint-executor format-check-executor \
        typecheck-executor cov-executor audit-executor verify-entry-executor \
        spec-lint content-lint content-tests

INSTALLER := packages/installer
PRGROOM := packages/prgroom
WORKCLI := packages/workcli
VIZSUITE := packages/vizsuite
GRIND := packages/grind
GITCLEAN := packages/gitclean
EXECUTOR := packages/executor

ci: ci-installer ci-prgroom ci-workcli ci-vizsuite ci-grind ci-gitclean ci-executor \
    lint-actions spec-lint content-lint content-tests

ci-installer: lint-installer format-check-installer typecheck-installer \
              cov-installer audit-installer verify-entry-installer

test-installer:
	cd $(INSTALLER) && uv run pytest -q

lint-installer:
	cd $(INSTALLER) && uv run ruff check

format-check-installer:
	cd $(INSTALLER) && uv run ruff format --check

typecheck-installer:
	cd $(INSTALLER) && uv run mypy --strict src

cov-installer:
	cd $(INSTALLER) && uv run pytest --cov --cov-report=term-missing

audit-installer:
	cd $(INSTALLER) && uv sync --frozen && uv run pip-audit

# spec-lint runs from the repo root (no `cd`) so it resolves docs/specs/
# relative to the repo, mirroring lint-actions/verify-entry-installer below.
# The `uv --project` flag selects the installer venv (AC4, S5-D5/S5-B6).
spec-lint:
	uv --project $(INSTALLER) run python -m installer.spec_lint_cli .

# content-lint stages the real src/ tree for every tool and plugin and runs the
# deploy-time admission gate over it — the check ci-installer cannot make,
# because its fixtures are synthetic. It also fails on a directory under src/
# that its staging never reaches, so content-tests cannot walk a tree this gate
# cannot see. Repo-root invocation (no `cd`) so it resolves src/ and
# .installignore; `uv --project` selects the installer venv. It writes nothing
# and never invokes the installer.
content-lint:
	uv --project $(INSTALLER) run python -m installer.content_lint_cli .

# content-tests is the only gate over src/ suites: it discovers every .py/.js/.sh
# suite, requires each shipped script to have one, runs them all, and fails a
# suite that exits 0 without reporting a clean pass. Needs `node` and `uv` on
# PATH: the suites are node:test and PEP 723 scripts respectively.
content-tests:
	uv --project $(INSTALLER) run python -m installer.content_tests_cli .

# lint-actions and verify-entry-installer run from the repo root (no `cd`) so
# they can resolve .github/workflows/ and scripts/ respectively. The
# `uv --project` flag selects the installer venv where the tool binary lives.
lint-actions:
	uv --project $(INSTALLER) run actionlint

verify-entry-installer:
	uv --project $(INSTALLER) run python scripts/install.py --help > /dev/null
	uv --project $(INSTALLER) run python -m installer --help > /dev/null

# ── prgroom (mirrors the ci-installer block one-for-one) ──

ci-prgroom: lint-prgroom format-check-prgroom typecheck-prgroom \
            cov-prgroom audit-prgroom \
            verify-entry-prgroom

test-prgroom:
	cd $(PRGROOM) && uv run pytest -q

lint-prgroom:
	cd $(PRGROOM) && uv run ruff check

format-check-prgroom:
	cd $(PRGROOM) && uv run ruff format --check

typecheck-prgroom:
	cd $(PRGROOM) && uv run mypy --strict src

cov-prgroom:
	cd $(PRGROOM) && uv run pytest --cov --cov-report=term-missing

audit-prgroom:
	cd $(PRGROOM) && uv sync --frozen && uv run pip-audit

# verify-entry-prgroom asserts the console-script entry point resolves and the
# CLI root parses (`prgroom --help` exits 0). Run via `uv --project` so the
# prgroom venv where the entry point is installed is selected.
verify-entry-prgroom:
	uv --project $(PRGROOM) run prgroom --help > /dev/null

# ── workcli (mirrors the ci-installer block one-for-one) ──

ci-workcli: lint-workcli format-check-workcli typecheck-workcli \
            cov-workcli audit-workcli \
            verify-entry-workcli

test-workcli:
	cd $(WORKCLI) && uv run pytest -q

lint-workcli:
	cd $(WORKCLI) && uv run ruff check

format-check-workcli:
	cd $(WORKCLI) && uv run ruff format --check

typecheck-workcli:
	cd $(WORKCLI) && uv run mypy --strict src

cov-workcli:
	cd $(WORKCLI) && uv run pytest --cov --cov-report=term-missing

audit-workcli:
	cd $(WORKCLI) && uv sync --frozen && uv run pip-audit

# verify-entry-workcli asserts the console-script entry point resolves, the
# protocol handshake works, and the CLI root parses (`work --help` exits 0).
# Run via `uv --project` so the workcli venv where the entry point is
# installed is selected.
verify-entry-workcli:
	uv --project $(WORKCLI) run work --protocol-version > /dev/null
	uv --project $(WORKCLI) run work --help > /dev/null

# itest-workcli is the real-bd integration suite: it stands up an isolated
# embedded-Dolt bd install per test and drives the production `work` CLI against
# it. It requires `bd` on PATH and is DELIBERATELY EXCLUDED from `ci-workcli` /
# `ci` (needs the bd toolchain; ~40s+ serial). Pre-push discipline, not a gate.
# `-p no:xdist` pins it serial so the session-scoped read_only_install pays its
# ~1.4s bd init ONCE (under -n auto it would re-init per worker).
itest-workcli:
	cd $(WORKCLI) && uv run pytest tests/integration -q -p no:xdist

# ── vizsuite (mirrors the ci-workcli block one-for-one; enforced via the
# top-level `ci:` aggregate) ──
ci-vizsuite: lint-vizsuite format-check-vizsuite typecheck-vizsuite \
             cov-vizsuite audit-vizsuite verify-entry-vizsuite

test-vizsuite:
	cd $(VIZSUITE) && uv run pytest -q
lint-vizsuite:
	cd $(VIZSUITE) && uv run ruff check
format-check-vizsuite:
	cd $(VIZSUITE) && uv run ruff format --check
typecheck-vizsuite:
	cd $(VIZSUITE) && uv run mypy --strict src
cov-vizsuite:
	cd $(VIZSUITE) && uv run pytest --cov --cov-report=term-missing
audit-vizsuite:
	cd $(VIZSUITE) && uv sync --frozen && uv run pip-audit
verify-entry-vizsuite:
	uv --project $(VIZSUITE) run viz --protocol-version > /dev/null
	uv --project $(VIZSUITE) run viz --help > /dev/null

# ── grind (mirrors the ci-workcli block one-for-one; enforced via the
# top-level `ci:` aggregate). ──
ci-grind: lint-grind format-check-grind typecheck-grind \
          cov-grind audit-grind verify-entry-grind

test-grind:
	cd $(GRIND) && uv run pytest -q
lint-grind:
	cd $(GRIND) && uv run ruff check
format-check-grind:
	cd $(GRIND) && uv run ruff format --check
typecheck-grind:
	cd $(GRIND) && uv run mypy --strict src
cov-grind:
	cd $(GRIND) && uv run pytest --cov --cov-report=term-missing
audit-grind:
	cd $(GRIND) && uv sync --frozen && uv run pip-audit
# verify-entry-grind asserts the console-script entry point resolves and the
# CLI root parses (`grind --help` exits 0). Run via `uv --project` so the
# grind venv where the entry point is installed is selected.
verify-entry-grind:
	uv --project $(GRIND) run grind --help > /dev/null

# ── gitclean (mirrors the ci-grind block one-for-one; enforced via the
# top-level `ci:` aggregate). ──
ci-gitclean: lint-gitclean format-check-gitclean typecheck-gitclean \
             cov-gitclean audit-gitclean verify-entry-gitclean

test-gitclean:
	cd $(GITCLEAN) && uv run pytest -q
lint-gitclean:
	cd $(GITCLEAN) && uv run ruff check
format-check-gitclean:
	cd $(GITCLEAN) && uv run ruff format --check
typecheck-gitclean:
	cd $(GITCLEAN) && uv run mypy --strict src
cov-gitclean:
	cd $(GITCLEAN) && uv run pytest --cov --cov-report=term-missing
audit-gitclean:
	cd $(GITCLEAN) && uv sync --frozen && uv run pip-audit
# verify-entry-gitclean asserts the console-script entry point resolves and the
# CLI root parses (`gitclean --help` exits 0). Run via `uv --project` so the
# gitclean venv where the entry point is installed is selected.
verify-entry-gitclean:
	uv --project $(GITCLEAN) run gitclean --help > /dev/null

# ── executor (mirrors the ci-grind block one-for-one; enforced via the
# top-level `ci:` aggregate). ──
ci-executor: lint-executor format-check-executor typecheck-executor \
             cov-executor audit-executor verify-entry-executor

test-executor:
	cd $(EXECUTOR) && uv run pytest -q
lint-executor:
	cd $(EXECUTOR) && uv run ruff check
format-check-executor:
	cd $(EXECUTOR) && uv run ruff format --check
typecheck-executor:
	cd $(EXECUTOR) && uv run mypy --strict src
cov-executor:
	cd $(EXECUTOR) && uv run pytest --cov --cov-report=term-missing
audit-executor:
	cd $(EXECUTOR) && uv sync --frozen && uv run pip-audit
# verify-entry-executor asserts the console-script entry point resolves and
# the CLI root parses (`executor --help` exits 0). Run via `uv --project` so
# the executor venv where the entry point is installed is selected.
verify-entry-executor:
	uv --project $(EXECUTOR) run executor --help > /dev/null
