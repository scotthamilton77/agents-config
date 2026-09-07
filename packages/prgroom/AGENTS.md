# AGENTS.md — `packages/prgroom/`

Package-scoped guidance for the prgroom CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Unlike the config
content under `src/`, **this is real code with a real quality gate.**

`prgroom` is a deterministic PR-grooming CLI: it polls a PR's review feedback,
clusters it, dispatches fixes, pushes, replies, and resolves threads — as
locked, resumable lifecycle verbs rather than model-driven prose.

**Almost nothing drives it today.** Charter D13 ("prgroom is carved, not
finished") scopes this package to slice S8. `post-verdict` is the one exception:
the `review-panel` skill's round procedure names it as the step that posts an
assembled verdict to a pull request. No deployed asset invokes any other verb and
no harness path depends on the grooming loop — read those lifecycle verbs as a
designed surface, not a running one.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/prgroom/`, run the canonical gate
from the root of **the tree you are working in** (the worktree root, if you are
on a worktree branch — the `Makefile` `cd`s relative to the invoking directory,
so a run from the main checkout gates code you did not change):

```bash
make ci-prgroom   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage), `pip-audit`
(deps), `prgroom --help` (entry verify). This is one of several package gates
`make ci` runs — read the `ci` target in the root `Makefile` for the current
membership rather than a copy here.

`make mutants-prgroom` is a separate, advisory gate: it runs the suite against
generated mutants of the modules a change touches and prints every mutant the
tests failed to kill. It answers what the coverage floor cannot — whether a
covered line is actually asserted. It is not part of `make ci-prgroom`.

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
  `HttpTransport` (`gh/`, for App-authenticated calls the `gh` CLI's own auth
  cannot carry), `GitClient` (`git/`), `Store` (`prsession/`), `EscalationSink`
  (`escalation.py`). Lifecycle functions take these as arguments and stay pure
  and testable; no module reaches a client from a global.
- **Typed, self-diagnosing errors.** Expected failures are modeled
  (`PrgroomError` tiers, precondition errors with a structured what/why/how
  stderr block, `GhNotFoundError` as a typed-but-not-fatal 404 signal).
  Exit codes follow `sysexits`.
- Layout: `cli.py` (the registered verbs), `lifecycle/` (the run-loop, verb-error
  policy, quiescence), `prsession/` (state store + PR ref + memory), `gh/` /
  `git/` (Protocol adapters), `agent/` (cluster/fix dispatch), `deps.py`
  (clock/randomness injection seam), `config.py`, `errors.py`,
  `escalation.py`, `proc.py` (the single subprocess seam).

## Verbs

`poll`, `cluster`, `fix`, `push`, `rereview`, `reply`, `resolve`,
`resolve-escalated`, `wait`, `status`, `run`, `approve`, `post-verdict`. `run` is
the aggregate loop; `status` emits the merge-gate envelope. `approve` and
`post-verdict` stand outside the grooming loop entirely — both reach GitHub under
the App identity, take no PR lock and touch no grooming state. `approve` submits
an approving review pinned to a head SHA the caller names; `post-verdict` submits
a comment-only review carrying a review round's verdict, pinned to the head that
verdict declares, with an inline comment at each finding that names a line the
diff touches. The two reviews are deliberately separate: a verdict says what a
round found and never that a change may merge.
`sweep` (cross-PR autonomous mode) is
design-of-record only (charter D13, "prgroom is carved, not finished",
forbids building it) and is not a registered command.

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
  exactly three shared fakes: the subprocess seam (`CommandRunner`);
  `RecordingGh`, the reply-surface `GhClient` recorder shared by the reply
  test modules — it records every call and those tests assert exact call
  lists; and `RouteTableHttp`, the App-HTTP seam recorder, which raises on any
  route it was not given and on any request not carrying the credential that
  request should be authorized by. That credential rule is shared rather than
  per-file precisely because it has to cover call sites nobody has written yet:
  a flow that drops or swaps a token is a defect no per-call assertion catches
  until someone remembers to write one. In all three the permissive-default masking risk
  per-file fakes guard against does not apply, which is the only reason they
  are shared. Don't grow any of them into a general-purpose fake — a
  `RouteTableHttp` route table stays in the test module that asserts it.
- Coverage floor is 90% branch (enforced by `pytest --cov`).

## Installed by the installer

The Python installer's CLI-deploy stage manages prgroom's lifecycle: it runs
`uv tool install` against `packages/prgroom/`, tracks the install in the
install receipt (digest-gated — a source change prompts an upgrade, a
docs/test change does not), and retires it via `uv tool uninstall` if the
registry ever drops it. The upgrade is consent-gated like every other
CLI-deploy decision: `--yes` or an interactive accept applies it; a decline or
a non-interactive run without `--yes` leaves the older receipt-owned install
in place rather than upgrading silently. Manual `uv tool install
./packages/prgroom` (or `uv run prgroom …` from `packages/prgroom/`) remains
possible for a no-installer or specific-checkout workflow.

## Do not run grooming against a live PR automatically

Never invoke `prgroom run`/`push`/`reply`/`resolve` against a real PR to "try it
out" — those verbs mutate GitHub. `approve` is under the same ban and then some:
it posts a review that a branch ruleset counts, so an exploratory run leaves an
approval standing on somebody's PR. `post-verdict` is banned on the same footing
— it posts a review and inline comments under the App identity, and a downstream
gate reads an App-posted verdict at the current head as the round's result, so an
exploratory run plants one nobody ran a round for. The gate's `prgroom --help`
entry-verify is the only sanctioned automatic invocation.

## Observability channels

Every prgroom output belongs to exactly one of four channels, chosen by **who
must do what with it** — not by severity, not by module:

| Channel | Job | Writers | Reader |
|---|---|---|---|
| `usage.jsonl` (`append_usage`) | Durable, machine-readable, **per-attempt** dispatch telemetry: what ran, how long, what outcome | the dispatcher's `usage_hook` | post-hoc analysis; cost/routing tuning (a per-**dispatch** `spend.jsonl` sibling is envisioned — `Dispatched.rung` is already shaped for it — but nothing writes it yet) |
| `EscalationSink` (`escalation.py`) | **Human-judgment events**: something a human or external watcher must eventually act on — blocker dispositions, chain exhaustion, audit violations, lifecycle gates | `agent/fix.py`, `lifecycle/escalation.py` | operator (stderr — the only sink `_build_sink` wires today; the design doc's §5 covers the built-but-unselectable file adapter and the unbuilt bd adapter) |
| stdlib logging → stderr | **Operational diagnostics**: noteworthy but requiring no tracked action — config-key warnings, best-effort bridge failures, partial-fallback events | module-level `getLogger(__name__)`; root config in `main()` only | whoever watches the process (human or driving agent) |
| `warn` callbacks (`lifecycle/warn.py`) | Grandfathered injected-callable variant of the logging channel, used by lifecycle verbs as a test seam | existing lifecycle code only | same as logging |

Two standing rules: **stdout is reserved for contract output** (the
`status --json` envelope and the human `status` rendering); every diagnostic
goes to stderr. **No new channels**: a new observability need slots into one of
the four jobs above; new code preferring a diagnostic stream uses stdlib
logging, not a new `warn` plumbing.

## Reference

Architecture: `docs/architecture/prgroom/index.md`.
