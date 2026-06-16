.PHONY: ci ci-installer test-installer lint-installer format-check-installer \
        typecheck-installer cov-installer golden-master-installer \
        audit-installer lint-actions verify-entry-installer \
        ci-prgroom test-prgroom lint-prgroom format-check-prgroom \
        typecheck-prgroom cov-prgroom audit-prgroom verify-entry-prgroom

INSTALLER := packages/installer
PRGROOM := packages/prgroom

ci: ci-installer ci-prgroom lint-actions

ci-installer: lint-installer format-check-installer typecheck-installer \
              cov-installer golden-master-installer audit-installer \
              verify-entry-installer

test-installer:
	cd $(INSTALLER) && uv run pytest -m "not golden_master" -q

# Golden-master is the slow bash-vs-python parity suite: it spawns both
# installers, contributes no src coverage (subprocess), and is excluded from the
# fast unit/coverage gate. Run on every push via ci-installer.
golden-master-installer:
	cd $(INSTALLER) && uv run pytest -m golden_master -q

lint-installer:
	cd $(INSTALLER) && uv run ruff check

format-check-installer:
	cd $(INSTALLER) && uv run ruff format --check

typecheck-installer:
	cd $(INSTALLER) && uv run mypy --strict src

cov-installer:
	cd $(INSTALLER) && uv run pytest -m "not golden_master" --cov --cov-report=term-missing

audit-installer:
	cd $(INSTALLER) && uv sync --frozen && uv run pip-audit

# lint-actions and verify-entry-installer run from the repo root (no `cd`) so
# they can resolve .github/workflows/ and scripts/ respectively. The
# `uv --project` flag selects the installer venv where the tool binary lives.
lint-actions:
	uv --project $(INSTALLER) run actionlint

verify-entry-installer:
	uv --project $(INSTALLER) run python scripts/install.py --help > /dev/null

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
