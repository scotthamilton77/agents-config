.PHONY: ci ci-installer test-installer lint-installer format-check-installer \
        typecheck-installer cov-installer audit-installer lint-actions \
        verify-entry-installer \
        ci-prgroom test-prgroom lint-prgroom format-check-prgroom \
        typecheck-prgroom cov-prgroom audit-prgroom verify-entry-prgroom \
        ci-workcli test-workcli lint-workcli format-check-workcli \
        typecheck-workcli cov-workcli audit-workcli verify-entry-workcli

INSTALLER := packages/installer
PRGROOM := packages/prgroom
WORKCLI := packages/workcli

ci: ci-installer ci-prgroom ci-workcli lint-actions

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
