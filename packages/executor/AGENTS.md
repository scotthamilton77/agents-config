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
ports.py  →  state.py  →  rules.py  →  pairing.py  →  enact.py  →  cli.py
(the only     (parses)    (the two     (composes)    (acts)      (envelope)
 subprocess)               matrices)
```

- **`ports.py` is the only module that shells out**, and everything it spawns
  is one of two console scripts. Above it, the whole package takes ports as
  arguments — which is what lets the unit suite run with both faked and neither
  binary present.
- **`pairing.py` is pure, and thin.** It reads a `RunState` and returns a
  `Plan`, never touching a port — which is what makes every row's pairing
  assertable without a fake. Each builder is the same four steps against
  `rules.py`: resolve the arguments, pick the row, ask whether the exact
  command is already recorded, and otherwise check the row's preconditions
  before building a payload.
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

## The three matrices

`S9T1-D12` closes the pairing universe over *which* verb maps to which event
and which tracker call. It answers none of the three questions each row also
has to, and every one was discovered a cell per review round before being
enumerated. **`src/executor/rules.py` is the source of truth**; the tables
below are the orientation, and `tests/unit/test_rules_matrices.py` walks all
three from the table itself.

**Adding a guard means adding a cell, never a check at the call site.** That
is the whole point of the enumeration — scattered guards are what let the same
bug arrive eight times wearing different arguments.

### Matrix A — the source-state matrix

Which item states a row may fire from. `parked` is a separate column because
it is a flag beside a status, not a member of the set: a scheduling park
leaves an item `queued`, so a status set alone waves a parked item through,
and the fold treats a parked item as absent for every handler but
`item_enqueued`.

| row | legal source statuses | parked | also requires |
|---|---|---|---|
| `start` | queued | forbidden | — |
| `park:failure` | queued, in-progress, pr-open, in-review, waiting-human, blocked | forbidden | a PR reference |
| `park:scheduling` | as above | forbidden | — |
| `redispatch` | any | **required** | a lane |
| `abandon` | any | **required** | a PR reference, matching `--pr`, a lane |
| `pr-opened` | in-progress, waiting-human | forbidden | — |
| `pr-closed` | pr-open, in-review, waiting-human | forbidden | a PR reference, matching `--pr` |
| `merged` | pr-open, in-review, waiting-human | forbidden | a PR reference |
| `done` | merged | forbidden | — |

Two of the "also requires" entries have no counterpart in the fold. **The fold
compares an event's PR against nothing**, so only `PR_MATCHES_ITEM` stops a
delayed notification for a superseded PR being recorded as fact — and for
`pr-closed`, tearing down the live review cycle. It is strict about absence:
an item holding no reference matches no PR. A requirement named "the PR
matches" that passed vacuously when there was none would be a trap for the
next row to use it, which is how `pr-closed` came to accept an invented
closure against a `waiting-human` item that had never opened one. Rows wanting
the clearer `E_NO_OPEN_PR` for that case pair it with `PR_REFERENCE`, which is
why the two stay separate.

Why refuse at all, when the fold would flag it anyway: the executor is the
runtime's single writer, so an event it can prove illegal is a caller's
mistake rather than something that happened, and refusing keeps the log a
record of transitions. For the tracker-first rows it is also correctness —
they write to the tracker before appending, so an append the fold would flag
leaves the two planes disagreeing with no retry that converges.

Duplicating the fold's sets is the cost. `GrindRuntime.append` refusing an
`applied: false` reply is the backstop that catches this table drifting, and
it names the fold's own reason when it fires.

**Two axes are deliberately absent and must stay absent.** An item absent from
the fold is refused before a row is chosen, by `RunState.item`. And a
run-local `disc-<n>` id is **never** a refusal (`S9T1-A6`) — handle routing
happens in `enact`, and such an item enacts normally with no tracker call and
an `unpromoted` entry. Both have a walk in the matrix test guarding against a
later cleanup folding them in.

### Matrix B — the command-identity tuple

Which arguments make a re-invocation *the same command*. `S9T1-D6`'s skip
fires **only on a full-tuple match** against what the fold records; a partial
match is a different command, enacted or refused on the merits and never
silently skipped.

| row | identity | what the fold records of it |
|---|---|---|
| `start` | item | in-progress and unparked |
| `park:*` | item, reason | parked, with the recorded reason |
| `redispatch` | item | not parked — the whole postcondition |
| `abandon` | item, pr | a *cleared* PR reference plus a closure for that PR |
| `pr-opened` | item, pr | the reference, and the item not sitting where a closure leaves it |
| `pr-closed` | item, pr, next | a ledger entry, the item's position, and nothing having touched it since |
| `merged` | item, sha | merged/done, with the merged-ledger commit |
| `done` | item | done and unparked |

What is **not** in an identity is as load-bearing. Free text is compared only
where the runtime derives something typed from it: the park *note* is never
compared, nor is a closure reason that types nothing — a retry may legitimately
word either differently — but on `pr-closed --next parked` the runtime types
the park from that text, so the park it produces is.

Three traps worth keeping:

- **Evidence has to outlive the transition it is about.** An opened PR
  outlives `pr-open`, so a status-only check re-appends from `waiting-human` —
  where the fold *accepts* it and drags the item back, ending a wait only an
  explicit resume should end. A silent state regression is worse than a
  flagged one.
- **A closure to `parked` leaves the review status alone** and sets the park
  instead, so comparing status would make such a closure refuse its own retry.
- **`abandon`'s evidence is the cleared reference, and nothing weaker.**
  Position, the surviving reference and ledger membership alone were each
  tried and each matches a state another command produces — an ordinary
  `pr-closed --next queued` looks identical. Until B7 lands the evidence is
  unreachable and the row refuses instead.

### Matrix C — the payload rules

Which fields the fold requires **non-empty** in the event a row appends, and
what an empty one becomes. Same standing as the source states: a payload the
fold rejects is a precondition, and on a tracker-first row it is the one that
can diverge the planes — an empty park note parks the tracker and only then
has the append refused.

| row | field | an empty value becomes |
|---|---|---|
| `park:*` | `note` | the reason code |
| `abandon` | `reason` (the closure's) | `abandoned` |
| `pr-closed` | `reason` | a refusal |
| `merged` | `sha` | a refusal |

Whether a field has a default is per row and documented, not a house style: a
park note has a natural stand-in and a merge commit does not. A default that
itself computes to empty is a **table bug** and fails loudly, and the set of
fields a rule may fill is closed — a rule quietly writing to the wrong field
would produce an event that passes every other check.

### One agreement check that is not a matrix

Matrix A and C are about what the *runtime's* fold will accept, and can both
be decided before either plane is touched. The tracker has one rule that
cannot: `work park` on an already-parked item reports the **existing** stint
and mints nothing. So `TrackerSession` compares the reason the facade returns
against the one asked for, and refuses before recording the mutation — with
nothing written and no sync owed. Discarding that reply would append the new
reason to the runtime while the tracker kept the old one, and **neither plane
could detect it**, since each stays internally consistent. Never let a facade
reply go unread on the assumption that a successful call means the requested
mutation.

## More rules that are load-bearing, not stylistic

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
