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
- **The runtime counts and decides; this package enacts.** Whether a budget is
  spent is the runtime's `attempt_budget_spent` condition and nothing else
  (`S9T1-C3`). This package keeps no counter, and its own arithmetic never
  reaches a decision — see "the budget split" below for the one number it does
  compute and why that is not an exception.
- **A park reason crosses untranslated.** There is no mapping table in this
  package and there must not be one. The failure axis lives in
  `packages/contracts/park-reasons.toml`; this package is its third reader, and
  its suite asserts against that file rather than a transcription. The
  scheduling axis is runtime-native and issues zero tracker writes — the facade
  deliberately has no vocabulary for it.

## The matrices

`S9T1-D12` closes the pairing universe over *which* verb maps to which event
and which tracker call. It answers none of the three questions each row also
has to, and every one was discovered a cell per review round before being
enumerated. **`src/executor/rules.py` is the source of truth**; the tables
below are the orientation, and `tests/unit/test_rules_matrices.py` walks all
three from the table itself. A fourth table, the attempt budgets, sits beside
them and is documented after.

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
| `attempt:under-budget` | every status but merged and done | forbidden | an **open** PR |
| `attempt:exhausted` | as above | forbidden | an **open** PR |

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

**`OPEN_PR` is strictly stronger than `PR_REFERENCE` and the two are not
interchangeable.** A closure leaves the reference behind and marks it closed,
deliberately: a failure-axis park describes a PR that already failed to merge,
so a reference is what it needs, while an attempt claims to be fixing one that
is still live. Reading a reference as an open PR charges a budget against a
cycle that is over. The flag is also the field whose degraded reading
*authorises*, so `ItemView.pr_open` is strictly `closed: false` on a numbered
reference — absent, null or mistyped is not open. It fails closed by value
rather than by raising, unlike `parked` and `work_id`: a reference whose
openness cannot be read is exactly the "no open PR" these two rows refuse for,
and raising would take down every other verb over a field only they consult.

**The two `attempt` rows share every refusal edge**, so a parked item or an
item with no open PR is refused with zero events and zero tracker calls on
either side of the budget (`S9T1-C4`). Only what happens past those edges
differs.

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
| `redispatch` | item | not parked, **and** still where the enqueue left it |
| `abandon` | item, pr | a *cleared* PR reference plus a closure for that PR |
| `pr-opened` | item, pr | the reference, and the item not sitting where a closure leaves it |
| `pr-closed` | item, pr, next | a ledger entry, the item's position, and nothing having touched it since |
| `merged` | item, sha | merged/done, with the merged-ledger commit |
| `done` | item | done and unparked |
| `attempt:under-budget` | item, kind | **nothing — the row has no skip** |
| `attempt:exhausted` | item, reason | **nothing — the row has no skip** |

**A row may declare that no state authorises a skip, and the two `attempt`
rows do.** That is a decision, not a missing cell, so it is stated in the
table (`_no_recorded_transition`) and walked by the matrix suite over the
whole status grid — a row that merely lacked a probe would look identical to
one whose probe nobody wrote.

- Under budget, `fix_attempted` folds into a **count, not a transition**. Two
  identical invocations are two attempts, and the fold counts past the budget
  rather than capping (`S9T1-B2`), so nothing in the state can tell a
  response-lost retry from a genuine second attempt. The pre-charge picks the
  safe side: over-counting spends one more attempt inside a bound that exists
  for the purpose, where under-counting removes the bound. **This is the one
  append in the package that is deliberately not idempotent** — do not "fix"
  it by giving the row a recorded probe.
