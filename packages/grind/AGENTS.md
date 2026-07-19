# AGENTS.md — `packages/grind/`

Package-scoped guidance for the event-sourced grind runtime's schema + fold.
The repo-root `AGENTS.md` still applies; this file adds what is specific to
this package. Unlike the config content under `src/`, **this is real code
with a real quality gate.**

`grind` is the event log and materialized-state engine behind an
orchestrated-grind run: an append-only `events.jsonl` is the source of
truth, and `fold(events) -> State` is the pure transition function that
turns it into a `state.json`-shaped snapshot. See
`docs/specs/2026-07-19-event-sourced-grind-runtime.md` for the full design —
this package implements its event envelope, event taxonomy, the fold and
transition table, and the observations schema (`.30.1` in the spec's
Delivery section).

**Scope note:** this package currently ships schema + fold only — no `grind`
CLI exists yet (`grind create`/`log`/`status`/`render`/`check`/`finish` land
in a later bead, `wgclw.30.2`). There is deliberately no
`[project.scripts]` entry point; `verify-entry-grind` in the root `Makefile`
checks the package imports cleanly instead of invoking a nonexistent binary.

## The quality gate is mandatory — run it, do not approximate it

Before pushing **any** change under `packages/grind/`, run the canonical
gate from the repo root:

```bash
make ci-grind   # the full gate CI enforces
```

It runs, in order: `ruff check` (lint), `ruff format --check` (formatting),
`mypy --strict src` (types), `pytest --cov` (tests + coverage), `pip-audit`
(deps), and an import-verify smoke check. `make ci` runs this alongside
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
  `strict = true`, coverage `branch = true` / `fail_under = 80` (this
  package's floor matches the repo's global 80%/70% default — see
  `packages/workcli/AGENTS.md` for a sibling package that raised its own
  floor; this one hasn't needed to).
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
- **Layout:** `model.py` (the `State` shape and its typed sub-records —
  `Item`, `Lane`, `ItemReview`, `ParkingEntry`, …), `fold.py` (the transition
  table and every event handler), `derive.py` (read-side projections that
  need no wall clock, e.g. lane status; time-dependent `conditions(State,
  now)` is a sibling bead's scope, not this package's yet), `log.py`
  (JSONL parsing with torn-tail tolerance, and `fold_log()` composing parse
  + fold).
- **Payload validation lives at the CLI boundary, not here.** Per spec
  ("parse once, trust inward"), `fold()` trusts that a well-formed event's
  payload fields are shaped correctly; the CLI (a later bead) is
  responsible for rejecting malformed payloads before they ever reach the
  log. This package's tolerance is about *structural* garbage (missing
  keys, wrong JSON types, unknown event types) — it degrades gracefully
  rather than crashing, but it doesn't second-guess a well-typed field's
  business validity beyond what the transition table itself encodes.

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
- **`pr_closed`'s `next: parked` path has no `kind`.** Unlike `item_parked`
  (which always carries a `kind` enum), `pr_closed`'s payload has no parking
  kind — this package parks with `kind=None` and reuses the closure's
  `reason` as the parking note.

## Tests

- Behavioural, not tautological — each test pins a coded transition-table
  decision, a derived-state computation, or an anomaly-policy guarantee,
  never the language/stdlib. See `../workcli/AGENTS.md` for the shared
  house standard this mirrors.
- `tests/unit/builders.py` holds small event-builder helpers (`seed_event`,
  `event`) shared across test modules — not a fixture file, a plain module.
- Coverage floor is 80% line / 70% branch (house default); current numbers
  run well above that (see `make cov-grind` output).

## Out of scope for this bead (`wgclw.30.1`)

The following are explicitly sibling beads under `wgclw.30`, not this
package's current surface:

- `grind` CLI verbs (`create`/`log`/`status`/`render`/`check`/`finish`) —
  `.30.2`.
- The dashboard renderer — `.30.3`.
- ERROR -> attention and LESSON -> panel *routing policy* beyond the fold
  already producing the right typed records — `.30.4`.
- The emit-back envelope and the full condition vocabulary
  (`conditions(State, now)`, including `review_stalemate_risk` and the
  transition condition `item_unblocked`) — `.30.5`.
- `grind check` and the staleness watchdog — `.30.6`.
- `orchestrated-grind/SKILL.md` integration — `.30.7`.

## Reference

Spec: `docs/specs/2026-07-19-event-sourced-grind-runtime.md`.
