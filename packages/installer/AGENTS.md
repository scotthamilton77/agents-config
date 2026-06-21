# AGENTS.md — `packages/installer/`

Package-scoped guidance for the Python installer. The repo-root `AGENTS.md`
still applies; this file adds what is specific to this package. Unlike the
config content under `src/`, **this is real code with a real quality gate.**

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/installer/`, run the canonical
gate from the repo root:

```bash
make ci-installer   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage),
`pip-audit` (deps), `install.py --help` (entry verify). `make ci` adds
`actionlint`.

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

- **Python over Bash** — logic that needs testing lives in Python; shell stays a
  thin wrapper. This package replaced `scripts/install.sh`, which is now a
  thin `exec uv run --project packages/installer python -m installer` stub. The
  golden-master parity suite is retired.
- **Pure core, injected I/O.** Engine modules under `core/` are pure functions;
  all terminal interaction routes through the `IOPort` protocol (`TerminalIO`
  real, `ScriptedIO` test fake). No module calls `print`/`input` or imports
  `rich` directly.
- Layout: `core/` (engine: model, staging, sync, templates, …), `tools/`
  (per-tool adapters keyed by the `Tool` enum), `cli.py`, `config.py`.

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

Never invoke `scripts/install.sh` or `scripts/install.py` to "try it out" —
only the user runs the installer, and only when they explicitly ask. The gate's
`install.py --help` entry-verify is the only sanctioned automatic invocation.

## Reference

Architecture and the Epic A→H story sequence: `docs/architecture/installer/installer-design.md`.
