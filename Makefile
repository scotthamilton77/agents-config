.PHONY: ci ci-installer test-installer lint-installer format-check-installer \
        typecheck-installer cov-installer audit-installer lint-actions \
        verify-entry-installer \
        ci-prgroom test-prgroom lint-prgroom format-check-prgroom \
        typecheck-prgroom cov-prgroom audit-prgroom verify-entry-prgroom \
        ci-grind test-grind lint-grind format-check-grind \
        typecheck-grind cov-grind audit-grind verify-entry-grind \
        ci-gitclean test-gitclean lint-gitclean format-check-gitclean \
        typecheck-gitclean cov-gitclean audit-gitclean verify-entry-gitclean \
        ci-executor test-executor lint-executor format-check-executor \
        typecheck-executor cov-executor audit-executor verify-entry-executor \
        spec-lint content-lint content-tests doc-lint

INSTALLER := packages/installer
PRGROOM := packages/prgroom
GRIND := packages/grind
GITCLEAN := packages/gitclean
EXECUTOR := packages/executor

# `doc-lint` gates here because the tree is clean. It reports live staleness in
# prose nobody is editing, so a finding can turn an unrelated build red — and the
# remedy for that is to correct the prose, never to exempt the file. An exemption
# silences the one class of drift that has no reviewer, which is the whole reason
# the check exists.
ci: ci-installer ci-prgroom ci-grind ci-gitclean ci-executor \
    lint-actions spec-lint content-lint content-tests doc-lint

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
# because its fixtures are synthetic. It also fails on a directory staging never
# reads and nothing declares — content that deploys nowhere and is measured by
# nothing. Repo-root invocation (no `cd`) so it resolves src/ and
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

# doc-lint reads every tracked Markdown file outside docs/specs/ and reports the
# backticked citations that no longer resolve — a path, a Python symbol, or a
# named skill/rule/command/agent. It is the only gate over prose nobody is
# editing, which is the prose that rots: review catches a false sentence in a
# changed file and cannot catch a true one that stopped being true. The asset
# roster comes from the same staging-and-gate path content-lint uses, so the two
# cannot disagree about what deploys. Repo-root invocation (no `cd`) so it
# resolves the tracked set and every cited path against the repo; it writes
# nothing and never invokes the installer. In `ci` — see the note there.
doc-lint:
	uv --project $(INSTALLER) run python -m installer.doc_lint_cli .

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

# ── grind (mirrors the ci-installer block one-for-one; enforced via the
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
