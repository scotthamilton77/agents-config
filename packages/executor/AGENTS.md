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
- **The executor refuses what the fold would flag.** Every row mirrors its
  handler's preconditions in `pairing.py`, before either plane is touched. The
  executor is the runtime's single writer, so an event it can prove illegal is
  a caller's mistake, not something that happened: refusing keeps the log a
  record of transitions rather than of the executor's errors. For the
  tracker-first rows it is also correctness — they write to the tracker first,
  so an append the fold would flag leaves the two planes disagreeing with no
  retry that converges. Two preconditions are easy to miss. **Parked is a flag
  beside a status, not a status**: a scheduling park leaves the item `queued`,
  so a status-set check waves a parked item straight through, and the fold
  treats a parked item as absent for every handler but `item_enqueued`. And
  the fold does **not** check an event's PR against the item's own, so
  `pr-closed` does — a delayed notification naming a superseded PR would
  otherwise tear down the live review cycle.
  Duplicating the fold's tables is the cost, and `GrindRuntime.append`
  refusing an `applied: false` reply is the backstop that catches this table
  drifting from the runtime's.
- **An idempotent retry has to be the same command, not just the same verb.**
  `park` on an already-parked item is a retry only when the recorded reason
  matches; `pr-closed` only when the recorded *outcome* matches the requested
  `--next`. A mismatch is a request for something that never happened, so
  reporting success would claim a transition neither plane made — and it falls
  through to the precondition checks, which refuse it with the reason. Two
  traps here: a closure to `parked` leaves the item's review status alone and
  sets the park instead, so status alone would make such a closure refuse its
  own retry as parked; and on that path the runtime types the park from the
  closure's own free text, so the park it produced is what a retry is compared
  against. What is *not* compared is free text as text — the park note, and a
  closure reason that types nothing — because a retry may legitimately word it
  differently.
- **Idempotency evidence has to survive the transition it is about.** "This
  is already recorded" cannot be read off the status the transition produced,
  because the item moves on: an opened PR outlives `pr-open`, and re-appending
  from `waiting-human` is the worst case, since the fold *accepts* it and
  drags the item back to `pr-open`, ending a wait only an explicit resume
  should end. A silent state regression is worse than a flagged one.
  Symmetrically, the closed-PR ledger cannot carry the evidence alone: it is a
  set of closures with no counterpart for openings, so a PR closed once looks
  closed forever. The two rules read the pair — `pr-opened` asks whether the
  item is sitting where a closure leaves it, `pr-closed` asks for a ledger
  entry *and* an item no longer where a live PR puts it. Neither half is
  redundant; each covers the other's blind spot.
- **`ok: true` from the runtime is not "it applied".** The runtime's policy is
  accept-and-flag: an event that is well-shaped but illegal from the entity's
  current state is still written, as `applied: false` plus an anomaly record.
  `GrindRuntime.append` turns that into a typed failure. Reading only `ok`
  would let the executor report a pairing it did not enact. **Written and
  applied stay separate facts**: that failure carries `EVENT_WAS_WRITTEN`, so
  the report says `event_appended: true` and does not contradict the event
  log. The marker is internal to the port/enact seam and never reaches the
  envelope under that name.
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
- **One invocation, at most one sync, and the sync is owed by the mutation,
  not by success.** `TrackerSession` records a mutation only once its call
  returned — a write that raised did not land, and counting it would make the
  flush sync nothing. If a later step then fails, the landed write still owes
  this invocation its sync, so `_with_owed_sync` issues it before reporting the
  step failure; without that, a failed append strands the write on the local
  plane until someone happens to retry. A command that mutated nothing syncs
  nothing. A failed sync is repaired by running `work sync`, never by
  re-running the command that made the mutations.
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
- **Two PR-cycle cases the runtime's snapshot cannot answer.** Both come from
  the same gap: the snapshot records that closures happened, but not that
  openings did, and not what outcome a closure produced. The decision layer
  cannot sharpen a rule the state does not support, so each is bounded rather
  than solved, and each closes properly only in the runtime's fold.
  - An item closed to `in-progress` that then goes `waiting-human` sits in a
    status reachable both by a resume and by an opening, so a genuine reopen
    there reads as a retry and is not recorded. The direction is chosen for
    its failure mode — a skipped append shows up as `event_appended: false`
    and is recoverable, where appending silently ends a human wait. An
    openings ledger would close it.
  - A `pr-closed` retry is bound to its closure by "nothing has touched the
    item since", which the runtime's second-granular timestamps defeat when an
    intervening event lands in the same second (measured, not assumed). The
    residual is benign: the row writes nothing and calls no tracker verb, so
    the wrong answer is a success report for an outcome the item is in anyway
    — no append, no tracker call, no divergence. The ledger recording each
    closure's `next` would close it.
