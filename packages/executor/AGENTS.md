# AGENTS.md — `packages/executor/`

Package-scoped guidance for the `executor` CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Unlike the config
content under `src/`, **this is real code with a real quality gate.**

`executor` is the decision layer above the grind runtime and the `work` facade.
The runtime reports facts and the facade records tracker outcomes; this package
is the only place that pairs them. One executor verb appends at most one
runtime event and enacts at most one tracker verb, and the set of legal pairs
is closed.

Reference: `docs/specs/2026-07-25-executor-seam-s9-tier1.md` — decisions
`S9T1-D1`…`D12` and the acceptance criteria every test cites.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/executor/`, run the canonical gate
from the root of **the tree you are working in** (the worktree root, if you are
on a worktree branch — the `Makefile` `cd`s relative to the invoking directory,
so a run from the main checkout gates code you did not change):

```bash
make ci-executor
```

It runs, in order: `ruff check`, `ruff format --check`, `mypy --strict src`,
`pytest --cov` (90% branch floor), `pip-audit`, and `executor --help`. Do not
hand-pick a subset — the linter and the formatter are orthogonal. Faster inner
loop: `make test-executor`.

This package is in the installer's `CLI_PACKAGES` registry, so it deploys onto
PATH via `uv tool install`. A change to `pyproject.toml` or `src/**` shifts the
source digest and forces a reinstall on the next installer run.

## Architecture

```
ports.py  →  state.py  →  pairing.py  →  enact.py  →  cli.py
(the only     (parses)     (decides)      (acts)      (envelope)
 subprocess)
```

- **`ports.py` is the only module that shells out**, and everything it spawns
  is one of two console scripts. Above it, the whole package takes ports as
  arguments — which is what lets the unit suite run with both faked and neither
  binary present.
- **`pairing.py` is pure.** It reads a `RunState` and returns a `Plan`; it
  never touches a port. That is what makes every row's pairing assertable
  without a fake.
- **Refusals are raised, never returned as a degenerate plan.** A caller that
  forgot to check a flag would otherwise enact half a row.

## Rules that are load-bearing, not stylistic

- **The pairing table is the mutation universe.** `PAIRING_TABLE` in
  `pairing.py` is the whole set of legal (executor verb → runtime event →
  tracker verb) triples. A `tracker` of `None` is the table's explicit *none*,
  not a missing entry. Port **reads** appear in no row and are unrestricted —
  reading the fold for an item's lane or PR is not a mutation.
- **The CLI surface is closed and the gap is named.** `EXECUTOR_VERBS` is the
  contract's verb universe; `PENDING_VERBS` names the ones no slice has wired
  yet. The parser is built *from* `_VERB_PARSERS`, so there is one list, not
  two that drift. Wiring a pending verb means adding its parser entry and
  deleting its name from `PENDING_VERBS` — the totality test measures the gap
  rather than ignoring it.
- **A park reason crosses untranslated.** There is no mapping table in this
  package and there must not be one. The failure axis lives in
  `packages/contracts/park-reasons.toml`; this package is its third reader, and
  its suite asserts against that file rather than a transcription. The
  scheduling axis is runtime-native and issues zero tracker writes — the facade
  deliberately has no vocabulary for it.
- **"No tracker handle" is a success value, not an error.** An item whose id
  matches the run-local slug grammar and which carries no work id has no
  tracker handle at all. Every tracker column for it reads *none* and the item
  is reported under `unpromoted`. Minting a tracker item for it takes placement
  judgment this package does not have. Never turn that path into a refusal, a
  warning, or a synthesised id.
- **Ordering is per row, not per call site.** Intents lead with the tracker so
  a failure leaves the runtime un-advanced and the command retryable;
  world-facts lead with the runtime so the fact survives a tracker failure.
  `Order` lives on the row for exactly that reason.
- **The state check gates the append, never the tracker call.** When the
  runtime already records a transition, the event is not re-appended and the
  tracker side *is* re-issued. That asymmetry is what lets a response-lost
  retry converge instead of duplicating one side.
- **One invocation, at most one sync, issued last.** `TrackerSession` records a
  mutation only once its call returned — a write that raised did not land, and
  counting it would make the flush sync nothing. A refusal syncs nothing at
  all, and a failed sync is repaired by running `work sync`, never by re-running
  the command that made the mutations.
- **Every failure carries a code from the closed set.** `ErrorCode` is the
  contract. `E_USAGE` and `E_INTERNAL` extend the spec's enumeration and are
  documented as such in place; adding a third is a contract change.

## Tests

- Behavioural. Each test pins a coded decision and cites the AC it discharges
  in the module docstring.
- `tests/unit/fakes.py` holds both port fakes plus the state builders. The
  builders default to the boring case; a test states only the fact it is about.
- `ScriptedRunner` answers by argv prefix and **raises on an unmatched call** —
  a benign default would let a test pass while the port asked the outside world
  something the test never anticipated. Do not add a fallback.
- `conftest.py` carries a suite-wide autouse guard: no tracker mutation may
  ever name a run-local slug. It is autouse deliberately — a per-test
  assertion would only cover the tests that remembered to make it.

## Known gaps, deliberately

- **No dispatch loop.** Nothing calls these pieces in sequence yet. This layer
  answers "what does verb X pair with"; it does not decide when to run X.
- **`attempt` and `next` are unwired** (slices C and N). They are in
  `EXECUTOR_VERBS` and in `PENDING_VERBS`, so the closed universe is already
  stated.
- **`abandon` emits an `item_enqueued` closure the current runtime fold
  ignores.** The runtime's validator accepts the extra key and the fold drops
  it until slice B lands; the event is recorded either way, which is what
  makes the two slices independently mergeable.
