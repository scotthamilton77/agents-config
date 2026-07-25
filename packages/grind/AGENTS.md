# AGENTS.md — `packages/grind/`

Package-scoped guidance for the event-sourced grind runtime. The repo-root
`AGENTS.md` still applies; this file adds what is specific to this package.
Unlike the config content under `src/`, **this is real code with a real
quality gate.**

`grind` is the event log and materialized-state engine under the pipeline
executor loop (charter D14): an append-only `events.jsonl` is the source of
truth, `fold(events) -> State` is the pure transition function that turns it
into a `state.json`-shaped snapshot, and `conditions(state, now)` reports the
level facts derived from that snapshot.

**This package emits facts; it does not decide.** Dispatch, fix/rebase
budgets, review triggering, merge eligibility, and every tracker call belong to
the decision layer above it — grind imports no tracker facade, shells out to no
`gh`/`git`, and assumes no filesystem beyond a caller-supplied `--dir`. That
boundary is the verified basis for keeping this runtime as the executor
substrate (`SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md`).

**CLI:** `[project.scripts]` declares `grind = "grind.cli:entry"`, shipping six
subcommands — `create`, `log`, `status`, `check`, `render`, `finish`. The
installer registers grind in `CLI_PACKAGES`
(`packages/installer/src/installer/core/clis.py`), so the `grind` binary is
installed onto PATH alongside `work` and `prgroom`, receipt-tracked and pruned
on retirement. Every command emits exactly one JSON envelope on stdout and
exits non-zero only on a command error — except `grind check`, whose exit 1
carries the staleness verdict itself.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/grind/`, run the canonical
gate from the repo root:

```bash
make ci-grind   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage), `pip-audit`
(deps), and `verify-entry-grind` — which asserts the console script resolves
and the CLI root parses by running `grind --help`. `make ci` runs this alongside
`ci-installer`, `ci-prgroom`, `ci-workcli`, and `ci-vizsuite`.

Do **not** hand-pick a subset (e.g. `ruff check` alone). The `Makefile` is
the single source of truth for the gate; mirror it exactly. Faster inner
loop while iterating: `make test-grind` (pytest only), but the full gate
must pass before push.

## Toolchain

- `uv`-managed; Python ≥ 3.11.
- Run tools via `uv run …` from inside `packages/grind/`, or the `make`
  targets from the repo root.
- Config lives in `pyproject.toml`: ruff (line-length 100), mypy
  `strict = true`, coverage `branch = true` / `fail_under = 80` — a single
  combined floor over branch-enabled coverage, not a line/branch pair. It is the
  lowest floor of any package here: `installer`, `prgroom`, `workcli`, and
  `vizsuite` all gate at 90.
- Zero runtime dependencies by design (stdlib only: `json`/`dataclasses`/
  `typing`) — keeps the `pip-audit` surface nil.

## Design principles for this package

- **`fold()` is pure and time-independent.** It never touches its input,
  never does I/O, and always returns a fresh `State` for a given event
  sequence — delete-and-refold is the runtime's entire recovery story, so
  nondeterminism here is a correctness bug, not a cosmetic one (see
  `tests/unit/test_replay_determinism.py`).
- **Status is derived, never asserted.** There is no `status_changed` event;
  every event handler in `fold.py` computes the entity's new status from its
  current status and the event's payload. Blocked/unblocked is doubly
  derived — from blocker edges, recomputed on every relevant transition, not
  read off any event field directly.
- **Anomaly policy is accept-and-flag, not reject.** An event illegal from
  the entity's current status, or naming an unknown item/lane, or of an
  unknown type, is still folded in: `fold()` never raises for a bad event
  (it may raise `LogCorruptionError` in `log.py` for a genuinely corrupt
  *non-tail* log line, which is a different failure class — see "Torn tail"
  in the spec). Every anomaly path records an `AnomalyRecord`, an ERROR
  `Observation`, and an auto-raised `AttentionEntry` — the three always
  travel together (see `fold._anomaly`).
