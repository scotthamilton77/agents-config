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

- **Python over Bash** — logic that needs testing lives in Python; `scripts/install.sh` is a thin `exec uv run` stub that delegates here.
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

## Install receipt & prune adoption (clean-break, by design)

Pruning is driven by the **install receipt**
(`~/.config/agents-config/install-receipt.json`) — a record of what the installer
actually wrote — not a hand-maintained retired-glob list. Design:
`docs/specs/2026-06-25-install-receipt-pruning-design.md`.

**Cold-start is a deliberate clean break.** A *missing* receipt bootstraps empty:
the first receipt-era run prunes nothing and records what it installs; pruning
begins on the second run. There is intentionally **no migration** of pre-receipt
installs and **no hand-maintained retired-path list** — the receipt is the only
prune authority. A handful of paths retired before receipt adoption (removed
skills, renamed rules) may therefore linger on installs that predate the receipt
and never swept them under the old prune; that bounded, one-time, *cosmetic*
litter is accepted, not a bug. Reintroducing a retired-list migration would revive
the exact source→prune coupling the receipt exists to remove — don't, without
revisiting the spec's trust/ownership model. (A *corrupt* receipt is different: it
fails closed — prune disabled, file left untouched — so an unreadable state file
never silently strands other owners' entries.)

## Hash-aware pruning is file-level only (dirs are backup-and-delete, by design)

A **file** orphan is pruned only while its bytes still match the recorded
``sha256`` (a user-modified, type-drifted, or unreadable file relinquishes); this
check runs at scan time AND is re-checked at the deletion boundary (TOCTOU guard).
A **directory** orphan carries ``sha256: null`` (no single digest in v1), so it is
pruned whenever the path is still a real directory — there is intentionally **no
recursive content-drift protection**: a user who adds or edits files *inside* a
recorded skill/agent directory that later retires will have that tree removed (a
path-aware **backup is always taken first**, so it is recoverable). Cheap *type*
drift (a recorded dir path that is now a file or symlink) IS guarded — it
relinquishes. Recursive directory content-drift protection (a per-file manifest or
recursive digest) is deferred to `agents-config-fkewj` and is a schema change; do
not bolt a partial version onto v1 without that bead.

## Prune delete is re-validated, not atomic with the delete (accepted residual)

The deletion boundary re-validates each orphan (`revalidate` in
`_back_up_and_delete`) right before removing it, then backs up and unlinks/rmtrees.
A narrow TOCTOU window remains between that re-check and the `unlink`/`rmtree`: a
path swapped in by a *concurrent non-installer process* could be backed up and
removed. This is an **accepted non-severe residual**, not data loss — the **backup
is taken before the delete** (a raced-in replacement lands in `<namespace>-backup/`,
recoverable), and the whole install→prune→write runs under the **single-writer
advisory lock**, so no other installer run can race it. Closing the window fully
(atomically move-to-quarantine → validate the moved object → finalize, so validate
and delete act on the *same* filesystem object) is deferred to
`agents-config-o4kov`; it restructures the delete path and must not be bolted on
without that bead.

## Reference

Architecture: `docs/architecture/installer/installer-design.md`.
