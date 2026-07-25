# Tier 1 executor seam — design

**Date:** 2026-07-24
**Scope:** `agents-config-9k9.1.4` (S9c), `.1.3` (S9b), `.1.6` (S9e), `.1.7` (S9f)
**Charter:** `docs/specs/2026-07-21-harness-rework-way-forward.md` (D10, D11, D14, D16, D20; slice S9)
**Predecessor:** `SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md` (V1; its AC-V1.3 table is the authoritative substrate inventory)
**Status:** design record. The seam decision and §5 escalations are settled and binding on
`.1.4`, `.1.3`, and `.1.6`, none of which are implemented. **§2.4 is superseded — read the
correction below instead.**

**§2.4 is void (2026-07-25).** `.1.7` and `agents-config-9k9.6` are both closed. The
section's reasoning about `work sync` versus the git hooks is correct as far as it goes,
but the exposure it argues for does not exist: `bd config show` reports `export.auto =
false` and `import.auto = false`, both set in `.beads/config.yaml`, so the hooks are inert
in both directions and `.beads/issues.jsonl` never moves data either way. Settled
consequence, binding on `.1.4`/`.1.6`: **workcli, grind, and the executor need no awareness
of beads hook configuration or of the JSONL plane.** No detection capability is warranted —
there is no action any of them would take differently.

