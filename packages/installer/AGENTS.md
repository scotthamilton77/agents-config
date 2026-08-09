# AGENTS.md — `packages/installer/`

Package-scoped guidance for the Python installer. The repo-root `AGENTS.md`
still applies; this file adds what is specific to this package. Unlike the
config content under `src/`, **this is real code with a real quality gate.**

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/installer/`, run the canonical
gate from the root of **the tree you are working in**:

```bash
make ci-installer   # the full gate CI enforces
```

If you are on a worktree branch, that means the worktree root. The `Makefile`
targets `cd` into a path relative to the invoking directory, so running this
from the main checkout gates the main checkout's copy of the package and
reports green on code you did not change.

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage),
`pip-audit` (deps), `install.py --help` (entry verify). This is one of
several package gates `make ci` runs — read the `ci` target in the root
`Makefile` for the current membership rather than a copy here. Four of the
repo-root targets in that list — `spec-lint`, `content-lint`, `content-tests`,
`doc-lint` — are code this package owns (`core/spec_lint.py`,
`core/content_lint.py`, `core/content_tests.py`, `core/doc_lint.py` and their
respective CLI entry points), so a change to any of them needs `make ci`, not
just `make ci-installer`.

Do **not** hand-pick a subset (e.g. `ruff check` alone). `ruff check` (linter)
and `ruff format` (formatter) are orthogonal — passing one says nothing about
the other. The `Makefile` is the single source of truth for the gate; mirror it
exactly. Faster inner loop while iterating: `make test-installer` (pytest only),
but the full gate must pass before push.

## Toolchain

- `uv`-managed; Python ≥ 3.11 (`uv` auto-installs it first run).
- Run tools via `uv run …` from inside `packages/installer/`, or the `make`
  targets from the repo root.
- Config lives in `pyproject.toml`: ruff (line-length 100, strict rule set),
  mypy `strict = true`, coverage `branch = true` / `fail_under = 90`.

## Design principles for this package

- **Python over Bash** — logic that needs testing lives in Python; `scripts/install.sh` is a thin `exec uv run` stub that delegates here.
- **Pure core, injected I/O.** Engine modules under `core/` are pure functions;
  all terminal interaction routes through the `IOPort` protocol (`TerminalIO`
  real, `ScriptedIO` test fake). No module calls `print`/`input` or imports
  `rich` directly.
- Layout: `core/` (engine: model, staging, sync, templates, …), `tools/`
  (per-tool adapters keyed by the `Tool` enum), `cli.py`, `config.py`.
- **Namespace vocabulary is consolidated in `core/namespaces.py`** — `ALL` plus
  per-concern views (`TOOL_SCOPED`, `SHARED`, `SHARED_CARRIER`,
  `PLUGIN_TOOL_SCOPED`, `PRUNE`, `BACKUP`). Adding a namespace means adding it
  there *and* to each view it belongs in; a namespace carrying `.md` files also
  needs the merge registry. `scripts/install.sh` holds no namespace logic —
  it is a thin stub.

## Tests

- Behavioural, not tautological — each test pins a coded decision, never the
  language/stdlib/regex. Screen every test against "what coded decision does
  this pin?" before writing it.
- Unit tests drive the engine through `ScriptedIO`; assert against its
  transcript. Coverage floor is 90% branch (enforced by `pytest --cov`).
- **`# pragma: no cover` on `Protocol` method declarations is load-bearing.**
  With `--cov-branch`, coverage.py counts the inter-declaration branches on
  `...`-bodied `typing.Protocol` methods; removing the pragma drops branch
  coverage measurably (e.g. `core/io_port.py` 100% → 87%) even though the
  methods have no executable body. Keep them.

## Do not run the installer automatically

Only the user runs the installer, and only when they explicitly ask. The
prohibition is on the act of deploying, not on the names of the entry points,
so it covers `scripts/install.sh`, `scripts/install.py`,
`python -m installer`, `installer.cli.main()`, `install_pipeline`, anything
reaching `installer.core.clis`, and any route added after this paragraph was
written.
Deploying writes into the user's home directory and mutates their system-wide
`uv` tooling, so there is no such thing as a harmless trial run to "try it
out".

The gate's entry-verify is the sanctioned exception: `--help` on both entry
points, `scripts/install.py` and `python -m installer`. It parses the argument
table and exits before anything is staged.

To observe install behaviour instead, inject every seam. `main()` takes five —
`home`, `repo_root`, `io`, `cwd` and `cli_deploy` — and every one silently
defaults to the real thing: `home` to `Path.home()`, `repo_root` to this
repository, `cwd` to `Path.cwd()`, `cli_deploy` to the live `uv tool install`
subprocess port.

A partial injection is the more dangerous mistake, because it looks contained
and is not. Faking `cli_deploy` alone stops the `uv` mutation and still lets the
file-deploy half write into the live `~/.claude/`, and `--dry-run` is a
suppression inside the run rather than a boundary around it. `cwd` is the one
seam that reads rather than writes: it decides only a suggest-only notice, but
it reads the *invoking* directory to do it, so a run that leaves it defaulted
produces a transcript that depends on where it was launched from — and this
repository's own root satisfies that check.

Two worked examples, because no single suite supplies all five:
`tests/unit/test_cli_deploy_wiring.py` for a full non-dry-run call with `home`,
`repo_root`, `io` and `cli_deploy`, and `tests/unit/test_cli_project.py` for
`cwd`.

## Reference

Architecture: `docs/architecture/installer/installer-design.md`.