- At exhaustion the park *is* a transition, but the condition that selects the
  row is absent for a parked item, so the row is unreachable once its park is
  on record. The reachable answer to "already exhausted?" is the under-budget
  row's parked refusal, which is `S9T1-C5`'s no-double-park.

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
| `attempt:exhausted` | `note` | the reason code (`budget-exhausted`) |
| `abandon` | `reason` (the closure's) | `abandoned` |
| `pr-closed` | `reason` | a refusal |
| `merged` | `sha` | a refusal |

Whether a field has a default is per row and documented, not a house style: a
park note has a natural stand-in and a merge commit does not. A default that
itself computes to empty is a **table bug** and fails loudly, and the set of
fields a rule may fill is closed — a rule quietly writing to the wrong field
would produce an event that passes every other check.

**The tracker is pinned before it is mutated.** `WorkTracker` performs the
facade's documented consumer handshake — `work --protocol-version`, major
pinned — once per adapter, before any verb. For a mutating consumer the timing
is the point: checking a reply is too late, because an incompatible facade may
already have acted. An unreadable version is refused alongside a mismatched
one; an unverified handshake is no handshake.

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

A park reply carrying no usable reason is a **failure**, not agreement — the
reply is the only evidence of which reason the tracker holds, so reading an
unusable one as "no disagreement" re-opens the divergence outright.

### The fourth table — the attempt budgets

`ATTEMPT_KINDS` is the `--kind` vocabulary and, per kind, the runtime config
key its budget is seeded under plus the fallback for an unseeded run. It
answers what a budget *is*. It never answers whether one is spent.

**Where each number in an `attempt` envelope comes from, and why:**

| path | `attempts` | `budget` |
|---|---|---|
| under budget | the folded ledger, **plus this command's charge** | `ATTEMPT_KINDS` against the snapshot's `config` |
| at exhaustion | the condition's | the condition's |

Three rules hold that together:

- **The decision is the condition and only the condition.** The refusal fires
  because `attempt_budget_spent` is present for this `(item, kind)`, never
  because a comparison here said so. A fresh process that has observed nothing
  refuses correctly, and a ledger sitting past the configured budget still
  proceeds when the runtime reported no condition. Both are pinned.
- **The refusal reports the condition's own numbers**, so the report and the
  fact it acted on cannot disagree.
- **The under-budget path is the one place this package computes a budget**,
  because no condition fires there and `S9T1-D11` requires the field. It reads
  the runtime's own `config` out of the *same* `status --full` reply as the
  fold — one snapshot, so a count and a threshold can never straddle an
  append — and mirrors the runtime's fallback rule, including that a seeded
  `0` is a legal budget meaning "spend nothing on this kind". Drifting this
  table from the runtime's is the one way the two planes can report different
  numbers for one config.

`attempts` on the proceeding path is the ledger **as the command leaves it**:
the append is a pre-charge, so by the time a caller reads the envelope the
attempt is spent, and reporting the count as the command found it would
describe a ledger that no longer exists.

### A refusal that enacts first

`Plan.refusal` is a typed failure a plan carries *through* its enactment
rather than instead of it. The exhaustion row parks the item on both planes
and only then refuses the attempt (`S9T1-C2`), so the refusal has to survive a
successful enactment. It lives on the plan and `enact` raises it — never the
CLI — so a dispatcher calling `enact` directly cannot enact the park and read
the result as a proceed. The full enactment report rides the error: a refusal
that mutated has to say what landed and whether it synced, or a caller cannot
tell it from a refusal that touched nothing.

That is also why the exhaustion envelope syncs while every other refusal does
not. The sync is owed by the mutation, not by success.

**A verb block is a conclusion, and only a conclusion carries one.** `_report`
folds `Plan.report` in on exactly two paths — the success return and that
refusal — and never on a step that failed partway. `proceed` is computed
before the append, so republishing it into the envelope that reports the
append's failure would authorise precisely what did not happen; the fold does
not count a flagged attempt either. `event_appended` and `tracker_called` are
outcomes and stay on every path; the verb block is not.

## More rules that are load-bearing, not stylistic

- **A degraded value that authorises is a fault, not a default.** The parser
  degrades a wrong-typed field to `None` and the decision above fails closed —
  a missing PR reference refuses, a missing lane refuses. Four reads invert
  that and so refuse instead: `parked` (a malformed one makes an unparked item
  look parked, waving `redispatch`/`abandon` into a tracker-first mutation),
  `work_id` (falling back to the item id sends a tracker write named by a
  fallback), the facade's park reply (no reason means no evidence of
  agreement), and the runtime's whole **`conditions` block** (absent or null
  reads as "no budget spent", which switches enforcement off). Before adding a
  lenient read, ask which way its degraded value points.

  **Ask it of an absence too, not only of a wrong type.** The `conditions`
  case is the one that got past a first pass: absent looked like a benign
  "nothing to report" until the question was put the other way round — the
  runtime already encodes that as the empty list, so absent can only be a
  reply this package cannot read. `parse_state` takes `conditions` as a
  **required** argument for that reason; a default would be a value meaning
  "the runtime said nothing about budgets", and there is no such reading.
  It fails every verb rather than only `attempt`: a runtime that cannot
  produce its own documented reply shape has not established that any of this
  package's readings of it hold.

  **And ask it of a skip.** Inside the conditions list, an unknown condition
  *name* is read past — the runtime's vocabulary is free to grow and this
  parser must not break on an addition — but an entry that is not an object,
  or that names no condition at all, is **not** an unknown condition. It is
  one this parser cannot classify, and it could be the very fact it is looking
  for. Elsewhere in this file a dropped entry fails *closed*: the ledger reads
  drop what they cannot answer with, and an unanswerable probe then refuses a
  skip. Here it fails *open*. Which way a drop points is a property of what
  reads the result, not of the parser, so decide it per read.
