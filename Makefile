.PHONY: ci ci-installer test-installer lint-installer format-check-installer \
        typecheck-installer cov-installer audit-installer lint-actions \
        verify-entry-installer

INSTALLER := packages/installer

ci: ci-installer lint-actions

ci-installer: lint-installer format-check-installer typecheck-installer \
              test-installer cov-installer audit-installer \
              verify-entry-installer

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

lint-actions:
	uv --project $(INSTALLER) run actionlint

verify-entry-installer:
	uv --project $(INSTALLER) run python scripts/install.py --help > /dev/null