- **Layout.** Core: `model.py` (the `State` shape and its typed sub-records —
  `Item`, `Lane`, `ItemReview`, `ParkingEntry`, …), `fold.py` (the transition
  table and every event handler), `derive.py` (read-side projections needing no
  wall clock, e.g. lane status), `conditions.py` (the time-dependent level
  facts and the one transition condition). I/O: `log.py` (JSONL parsing with
  torn-tail tolerance, and `fold_log()` composing parse + fold), `store.py`
  (the write path — torn-tail repair, append, read-back), `jsonio.py` (strict
  JSON decoding, non-finite constants refused), `serialize.py` (`State` ->
  `state.json` and the `status` views). Boundary: `cli.py` (argparse wiring and
  dispatch), `verbs.py` (the command bodies), `payloads.py` (per-type payload
  validation), `envelope.py` (`GrindError`), `resolve.py` (`--dir`
  resolution). Projections: `render.py` (`dashboard.html`), `handoff.py`
  (`status --handoff`).
- **A condition is a fact with evidence, never an instruction.** Its name
  states what is true and its fields carry the evidence — no "nudge the lane",
  no "escalate the review". `conditions.IMPERATIVE_VERBS` is the convention
  lock a test asserts every condition name against; acting on a condition is
  the decision layer's call, not this package's.
- **Payload validation lives at the CLI boundary, not in the fold.** Per spec
  ("parse once, trust inward"), `fold()` trusts that a well-formed event's
  payload fields are shaped correctly; `payloads.py` rejects malformed payloads
  before they ever reach the log, as a command error that appends nothing. The
  fold's tolerance is about *structural* garbage (missing keys, wrong JSON
  types, unknown event types) — it degrades gracefully rather than crashing,
  but it doesn't second-guess a well-typed field's business validity beyond
  what the transition table itself encodes.

## Judgment calls worth knowing about

- **`item_blocked` accepts a self-loop on an already-`blocked` item.** The
  transition table's literal legality matrix (spec: "Item status legality")
  marks `blocked` x `blocked` as absent (anomaly), but the same section's
  prose says "a later `item_blocked` for the same item replaces its full
  edge set... how ROOT re-scopes or drops a dependency" — a capability that
  is unreachable if `blocked` x `blocked` is illegal, since any item with an
  unresolved edge is already `blocked` by definition. This package treats
  the edge-replace semantics as authoritative and allows the self-loop (see
  `fold._BLOCKABLE`'s comment). If this reading is wrong, the fix is a
  one-line set change plus removing the "re-scope" test in
  `tests/unit/test_fold_blocking.py`.
- **`item_waiting_human` is legal from `blocked`, not just the four
  "normal" active statuses.** Easy to miss reading the transition table
  informally — row `blocked`, column `waiting_human` is `waiting-human`, not
  a dash. A human can be asked to intervene on a dependency that isn't
  resolving on its own.
- **Lane status excludes `done` items when the lane still has in-flight
  work.** "All done -> done; any in flight -> the most advanced active
  state" reads ambiguously for a mixed lane (one item done, one still
  queued): naively taking the max-rank status across *all* items would
  report `done` for a lane that's barely started. `derive.lane_status`
  computes the "most advanced" rank only among non-`done` items, falling
  back to `done` only when every item in the lane is.
- **`pr_closed.reason` shares a field name with the park vocabulary and not
  its contract.** It is a free-text closure note, validated as any non-empty
  string, while `item_parked.reason` is a closed enum. On the `next: parked`
  path this package runs the text through the same lookup: if it names a
  vocabulary member the park is typed with it (demoting a legal reason to
  prose would lose it silently), otherwise the park is untyped and the text
  becomes the note. An untyped park is *absent* from both axes, not
  ambiguously on one.
