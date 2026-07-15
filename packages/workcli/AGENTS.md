# AGENTS.md — `packages/workcli/`

Package-scoped guidance for the `work` CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Unlike the config
content under `src/`, **this is real code with a real quality gate.**

`workcli` is the `work` facade CLI: it quarantines the issue-tracker backend
(bd) behind a stable, versioned JSON envelope contract — twelve verbs over an
injected `Backend` seam, typed error codes, and a bd adapter driven through a
subprocess port. See `docs/specs/2026-07-04-work-facade-cli-contract.md` for
the behavioral spec and `docs/plans/2026-07-10-workcli-transport-layer.md` for
the implementation plan.

A lifecycle layer (`src/workcli/lifecycle/`) sits over that same transport
seam: noun-templated `work create <noun>` plus the guarded verbs
`claim`/`release`/`deliver`/`plan`/`promote`/`reconcile` — status only ever
moves through a lifecycle verb (plus transport's `close`/`reopen`). See
`docs/specs/2026-07-05-work-lifecycle-and-facade.md` and
`docs/plans/2026-07-12-workcli-lifecycle-layer.md`. The finer capability-model
split (an honest server-authoritative `sync` no-op; read-only dep listing
surviving `supports_dep_types=False`) is deferred to the future non-bd (GH)
adapter bead — bd declares every `Capabilities` flag `True`, so nothing here
needs it yet.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/workcli/`, run the canonical
gate from the repo root:

```bash
make ci-workcli   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage), `pip-audit`
(deps), `work --protocol-version` and `work --help` (entry verify). `make ci`
runs this alongside `ci-installer`, `ci-prgroom`, and `lint-actions`.

Do **not** hand-pick a subset (e.g. `ruff check` alone). `ruff check` (linter)
and `ruff format` (formatter) are orthogonal — passing one says nothing about
the other. The `Makefile` is the single source of truth for the gate; mirror
it exactly. Faster inner loop while iterating: `make test-workcli` (pytest
only), but the full gate must pass before push.

## Toolchain

- `uv`-managed; Python ≥ 3.11.
- Run tools via `uv run …` from inside `packages/workcli/`, or the `make`
  targets from the repo root.
- Config lives in `pyproject.toml`: ruff (line-length 100), mypy
  `strict = true`, coverage `branch = true` / `fail_under = 90`.
- Zero runtime dependencies by design (stdlib only: argparse/json/subprocess/
  dataclasses) — keeps the `pip-audit` surface nil.

## Design principles for this package

- **Pure verb layer over an injected `Backend` seam.** The verb layer
  (`verbs/`) owns normalization, typed errors, and pre-checks; it never
  imports `subprocess` and never talks to bd directly. Adapters
  (`adapters/bd/`) own backend I/O and concept mapping only, and never print —
  all output flows back through the verb layer to the envelope.
- **Injected I/O everywhere.** `main()` accepts `argv`, `runner`, `out`,
  `err`, `sleep` as arguments — outside-world dependencies never reach a
  module global. Contract tests drive the CLI through `main()` with a
  `ScriptedBdRunner` fake (`tests/fakes.py`, from Task 2) in place of the real
  subprocess-backed `SubprocessBdRunner`; no live Dolt, no real subprocesses.
- **One JSON envelope on stdout, always.** Exit code mirrors `ok`
  (`envelope.py`, pinned contract). Argparse usage errors and unexpected
  internal exceptions both flow through the same envelope machinery — never a
  raw argparse stderr dump or an unhandled traceback to stdout.
- Layout: `cli.py` (argparse wiring + dispatch), `envelope.py` (error codes +
  emit helpers), `model.py` / `backend.py` (the `Backend` protocol and item
  shapes), `verbs/` (read/write/relations/syncing), `adapters/bd/` (the bd
  adapter: `runner.py` subprocess port, `parse.py`, `retry.py`, `backend.py`).

## Tests

- Behavioural, not tautological — each test pins a coded decision (an
  envelope shape, a dispatch path, a bd call-log assertion), never the
  language/stdlib.
- Contract tests for verbs run against `tests/fakes.py`'s `ScriptedBdRunner`
  (records every call, feeds scripted results) — never a real bd subprocess
  and never a live Dolt database.
- Coverage floor is 90% branch (enforced by `pytest --cov`); this package's
  sibling standard supersedes the repo's global 80%/70% default.

## Do not run bd mutations against the real DB from this package's tests

Contract tests exercise the `bd` adapter exclusively through the
`ScriptedBdRunner` fake. Golden `--json` captures for parser fixtures (Task 2)
are read-only and run from the **main repo root**, never this worktree — see
the plan's decision 14. Never invoke a mutating `bd` verb against the real
database while developing or testing this package.

## Real-bd integration suite (`make itest-workcli`)

`make itest-workcli` is the **sanctioned exception** to the rule above: it drives
the production `work` CLI against a **real, isolated** bd install (embedded Dolt
in a temp dir, bound via `BEADS_DIR` and an off-repo `tmp_path` + a git-repo
pre-flight guard, so it can never reach the repo's `.beads`). It catches bd-JSON
drift the hermetic `ScriptedBdRunner` fakes cannot. **Requirements & rules:**

- Needs `bd` on PATH; skips wholesale otherwise.
- **NOT** part of `make ci-workcli` / `make ci` — it needs the bd toolchain and
  runs ~40s+ serial. It is **pre-push discipline, not a merge gate**. `testpaths`
  in `pyproject.toml` pins the coverage-gated run to `tests/unit`.
- Runs serial (`-p no:xdist`) so the shared read-only install pays `bd init` once.
- Never weaken an integration assertion to make it pass: a failure is a real
  drift signal — fix the adapter/parser (and note the drift), or file it as
  discovered work, instead.

## Reference

Spec: `docs/specs/2026-07-04-work-facade-cli-contract.md`.
Plan: `docs/plans/2026-07-10-workcli-transport-layer.md`.