**One correction to §2.1, already applied inline:** the join key `work_id or id` is
grounded in intent rather than in a fold defect as of `agents-config-9k9.1.17` (PR #397).
It is still not total — the spec permits ROOT-assigned run-local slugs (`disc-<n>`) as item
ids, so `.1.4` must treat "no tracker handle yet" as a first-class case rather than an
error path.

---

## 0. Verdict in brief

The executor decision layer lives in a **new package, `packages/executor/`**, which
talks to `grind` and `work` **only through their CLI JSON envelopes**, behind two
injected ports. grind stays a fact-emitter with zero external coupling; workcli stays
a tracker facade that records outcomes and counts nothing.

Attempt *counts* are facts and belong in grind's fold. Attempt *budgets* are numbers
the executor seeds into grind's `config`, exactly as `stalemate_risk_round` already
works. Exhaustion *enforcement* — parking with `budget-exhausted` — is executor-only.
That split is not a compromise; it is the same split `review_stalemate_risk` already
ships, and V1 quotes the spec confirming it ("stalemate *declaration* stays with the
review skill's rule").

Three of the four items are implementable now. **1.7 is not** — its stated premise is
void, not merely inaccurate: `work sync` and the git hooks operate on different planes
(see §2.4, corrected).

**Decisions taken 2026-07-25.** The seam (option A) is **approved**: new
`packages/executor/`, console script `executor`. E2 is **approved** — `work ready` and
`work claim` gain a read-only `parked_stale` block, so D10's "cannot be bypassed" is
mechanically true. E3 stands as recommended (dependency edge, plus a facade-gap note
for the axis asymmetry). E4 is **withdrawn** — it rested on the same categorical error
as 1.7. E5 is minted as `agents-config-9k9.1.18`.

**One correction to §2.1 below:** the join key's justification is wrong. Seeded items
lack a `bead` because of a fold defect, not by design — `agents-config-9k9.1.17`, now
a `blocks` edge on 1.4.

---

## 1. The seam decision

### 1.1 The constraint, stated precisely

Two ends refuse the job, for different and both-correct reasons:

- **grind refuses to decide.** `conditions.py:5-9` is a hard seam with a test behind
  it: `test_conditions.py:471` asserts the first word of every emitted condition name
  is not in `IMPERATIVE_VERBS`, and that set is almost verbatim the executor's verb
  list. grind imports no workcli and shells to nothing.
- **workcli refuses to remember.** The S2 spec, S2-D2: "the budget numbers themselves
  (2 CI-fix attempts, 1 rebase) are executor policy (S9), not facade logic — the
  facade records the outcome, it never counts attempts." workcli is stateless across
  calls by construction; it holds a `Backend` and returns envelopes.

Both refusals are load-bearing. grind's purity is what made V1 return FIT at all
("the runtime is clean because nobody finished coupling it"). workcli's is the D11
portability guarantee. Neither should be relaxed to save a package.

### 1.2 Options considered

**A. A new package that shells to both CLIs.** New `packages/executor/`, its own uv
project, its own `make ci-executor` gate, installed onto PATH like `work` and
`grind`. Talks to both through their documented JSON envelopes behind Protocol ports
with fakes in tests.

**B. A new package that imports `grind` as a library and shells to `work`.** Same
shape, but a path dependency on `packages/grind` (precedented: `packages/pdlc`
depends on `packages/holding-place` by path). Gets grind's typed `State` for free.

**C. A skill / prose layer driving both CLIs.** An agent reads `grind status`, decides,
calls `work park`. Zero new code.

**D. Extend grind with a carefully non-imperative decision module** (`grind.executor`),
sibling to `conditions.py` and outside the lock's reach.

**E. Extend workcli.** The facade grows a `work next` / budget-aware surface.

### 1.3 Choice: **A**, with a named fallback to B

**Rejected C** on the repo's own first design principle: "Code over Prose — anything
code can do better than agents, we move out of prose and into code helpers." A
budget counter maintained by an agent reading a dashboard is precisely the
babysitting the prime directive exists to delete, and it cannot be tested. It is also
what the old harness did.

**Rejected E** because it inverts D11. The facade's job is to make the tracker
backend swappable; giving it executor memory means a GH-issues adapter has to
reimplement attempt budgets. S2-D2 already forbids it in words.

**Rejected D** because grind's zero-external-coupling is currently a *checkable*
property of the package ("no imports of workcli, no shelling to bd/gh/git" — V1,
AC-V1.2). The moment a module inside `packages/grind` shells to `work`, that property
becomes a per-module convention rather than a package invariant, and the next agent
that needs "just one" tracker call inside `fold.py` has a precedent to cite. The
package boundary is the cheapest enforcement mechanism available and it costs one
`pyproject.toml`.

**Chose A over B** on four grounds:

1. The `work` side *must* be a subprocess regardless — importing `workcli.lifecycle`
   would bypass the facade's own envelope/capability contract, which is the thing D11
   makes portable. Given one port is a subprocess, two ports of one style beats a
   hybrid.
2. Both CLIs were built as programmatic contracts: exactly one JSON envelope on
   stdout, exit code carrying only command failure. `grind`'s docstring
   (`cli.py:5-9`) and workcli's protocol version exist for exactly this consumer.
3. It keeps grind installable and usable standalone, which is what `9k9.1.5` is
   currently landing.
4. `packages/prgroom` already establishes the "typed client wrapping a subprocess"
   pattern (`gh`/`git` clients, retained under D13).

**Fallback to B** if the parse layer for `grind status --full` turns out to be more
than ~150 lines of typed mapping. That is a measurable trigger, not a preference:
if reproducing grind's `State` shape in the executor costs more than a path
dependency, take the path dependency and keep only `work` as a subprocess. Record
the switch as a design note; do not litigate it mid-slice.

### 1.4 How the choice keeps both seams intact

| Seam | How it survives |
|---|---|
| `conditions.py` HARD SEAM | grind gains one new *fact* condition (`attempt_budget_spent`) and one new *fact* event (`fix_attempted`). No condition name is an instruction; the existing lock test is extended to cover the new name explicitly (see §2.2, note on the test's fixture). grind still never calls anything. |
| grind's zero external coupling | Unchanged, and now enforced by a package boundary rather than by nobody having tried. |
| "the facade records the outcome, it never counts attempts" | workcli is untouched by 1.3 and 1.4. The only proposed workcli change in this whole document is the read-only surfacing question in 1.6, which is an escalation, not a decision I am taking. |
| D11 "the harness never speaks bd" | The executor's test suite pins the absence of `bd` in its own source (1.4's stated `remove_when`). |

### 1.5 Package shape

```
packages/executor/
  pyproject.toml            # dist name `executor`, console script `executor`
  src/executor/
    __init__.py, py.typed
    envelope.py             # ExecutorError + the one-envelope-on-stdout invariant
    ports.py                # TrackerPort(Protocol), RuntimePort(Protocol)
    work_client.py          # TrackerPort over subprocess `work`
    grind_client.py         # RuntimePort over subprocess `grind`
    model.py                # typed parse of the two envelope shapes
    pairing.py              # the one table: execution transition -> tracker verb
    budget.py               # 1.3 executor half
    next_work.py            # 1.6
    cli.py
  tests/unit/               # both ports faked; no binaries required
  tests/integration/        # real `work` + `grind`; `make itest-executor`
```

`make ci-executor` mirrors `ci-workcli`/`ci-grind` exactly (lint, format-check,
typecheck, coverage, audit, entry-verify) and joins the top-level `ci` target.

Two concrete footguns the client layer must absorb, both verified in the current code:

- **`grind check` exits 1 when stale while emitting `ok: true`** (`cli.py:161-163`).
  A naive `check_returncode()` reads a healthy staleness verdict as a crash.
- **grind's envelope carries no protocol version**; workcli's does
  (`{"protocol": "1.3", "ok": ..., "data": ..., "error": ...}`). The parse layer must
  be defensive about grind's shape. Adding a protocol version to grind's envelope is
  a reasonable follow-on bead; it is **not** in Tier 1 and should not be smuggled in.

---

## 2. Per-item design

### 2.1 `agents-config-9k9.1.4` (S9c) — work-verb call sites

**Builds:** `packages/executor/` itself (skeleton, CI gate, both ports), plus the
pairing layer. This item is the one that creates the package; everything else in
Tier 1 lands inside it.

**The join key.** grind `Item.bead` is populated only by `discovered_work`
(`fold.py:636-638`), where it is `None` when it would equal the item id
("optional metadata, carried only when it differs from `item`"). Seed-created items
(`fold.py:175-181`) never set it.

> **Corrected 2026-07-25, twice.**
>
> **(a) The field is being renamed.** `bead` is the tracker *backend's* noun, and D11
> quarantines that backend behind the facade — grind must know only work item IDs. It is
> `work_id` as of `agents-config-9k9.1.19`. So the join key below reads
> `tracker_id(item) = item.work_id or item.id`. grind never executed `bd` and still
> doesn't; this was vocabulary in the persisted schema and public JSON, not coupling.
>
> **(b) The justification was wrong.** The spec gloss quoted above governs
> `discovered_work`'s optional field **only**. The `grind_created` payload specifies
> lanes carrying a queue of items with tracker ids, and the seed handler simply never
> reads the field — a fold defect (`agents-config-9k9.1.17`, edged behind 1.19 and
> `blocks` on 1.4). The join key still works, but on the defect rather than on intent,
> and its behaviour changes the day the defect is fixed. **Land 1.19, then 1.17, then
> write the join key against the fixed behaviour and the new field name.**

So the binding is (field name as corrected above):

```
tracker_id(item) = item.work_id or item.id
```

which means **an executor-seeded grind uses tracker ids as grind item ids** and the
`bead` field exists only for the discovered-work case where they diverge. State this
in the module docstring; it is the single most drift-prone assumption in the slice.

**The pairing table** (`pairing.py`) — one table, exhaustively tested:

| Execution transition | Tracker verb |
|---|---|
| `item_started` | `work claim <id>` |
| `item_parked`, **failure** axis | `work park <id> --reason <same code> --note …` |
| `item_parked`, **scheduling** axis | *none* — zero tracker mutations |
| park exit, cause fixed | `work redispatch <id>` |
| park exit, PR abandoned | `work abandon <id>` |
| `item_merged` | `work close <id>` (close-walk is `close`'s default, S2-D5) |
| `item_done` | *none* |
| any tick with ≥1 mutation | exactly one `work sync` at tick end |

Three of those rows are decisions, not transcription:

- **The axis is the routing rule.** Post-S9a, grind's failure-axis reasons are
  member-identical to `work park --reason`'s vocabulary (verified:
  `ci-failure|merge-conflict|approval-required|bot-declined|budget-exhausted` on both
  sides). So a failure-axis park crosses the boundary **untranslated** — the test
  should assert that no translation map exists, because a map is where drift would
  live. grind's scheduling axis (`discovered-work`, `later-wave`, `deferred`) has no
  counterpart in `work park`, and correctly so: those are sequencing decisions about
  work that never failed. A scheduling park issues **zero** tracker writes.
- **`item_merged` is the close trigger, not `item_done`.** V1 flagged this
  mismatch (grind treats `done` as terminal and `merged` as intermediate; D10 says
  "Closed = merged"). Both agree on the load-bearing behaviour — grind's blocker edges
  resolve on `merged` *or* `done` — so pick `merged` and say so at the call site
  rather than discovering it later.
- **Ordering rule between the two systems.** Intents the executor is about to enact
  (claim, park, redispatch, abandon) go to **the tracker first**, then grind; a failed
  tracker call leaves grind un-advanced and the operation retryable. Facts about the
  outside world that already happened (`pr_opened`, `item_merged`) go to **grind
  first**, then the tracker; the merge is real whether or not the tracker heard about
  it. This is the concrete mechanism by which "execution state and tracker state drift
  apart" is prevented, and it is what the tests should pin.

**What its tests prove:**

- Parametrized over the pairing table: every transition the executor can emit maps to
  exactly one tracker action or an explicit `None` — a new transition with no row
  fails the test rather than silently doing nothing.
- Failure-axis park → `work park --reason` with a byte-identical code; scheduling-axis
  park → the fake tracker's call log is empty.
- Tracker-first ordering: with the fake tracker raising, no grind event is appended.
  World-fact ordering: with the fake tracker raising on `close`, the grind
  `item_merged` event *is* appended and the failure surfaces for retry.
- Join key: `bead=None` uses `item.id`; `bead` set uses `bead`.
- Batching: N mutations in one tick → exactly one `work sync`.
- **`remove_when` discharge:** a source-scan test asserting the string `bd` appears
  nowhere as a command in `packages/executor/src/**` — the "test pins the absence of
  bd" the admission record names.

### 2.2 `agents-config-9k9.1.3` (S9b) — attempt budgets

**This is the sharpest tension in the set, and it resolves cleanly. Here is the
resolution, not a hedge.**

Three things are being conflated by the phrase "budget counting":

| Thing | Nature | Home |
|---|---|---|
| "3 CI-fix attempts have been recorded for item X" | **fact**, derived from events | grind's fold |
| "the CI-fix budget is 2" | **config**, supplied by the caller | grind's `config`, seeded by the executor |
| "therefore stop, and park with `budget-exhausted`" | **policy** | `packages/executor/budget.py` |

The bead says the counters live in "folded state" and that is correct, because a
count of recorded events is exactly what a fold is for. It does not constitute
orchestration policy for the same reason `stale_item` does not: grind is doing
arithmetic over facts against a caller-supplied threshold and reporting the result.
The precedent is not analogical, it is structural — `stalemate_risk_round: 3` is
already a caller-supplied cap that a condition compares against, and V1 quotes the
spec confirming the runtime "computes the arithmetic and defers enforcement
entirely."

The line grind must not cross is **acting**. It does not park anything, does not
call anything, and its condition name carries no instruction.

**grind-side changes (all inside `packages/grind`):**

1. **New event `fix_attempted`** — payload `{item, kind, note?}` where `kind` is
   `ci-fix|rebase`. Validator in `payloads.py` (unknown `kind` → command error,
   nothing appended). The executor asserts this event **before** attempting the fix,
   so a crash mid-attempt still consumes budget; a budget that only counts completed
   attempts is not a budget.
2. **`Item.attempts: AttemptLedger`** (`model.py`) — `ci_fix: int = 0`,
   `rebase: int = 0`. Fold handler in `fold.py` using the existing `_item` helper, so
   an attempt on a parked or absent item is an accept-and-flag anomaly like every
   other handler.
3. **Ledger lifetime = one PR cycle.** Cleared by `pr_closed` (mirroring
   `round_history`, which is cleared there for exactly this reason — "a new PR must
   not inherit an old stalemate") and by `item_enqueued` (leaving the parking lot is
   the deliberate act that grants a fresh window).
4. **`DEFAULT_CONFIG` gains `ci_fix_budget: 2`, `rebase_budget: 1`** — D10's initial,
   tunable numbers, in the same place as the existing two timers and repeat-detector.
5. **New condition `attempt_budget_spent`** — fields
   `{item, kind, attempts, budget, since}`, gated on `_ACTIVE_REVIEW_STATUSES` and
   non-parked, non-terminal items, same shape as `review_stalemate_risk`. First word
   `attempt` is not in `IMPERATIVE_VERBS`; note that `fix` **is** in the set, so the
   condition may not be named `ci_fix_budget_*`. The lock test splits on `[_\s]` and
   checks only the first word, so this is a naming constraint on the leading token,
   but do not test the edge of it.
6. **`serialize.py`** — `attempts` joins `_item_json` so `status --full` carries it.
   Renderer change is *optional and deferred*: it adds diff surface for no test value.

**executor-side changes (`executor/budget.py`, lands after 1.4's skeleton):**

Reads the condition (or recomputes from `attempts` + `config`; prefer the condition,
so exhaustion has one definition), and on exhaustion emits `item_parked` with
`reason=budget-exhausted` and calls `work park --reason budget-exhausted` through the
pairing layer. Note `budget-exhausted` is failure-axis/human-category, and
`fold.py:594` anomalies a failure-axis park on an item with no PR — correct, because
budgets only exist inside a PR cycle.

**What its tests prove:**

- Two `ci-fix` attempts fold to `attempts.ci_fix == 2`; a third is still recorded
  (grind counts, it does not cap).
- `fix_attempted` on a parked item → anomaly, ledger unchanged.
- `pr_closed` clears the ledger; `item_enqueued` clears it; nothing else does.
- Boundary: the condition fires at `attempts == budget`, not at `budget - 1`, and
  carries both numbers as evidence.
- The condition is absent for parked, terminal, and non-review-status items.
- The new name is added to the `IMPERATIVE_VERBS` lock test's name set **explicitly** —
  that test only checks the names its fixture happens to emit plus the statically
  named `item_unblocked`, so a new condition is not covered for free.
- Replay determinism is unchanged (existing suite).
- Executor: at budget, the third attempt is refused, `item_parked` is emitted, and
  `work park --reason budget-exhausted` is called on the fake — in that order per the
  §2.1 ordering rule (tracker first).

### 2.3 `agents-config-9k9.1.6` (S9e) — surfacing the parked report

**"What is the open-new-work interaction today?" — answered honestly.**

There are three, and only one of them is buildable in Tier 1:

1. **`work ready`** — the real, existing, machine-and-human call for "what can I pull
   next." It exists today and is called today.
2. **A human "what's next" surface** — does not exist. The `whats-next` skill is
   archived; re-admission is bead `9k9.1.14`, which is not Tier 1 and whose own
   description says its `collect.py` queries `bd` directly in violation of D11.
3. **The executor's dispatch loop** — does not exist and needs S7's dispatch brief.
   Tier 2.

So the answer is: **there is a real call site today, and it is `work ready`.** 1.6 is
not blocked on Tier 2 — but its stated `remove_when` ("the report appears at every
open-new-work interaction and **cannot be bypassed**") is only half satisfiable by
executor-side code, because a caller can always run `work ready` directly.

**What to build (executor half, uncontroversial):** `executor next [--stale-days N]`
composes `work parked --stale-days N` **first**, then `work ready`, and emits one
envelope with `parked_stale` ahead of `ready`. If the parked call fails, the ready
list is **suppressed** — D10's price of pulling new work is reviewing stuck work, and
a silently-degraded report that still hands out new work inverts the whole point.

**What is escalated (workcli half):** whether `work ready` and `work claim` should
carry a read-only `parked_stale` block in their envelopes, which is the only place
the "cannot be bypassed" property is actually achievable. See §5, E2. Note this would
*not* violate S2-D2 — it joins two reads and counts nothing — but it is a facade
surface change and S2-D4 explicitly punted the *decision* to S9, so S9 should make it
deliberately rather than by implication.

**What its tests prove:**

- `executor next` calls `work parked` before `work ready`, ordered, on the fake.
- The envelope carries the stale report even when it is empty (absence of parked work
  is a reported fact, not a missing field).
- Zero mutations: the fake tracker's mutation log is empty for the whole command.
- Parked-call failure → ready items are absent from the envelope and the command
  reports the degradation.
- `--stale-days` passes through to the facade (the threshold lives in `work parked`,
  default 7 per S2-D4; the executor does not reimplement it).

### 2.4 `agents-config-9k9.1.7` (S9f) — beads git hooks

**Corrected 2026-07-25 against `docs/primers/BEADS_GITHOOKS_PRIMER.md`. This item's
premise is void — categorically, not partially. Do not implement it as written.**

`work sync` runs `bd dolt commit` + `bd dolt push`, and `--pull` runs `bd dolt pull`
(`adapters/bd/backend.py:313-347`). It never runs `bd export` or `bd import`. The two
mechanisms are orthogonal:

```
work sync : Dolt DB  <->  Dolt remote
git hooks : Dolt DB  <->  issues.jsonl (the git-tracked snapshot)
```

So no number of explicit `work sync` call sites can make the export/import hooks
redundant — `work sync` does not touch `issues.jsonl` in either direction.
Retirement-by-call-site is impossible in principle.

| Hook | What it actually does | Retirable? |
|---|---|---|
| `pre-commit` | exports Dolt → `issues.jsonl` **and stages it**, so tracker state lands in the *same commit* as the code change | **No.** No `work sync` call site reproduces that atomicity. |
| `pre-push` | **documented no-op placeholder** — runs only a chained `.old` hook, no bd logic | **Yes**, at zero cost and zero benefit. The bead and this document's first draft both wrongly called it an export hook. |
| `post-merge` | imports `issues.jsonl` → Dolt after pull/merge | **No.** With import off, the next auto-export overwrites the file with the older local view — silent loss of teammates' issues. |
| `post-checkout` | same import, branch switches only | **No**, same reason. |
| `prepare-commit-msg` | appends `Executed-By: <agent>` when `BD_ACTOR` is set | Not sync at all. Out of scope for this bead; decide on forensics merits or not at all. |

**The real work, which is what the bead should have been about.** workcli must be
correct on beads installs that may or may not have hooks, whose behaviour varies with
config: `export.auto`, `export.git-add`, `import.auto` (all default true, all
disableable), plus `export.interval` (60s minimum between auto-exports, so an export
can be skipped as too recent), the two error policies, and `export.path`. Install
target is `.git/hooks/` or `.beads/hooks/` via `core.hooksPath`, so presence is not a
single path check. Uninitialized Dolt exits 3 as a *non-blocking warning*, so a hook
can "succeed" having done nothing.

**Consequence for the approved seam:** the executor can mutate the tracker, call
`work sync`, receive a truthful `synced: true` for the Dolt plane, and still leave the
repo's git-tracked `issues.jsonl` stale — because that plane is maintained only by a
hook that may be absent, disabled, or interval-skipped. Nothing in the harness
observes this today. Config asserting a behaviour is not the behaviour happening.

**Disposition: awaiting Scott's choice** among (a) re-scope to workcli
capability-detection + retire only the no-op `pre-push`, (b) split into a detection
bead plus a trivial `pre-push` chore and close this one void, or (c) close void and
record the stale-JSONL risk as an accepted facade gap. Full analysis is recorded as a
note on `agents-config-9k9.1.7`. `agents-config-9k9.6` is superseded either way.

**E4 is withdrawn.** Auto-syncing on mutating `work` verbs would sync the *Dolt* plane
and still not make the export/import hooks redundant. Do not mint it as framed.

---

## 3. Ordering and parallelism

**Wave 0 — clear the decks (already in flight).** `9k9.1.9` (`--dir` resolution),
`9k9.1.8` (`status --handoff`), `9k9.1.5` (installer `CLI_PACKAGES`). All three touch
files Tier 1 wants:

- 1.9 and 1.8 → `packages/grind/src/grind/cli.py`, `verbs.py`, and 1.8 very likely
  `serialize.py`. **1.3 also touches `serialize.py`.** Land 1.8 before dispatching
  1.3, or accept a rebase on one file.
- 1.5 → `packages/installer/src/installer/core/clis.py` (`CLI_PACKAGES` is a 2-tuple
  today). Registering `executor` touches the identical three lines. **Do not let 1.4
  register the executor CLI until 1.5 has merged**; carry it as a follow-up commit or
  a one-line PR.

**Wave 1 — two agents, genuinely parallel, zero shared files:**

| Agent | Item | Files |
|---|---|---|
| A | **1.4** — package skeleton, ports, clients, pairing | `packages/executor/**` (all new), `Makefile` (+`ci-executor`), `.github/workflows/*` if CI needs the target |
| B | **1.3 grind half** — event, ledger, config, condition, serializer | `packages/grind/src/grind/{model,payloads,fold,conditions,serialize}.py` + tests |

They share nothing. The only collision is `Makefile`, and only if B also adds a
target — it does not (`ci-grind` exists).

**Wave 2 — serialized after their inputs:**

| Item | Waits on | Files | Collision |
|---|---|---|---|
| **1.3 executor half** (`budget.py`) | 1.4 merged, 1.3 grind half merged | `packages/executor/src/executor/budget.py`, `cli.py` | `cli.py` with 1.6 |
| **1.6** (`next_work.py`) | 1.4 merged | `packages/executor/src/executor/next_work.py`, `cli.py` | `cli.py` with 1.3's executor half |

1.3-executor and 1.6 each add one module plus one subcommand registration in
`cli.py`. That is an additive, ~3-line collision in a single file. Two options, pick
one and tell the agents: run them in parallel and accept one trivial rebase, or
serialize 1.3-executor → 1.6. Given 1.3 is P1 and 1.6 is P2, **serialize** — it costs
one wave and removes the only ambiguity.

**Wave 3 — 1.7**, only after Scott picks a disposition (§2.4). Not schedulable as
written.

**Net dispatch plan** (corrected 2026-07-25):

```
done:     wave 0 landed as PRs #390, #392, #391 (CI green, unmerged)
first:    1.17  <- fold defect; blocks 1.4's join key
then:     1.4  ||  1.3-grind          <- two agents, parallel, no shared files
then:     1.4's installer registration (1 line, after #391 merges)
then:     1.3-executor
then:     1.6  (executor half + the approved work ready/claim parked_stale block)
later:    1.18 (grind envelope protocol version, after #390/#392 merge)
blocked:  1.7  (premise void, awaiting disposition)
```

**One split to authorize explicitly:** 1.3's admission `remove_when` is "budgets are
enforced and exhaustion parks with the typed reason", so 1.3 is not closable until
its executor half lands. Splitting it across two waves means the bead stays open
through wave 1. That is correct and should not be worked around by weakening the AC.

---

## 4. Blocked-on-Tier-2 honesty

**Not blocked:** 1.4, 1.3, 1.6. None of them needs S6's verdict schema, S7's dispatch
brief, or S8's merge-eligibility evaluator. They are the tracker-state and
budget-state halves, and V1 was explicit that the tracker substrate is "fully ready
post-S2."

**A caveat I will not smooth over:** the *value* of 1.4 and 1.6 is capped until a
dispatcher consumes them. `executor next` is a real command a human can run, and the
pairing layer is real code with real tests, but until S7 lands there is no loop
calling them on its own. Building them now is still right — they are the pieces the
dispatcher will need, they are testable in isolation, and they retire the
"reconcile grind and the tracker by hand" failure the moment anyone uses the
executor manually. But do not report Tier 1 as "the executor loop works." It is the
executor loop's tracker interface and its budget arithmetic, with no driver.

**Genuinely blocked: 1.7**, and not on Tier 2 — on a premise error no upstream slice
will fix, because `work sync` and the hooks never touched the same plane. See §2.4 as
corrected.

**Largest useful subset available before S6/S7/S8:** 1.4 in full, 1.3 in full
(both halves), 1.6's executor half in full and its workcli half pending E2. That is
three of four items complete and one re-scoped.

---

## 5. Escalations

**E1 — Package name and binary name. DECIDED 2026-07-25: `packages/executor/`, console
script `executor`.** `exec` is unusable (shell builtin). `loop` collides
conceptually with the `/loop` skill. `drive`/`pilot` read nicely but match nothing in
the charter's vocabulary, which says "executor loop" throughout. One-word veto
accepted; this is the cheapest decision in the document and blocks agent A's first
commit.

**E2 — Does the parked/staleness report belong in `work ready`'s envelope? DECIDED
2026-07-25: yes — option 1 below is approved.** 1.6 therefore carries a workcli PR
adding the read-only `parked_stale` block to `work ready` and `work claim`, alongside
`executor next` as the composed surface. *Original ranking retained for its reasoning:*

1. **Yes — add a read-only `parked_stale` block to `work ready` and `work claim`
   envelopes** (and keep `executor next` as the composed surface). This is the only
   design where D10's "surfaced at the start of **any** open-new-work interaction" is
   mechanically true. It does not violate S2-D2: it joins two reads, counts nothing,
   and decides nothing. Cost: a facade surface change and a workcli PR inside a slice
   that is otherwise executor-only.
2. Executor-only, and accept that `work ready` bypasses the report. Cheaper, honest,
   and leaves the `remove_when` undischarged — 1.6 would close with a known hole.
3. Do nothing until a dispatcher exists. Rejected: it defers the one D10 obligation
   that is fully buildable today.

I recommend 1 but will not take it unilaterally, because S2-D4 deliberately routed
this decision to S9 and it changes a facade contract the charter calls the harness's
only tracker interface.

**E3 — 1.7 cannot be parked with a typed reason, and that is itself a finding.**
`work park --reason` accepts only the five **failure-axis** codes
(`ci-failure|merge-conflict|approval-required|bot-declined|budget-exhausted`).
Post-S9a, *grind* has a scheduling axis (`later-wave`, `deferred`, `discovered-work`)
but the facade does not. So "this work is premature, revisit after X" is not
expressible as a park through the facade — the correct primitive is a `blocked-by`
dependency edge, which `work dep add` supports. **Recommendation:** use the edge, and
record the vocabulary asymmetry as a facade-gap note on `agents-config-9k9` per D11.
Whether the facade should grow a scheduling axis to match grind's is a real question
and a separate bead; I would not open it inside S9.

**E4 — WITHDRAWN 2026-07-25.** It proposed auto-sync on mutating `work` verbs as 1.7's
unblocker. That rests on the same categorical error as the bead: auto-syncing the *Dolt*
plane does not make the *`issues.jsonl`* export/import hooks redundant. Do not mint it
as framed. See §2.4 as corrected.

**E5 — grind's envelope has no protocol version. MINTED as
`agents-config-9k9.1.18`**, deferred out of Tier 1 as recommended: it touches `cli.py`,
which PRs #390 and #392 are already editing.