- **The park vocabulary has two axes and one exit.** `PARK_REASONS`
  (`model.py`) is the single table; `axis` and `category` are `@property`
  lookups on `ParkingEntry`, never stored, so a park cannot carry a reason
  that disagrees with its own axis. Two decisions are pinned in
  `tests/unit/test_park_vocabulary.py` and worth not re-litigating:
  - *No routed re-entry for machine-actionable reasons.* The charter is
    categorical that the machine never acts on a parked item of its own
    accord, and there is no automatic TTL action. `category: machine` describes
    the **cause**, and the executor's bounded fix budget is spent *before* the
    park — so `ci-failure` waits for an explicit `item_enqueued` exactly as
    `deferred` does. Adding an auto-recheck path would also need a decision
    verb, which the `conditions.py` seam forbids this package from owning.
  - *The scheduling axis is kept, `human-gated` is dropped.*
    `discovered-work`/`later-wave`/`deferred` describe work that never failed
    (`discovered_work` parks items that never had a PR, and `later-wave` is the
    schema's only surviving trace of a wave), so no failure reason can describe
    them without lying. `human-gated` was the one old kind that *was*
    failure-shaped, and `approval-required` names the same state — two names
    for one state is the drift the reconciliation removes.
  - The `failure` axis is not this package's to define: it lives in
    `packages/contracts/park-reasons.toml`, which `packages/workcli`
    implements as `work park --reason`. The isolated-project boundary rules
    out a cross-import, and a transcription in each test file would only catch
    a *forgetful* one-sided edit — so both suites read that one file instead.
    Changing the vocabulary is a three-file change by construction: the
    contract plus both tables, with each missing table failing its own gate.
    The scheduling axis is grind-native and deliberately absent from the
    contract; it has no tracker counterpart.
- **`pr-open` and `in-review` are parkable, and that is load-bearing.** Every
  failure-axis reason (`ci-failure`, `merge-conflict`, `bot-declined`, …) is
  reached with a PR open, so excluding those statuses from `_PARKABLE` would
  let the boundary accept a park the fold then rejects as an anomaly — the
  axis would be unrecordable from exactly the states it names. `merged`/`done`
  stay unparkable: finished work has nothing left to park.
- **The fold still reads the retired `kind` field — but only when `reason` is
  absent.** `_LEGACY_PARK_KINDS` (`fold.py`) maps the pre-charter vocabulary
  on read: three members pass through unchanged, `human-gated` lands on
  `approval-required`. Nothing writes `kind` and the validator rejects it on
  input; the map exists because delete-and-refold is this runtime's whole
  recovery story, and an upgrade that greyed out every historical park would
  make it a poor one. Absent-only is the load-bearing part: an event carrying
  an unrecognized `reason` *alongside* a stale `kind` must not have its
  recorded cause quietly replaced by the older field — it stays untyped and
  records the anomaly triple, as any unrecognized value does. Absence means
  **key absence**, not a `None` value: an explicit `"reason": null` is
  present-and-garbage, which flags, and is a different thing from an old event
  that never carried the key.
- **`discovered_work` accepts only the scheduling axis.** It creates an item
  with no PR, no branch and no CI, so a failure reason there would be an
  untrue statement — the boundary narrows to `_SCHEDULING_REASONS` instead of
  the full table, and the fold mirrors the check so a replayed or hand-edited
  log cannot land one either. The fold *keeps* the item and parks it untyped
  rather than dropping it: a false failure record is the harm to prevent, and
  losing the discovered work would be a second one.
- **A failure-axis reason requires a PR ref, checked on `item.pr` and not on
  status.** A failure reason is a statement that this item's PR did not merge,
  so an item that never opened one folds as an anomaly instead. Status is the
  wrong key: `blocked` and `waiting-human` both legally hold an open PR, and
  those are exactly where an `approval-required` or `ci-failure` park lands.
  `pr_closed` leaves the ref behind, so a re-queued item still passes — the
  check is deliberately permissive there rather than risking a false rejection.

## Tests

- Behavioural, not tautological — each test pins a coded transition-table
  decision, a derived-state computation, or an anomaly-policy guarantee,
  never the language/stdlib. See `../workcli/AGENTS.md` for the shared
  house standard this mirrors.
- `tests/unit/builders.py` holds small event-builder helpers (`seed_event`,
  `event`) shared across test modules — not a fixture file, a plain module.
- Coverage floor is `fail_under = 80` over branch-enabled coverage; current
  numbers run well above it (see `make cov-grind` output).

## Reference

Specs: `docs/specs/2026-07-19-event-sourced-grind-runtime.md` (event envelope,
taxonomy, transition table, CLI contract, emit-back, staleness, handoff) and
`docs/specs/2026-07-19-grind-dashboard-renderer.md` (the renderer contract).

Both specs predate the harness-rework charter and frame their consumer as an
agent-topology skill that no longer exists; the runtime spec's "Integration
into orchestrated-grind" section is discarded by charter D14. Read them for the
substrate contract this package implements, and take the consumer, the
executor's role, and the park vocabulary from
`docs/specs/2026-07-21-harness-rework-way-forward.md` where the two disagree.
