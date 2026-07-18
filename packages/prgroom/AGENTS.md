# AGENTS.md — `packages/prgroom/`

Package-scoped guidance for the prgroom CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Unlike the config
content under `src/`, **this is real code with a real quality gate.**

`prgroom` is a deterministic PR-grooming CLI that supersedes the
`wait-for-pr-comments` and `reply-and-resolve-pr-threads` skills: it polls a
PR's review feedback, clusters it, dispatches fixes, pushes, replies, and
resolves threads — as locked, resumable lifecycle verbs rather than
model-driven prose. The `monitor-pr` skill drives it.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/prgroom/`, run the canonical gate
from the repo root:

```bash
make ci-prgroom   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage), `pip-audit`
(deps), `prgroom --help` (entry verify). `make ci` runs this alongside
`ci-installer` and `lint-actions`.

Do **not** hand-pick a subset (e.g. `ruff check` alone). `ruff check` (linter)
and `ruff format` (formatter) are orthogonal — passing one says nothing about
the other. The `Makefile` is the single source of truth for the gate; mirror it
exactly. Faster inner loop while iterating: `make test-prgroom` (pytest only),
but the full gate must pass before push.

## Toolchain

- `uv`-managed; Python ≥ 3.11 (`uv` auto-installs it first run).
- Run tools via `uv run …` from inside `packages/prgroom/`, or the `make`
  targets from the repo root.
- Config lives in `pyproject.toml`: ruff (line-length 100), mypy
  `strict = true`, coverage `branch = true` / `fail_under = 90`.

## Design principles for this package

- **Deterministic lifecycle over model judgment.** The grooming loop is a fixed
  pipeline of verbs (`cluster → fix → cap-guard → push → reply → resolve →
  rereview`) run under one advisory lock per PR ref. Control flow lives in code;
  agents are invoked only for the bounded fix/cluster steps.
- **Injected I/O, pure lifecycle.** External access (GitHub, git, the state
  store, escalation sinks) is reached through Protocols — `GhClient` (`gh/`),
  `GitClient` (`git/`), `Store` (`prsession/`), `EscalationSink`
  (`escalation.py`). Lifecycle functions take these as arguments and stay pure
  and testable; no module reaches a client from a global.
- **Typed, self-diagnosing errors.** Expected failures are modeled
  (`PrgroomError` tiers, precondition errors with a structured what/why/how
  stderr block, `GhNotFoundError` as a typed-but-not-fatal 404 signal).
  Exit codes follow `sysexits`.
- Layout: `cli.py` (the 12 verbs), `lifecycle/` (the run-loop, verb-error
  policy, quiescence), `prsession/` (state store + PR ref + memory), `gh/` /
  `git/` (Protocol adapters + fakes), `agent/` (cluster/fix dispatch), `config.py`,
  `errors.py`, `escalation.py`, `proc.py` (the single subprocess seam).

## Verbs

`poll`, `cluster`, `fix`, `push`, `rereview`, `reply`, `resolve`,
`resolve-escalated`, `wait`, `status`, `run`, `sweep`. `run` is the aggregate
loop; `status` emits the merge-gate envelope. **`sweep` (cross-PR autonomous
mode) is still a stub** — it exits the skeleton code (69), not implemented.

## Design-only subsystem — do not treat as built

The **fix↔verify subsystem** (per `docs/architecture/prgroom/`) is designed but
**0% implemented**: there is no `verify` step in the built pipeline, no `verify`
field on state, and no `[verify]` config. Do not wire code against it as if it
exists.

## Tests

- Behavioural, not tautological — each test pins a coded decision, never the
  language/stdlib. Drive lifecycle functions through the fake `gh`/`git`/`Store`
  adapters and assert against observed calls/state.
- Per-file Gh fakes are the default: each test module defines its own small
  `GhClient`-level fake tailored to what it asserts (`_RecordingGh`, `FakeGh`,
  …). Do not cross-import a sibling test module's fake. `tests/fakes.py` hosts
  exactly two shared fakes: the subprocess seam (`CommandRunner`) and
  `RecordingGh`, the reply-surface `GhClient` recorder shared by the reply
  test modules — it records every call and those tests assert exact call
  lists, so the permissive-default masking risk per-file fakes guard against
  does not apply. Don't grow it into a general-purpose Gh fake.
- Coverage floor is 90% branch (enforced by `pytest --cov`).

## Not installed by the installer

The installer does **not** currently manage prgroom's lifecycle — an earlier
bash `uv tool install` path was retired when `install.sh` collapsed to a stub,
and the Python installer has not re-adopted it. To use the CLI, `uv tool
install` it (or `uv run prgroom …`) from `packages/prgroom/` directly.

## Do not run grooming against a live PR automatically

Never invoke `prgroom run`/`push`/`reply`/`resolve` against a real PR to "try it
out" — those verbs mutate GitHub. The gate's `prgroom --help` entry-verify is
the only sanctioned automatic invocation.

## Observability channels

Every prgroom output belongs to exactly one of four channels, chosen by **who
must do what with it** — not by severity, not by module:

| Channel | Job | Writers | Reader |
|---|---|---|---|
| `usage.jsonl` (`append_usage`) | Durable, machine-readable, **per-attempt** dispatch telemetry: what ran, how long, what outcome | the dispatcher's `usage_hook` | post-hoc analysis; cost/routing tuning (sibling `spend.jsonl` holds per-**dispatch** cost) |
| `EscalationSink` (`escalation.py`) | **Human-judgment events**: something a human or external watcher must eventually act on — blocker dispositions, chain exhaustion, audit violations, lifecycle gates | `agent/fix.py`, `lifecycle/escalation.py` | operator / monitor-pr / future `bd` adapter |
| stdlib logging → stderr | **Operational diagnostics**: noteworthy but requiring no tracked action — config-key warnings, best-effort bridge failures, partial-fallback events | module-level `getLogger(__name__)`; root config in `main()` only | whoever watches the process (human or driving agent) |
| `warn` callbacks (`lifecycle/warn.py`) | Grandfathered injected-callable variant of the logging channel, used by lifecycle verbs as a test seam | existing lifecycle code only | same as logging |

Two standing rules: **stdout is reserved for contract output** (the
`status --json` envelope and the human `status` rendering); every diagnostic
goes to stderr. **No new channels**: a new observability need slots into one of
the four jobs above; new code preferring a diagnostic stream uses stdlib
logging, not a new `warn` plumbing.

## Reference

Architecture: `docs/architecture/prgroom/index.md`.