- **Every failure raised after the outside system may have acted carries what
  it may have done.** This is one rule, and four review rounds found it four
  times before it got written down. The runtime appends *before* it replies
  and the facade writes *before* it replies, so an `ok: true` reply from an
  appending or mutating verb means the effect is durable however the call ends
  after that — a wrapper dying, an unreadable `applied`, a park reply naming
  no reason. `EVENT_WAS_WRITTEN` and `TRACKER_WRITE_LANDED` are how a refusal
  says so; without them the report contradicts the event log, or the owed sync
  is skipped and a real write is stranded.
  When it is unknown whether the effect happened, **mark it** — syncing an
  idempotent replay is harmless, stranding a write is not. Mark it *un*happened
  only where something proves that, and **a well-formed `ok: false` is not
  proof**: the runtime appends before it folds, persists and renders, so its
  catch-all reports a failure over an event already on disk; the facade's park
  writes status, label and note in sequence, so a later step failing leaves an
  earlier write applied. Both report a readable error envelope. The two things
  that *do* prove it are never having launched, and a `park` reason mismatch —
  the differing reason itself proves the facade's replay branch ran, and that
  branch mints nothing.
  In an *error* envelope, therefore, `event_appended: true` means **may have
  been written — treat the log as authoritative**. Over-claiming costs a log
  check; under-claiming costs a duplicate append or a stranded write.
  **A reply that cannot be read at all is the strongest "unknown" there is** —
  a timeout can land mid-write, a wrapper can truncate the output of a call
  that finished — so the marker attaches at the decode boundary too, not only
  to parseable replies. The one exception is a call that never launched:
  `CommandResult.launched` is `False` only for a failure before exec, which
  *proves* no child process ran, and the marker is withheld. A timeout is
  `launched=True`, since the process ran; exit code alone cannot tell the two
  apart, which is why that flag exists at all.
  The marker follows the *verb*: reads (`state`, `staleness`) and `sync` claim
  nothing, because neither writes.
  Adding a raise below the port boundary means asking what the far side may
  already have done.
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
- **`next` is unwired** (slice N). It is in `EXECUTOR_VERBS` and in
  `PENDING_VERBS`, so the closed universe is already stated.
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
