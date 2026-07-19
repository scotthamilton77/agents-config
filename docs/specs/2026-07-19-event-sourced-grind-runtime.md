# Event-sourced grind runtime — design

**Bead:** `agents-config-wgclw.30`
**Status:** draft

## Problem

A grind run currently maintains its operational state in two hand-edited,
drift-prone artifacts:

1. **`ORCHESTRATION-STATE.md`** — a compaction handoff ROOT composes by hand,
   from memory, ideally *before* it needs it. Written late, it is composed from
   degraded context; written early, it goes stale as the run advances.
2. **`state.json` + `dashboard.html`** — owned by a dedicated `bookkeeper`
   agent that receives terse deltas from ROOT, merges them into state, and
   re-renders the dashboard. A model performing deterministic state mutation:
   token cost per update, drift risk per merge, and a whole named teammate
   whose job a script can do.

Both artifacts answer the same question — *what is the state of this grind?* —
and neither is authoritative, because both are downstream of ROOT's memory.
When they disagree with the world (observed repeatedly in the reference runs),
ROOT burns context reconciling them.

This spec replaces both with **one append-only event log** managed by a small
CLI. The log is the source of truth; session state, the dashboard, and the
compaction handoff are all derived projections; recovery is replay. The
bookkeeper agent is retired. Code over model: ROOT logs typed events and reads
back derived state, instead of narrating state to a teammate and hand-writing
handoffs.

## Glossary

First-class entities (present in the schema):

- **Grind** — one run, one event log, one dashboard. The root aggregate;
  `grind_created` … `grind_finished` bound its lifetime.
- **Lane** — a conflict-partitioned, ordered queue of items owned by one
  lieutenant. An *ownership* grouping, nothing more.
- **Item** — **the** atomic unit of the FSM. Maps 1:1 to a work-tracker bead,
  typically ships as one PR, and is the only entity carrying the nine-status
  lifecycle. Every typed event that is not grind- or lane-scoped references
  exactly one item.
- **Blocker edge** — a directed dependency between two items (may cross
  lanes). Recorded as fact; everything below is derived from edges.

Derived views (computed by the fold, never stored, never event payloads):

- **Chain** — a path through blocker edges whose terminus cannot currently
  progress (blocked on blocked, or on parked / waiting-human). Evidence for
  the `blocked_chain` condition; recomputed each fold, evaporates when the
  terminus moves.

Deliberately **not** an entity:

- **Wave** — a sequencing cohort ("these items now, those after"). Survives
  only as the parking kind `later-wave`. No wave arithmetic exists anywhere in
  the schema; a parked later-wave item re-enters play via `item_enqueued`.

## Design

### Files and ownership

A grind directory (the grind's working directory) contains:

| File | Role | Written by |
|------|------|-----------|
| `events.jsonl` | Append-only event log — **the** source of truth | `grind` CLI only |
| `state.json` | Materialized snapshot of the fold — a cache | `grind` CLI only |
| `dashboard.html` | Rendered projection of `state.json` | `grind render` (see the dashboard renderer spec) |

ROOT never edits any of these by hand. `state.json` is disposable: delete it
and the next command refolds from the log. The fold **refolds from zero on
every command** — grind logs are hundreds of events, not millions; refold
costs milliseconds and buys freedom from incremental-fold bugs and snapshot
corruption. There is no incremental mode.

**Single-writer (v1):** ROOT is the only process that appends. Lieutenants
report to ROOT (unchanged runtime fact — worker completions notify ROOT
anyway), and ROOT logs. No locking in v1; the append is a single
`O_APPEND` write of one line.

**Torn tail:** a crash mid-append can leave a truncated final line. The fold
detects a non-parsing last line, drops it, and reports it in the envelope as
an anomaly (`torn_tail`). Accept-and-flag, not refuse-to-load.

### Event envelope

Every line in `events.jsonl` is one JSON object:

```json
{ "ts": "2026-07-19T04:12:08Z", "type": "pr_opened", "item": "wgclw.30.1", "pr": 341 }
```

- `ts` — ISO-8601 UTC, stamped by the CLI at append time. Never supplied by
  the caller.
- `type` — one of the taxonomy below. Unknown types append fine and fold as
  anomalies (forward compatibility), never crash the fold.
- Entity reference — `item`, `lane`, or neither (grind-scoped), per type.
- Remaining fields — the type's payload, validated at the CLI boundary
  (parse once, trust inward). Free-text fields exist (`detail`, `message`,
  `summary`) but nothing the renderer must *parse* is free text — labels,
  kinds, statuses, counts are all typed fields.

### Event taxonomy

Status is **derived** by the fold, never asserted. There is no
`status_changed` event; ROOT logs what *happened* and the fold computes what
things now *are*.

**Grind lifecycle**

| Type | Payload | Effect |
|------|---------|--------|
| `grind_created` | `title`, `repo` (owner/name), `mission` (goal + explicit out-of-scope), `protocols` (structured block: review protocol choice, merge-policy resolution, watcher conventions, session grants), `config` (thresholds, below), `lanes[]` (id, name, agent, queue of items with bead ids, titles, blocker edges) | Seeds the entire board. The mission/protocols block is what makes `status --handoff` self-contained (§7 replacement). |
| `grind_paused` | `reason`, `resume_checklist[]` | Board banner; handoff carries pause state |
| `grind_resumed` | — | Clears pause |
| `grind_finished` | `summary` | Terminal. Fold rejects (anomaly) further mutating events. |

Seeded blocker edges (in `lanes[].blocker edges`) take effect at fold time: an
item with unresolved edges folds as `blocked`, not `queued` — identical to
edges recorded later by `item_blocked`.

**Lane**

| Type | Payload | Effect |
|------|---------|--------|
| `lane_standing_down` | `lane` | Lane status `standing-down` (queue empty, wrapping up) |
| `lane_handover` | `lane`, `from_agent`, `to_agent`, `reason` | Records lieutenant rotation; lane keeps its queue |

Lane status is otherwise fully derived from item statuses (all done → `done`;
any in flight → the most advanced active state), so there is no generic
`lane_status` event to drift.

**Item lifecycle** (each row is a transition; the full legality table is
below)

| Type | Payload | Fold effect |
|------|---------|-------------|
| `item_started` | `item` | `queued → in-progress` |
| `pr_opened` | `item`, `pr` | `in-progress → pr-open` |
| `review_round` | `item`, `kind` (codex\|copilot\|ralf\|human), `round`, `detail?` | `pr-open → in-review` (or stays `in-review`); sets the round badge |
| `review_verdict` | `item`, `kind`, `round`, `verdict` (clean \| findings \| stalemate), `findings[]` — each `{severity, summary, disposition (fixed \| wont-fix \| deferred \| escalated), thread_url?}` | Records the round's outcome. `open_threads` and `wont_fix_count` are **derived** from dispositions, not asserted. `stalemate` sets the item's stalemate flag (declared per the review skill's §3 rule — the fold records, it does not diagnose). |
| `pr_closed` | `item`, `pr`, `reason`, `next` (in-progress \| queued \| parked) | Unmerged closure (abandoned, superseded). Item returns to `next`; without this an abandoned PR is unrepresentable except by lying. |
| `item_blocked` | `item`, `on[]` (blocking item ids), `note?` | Records blocker edges (and `note`). `blocked` status is **derived** from unresolved edges — whichever way they arrived (seed or event), never asserted by the event. Unblocking is **derived**: when every edge's target reaches `merged`/`done`/closed, the fold returns the item to `queued` and fires the `item_unblocked` condition — there is no unblock event. |
| `item_waiting_human` | `item`, `why` | `→ waiting-human`; auto-raises an attention entry |
| `item_merged` | `item`, `pr`, `sha` | `→ merged`; appends to the merged ledger projection |
| `item_done` | `item` | `merged → done` (post-merge leg complete); clears any attention/round badge for the item |
| `item_parked` | `item`, `kind` (discovered-work \| human-gated \| later-wave \| deferred), `note` | Removes from active queue into the parking lot |
| `item_enqueued` | `item`, `lane`, `position?` | Parking lot's one exit: `parked → queued` in the named lane. Also legalizes mid-grind queue additions. |
| `discovered_work` | `item` (durable id), `description`, `source` (lane/PR that surfaced it), `bead?`, `disposition` (parked \| enqueued), `kind?` (when parked), `lane?` (when enqueued), `rationale` | Creates a new item carrying its triage rationale, keyed by the required `item` id: the bead id when one exists, else a ROOT-assigned run-unique slug (`disc-<n>`, next free ordinal). `bead?` is optional metadata, carried only when it differs from `item`. `enqueued` is sugar for discover + `item_enqueued` in one event. |

**Cross-cutting**

| Type | Payload | Effect |
|------|---------|--------|
| `observation` | `level` (INFO \| WARN \| ERROR \| LESSON), `message`, `item?`, `lane?` | Terse markers, not narration. `ERROR` auto-raises an attention entry; `LESSON` feeds the lessons-learned projection (the grind-retrospective capture mechanism — no bespoke lessons protocol). |
| `attention_raised` | `text`, `item?` | Adds to the human docket / red banner |
| `attention_cleared` | `text` or `item` | Removes the matching entry |

### The fold and the transition table

The fold is a **pure function** `fold(events) → State`, unit-tested in
isolation. State contains: grind header (title, repo, mission, protocols,
pause state), lanes with derived statuses, items with derived statuses +
review state + PR refs, blocker edges, parking lot, attention list,
observations, merged/closed ledgers (projections over `item_merged` /
`item_done`), lessons, and the currently-true condition set.

Item status legality (rows = current status, event → new status; anything
absent is an anomaly):

| From \ Event | started | pr_opened | review_round | verdict | pr_closed | blocked | waiting_human | merged | done | parked |
|---|---|---|---|---|---|---|---|---|---|---|
| `queued` | in-progress | — | — | — | — | blocked | waiting-human | — | — | parked |
| `in-progress` | — | pr-open | — | — | — | blocked | waiting-human | — | — | parked |
| `pr-open` | — | — | in-review | in-review | per `next` | blocked | waiting-human | merged | — | — |
| `in-review` | — | — | in-review | in-review | per `next` | blocked | waiting-human | merged | — | — |
| `waiting-human` | — | pr-open | in-review | in-review | per `next` | — | — | merged | — | parked |
| `blocked` | — | — | — | — | — | — | waiting-human | — | — | parked |
| `merged` | — | — | — | — | — | — | — | — | done | — |
| `done` | terminal | | | | | | | | | |
| (parked) | re-enters via `item_enqueued → queued` only | | | | | | | | | |

`standing-down` remains lane-only vocabulary, set by `lane_standing_down`.

`item_started` on an item with unresolved blocker edges folds as an anomaly
(accept-and-flag applies): the item is `blocked`, and the table's `(queued)`-row
legality presumes no unresolved edges.

**Anomaly policy — accept-and-flag, never reject.** An event that is not
legal from the item's current status (or references an unknown item/lane, or
has an unknown type) is still **appended** — append-only logs do not argue at
3am, and a refused write mid-grind means ROOT improvises, which is how
hand-edited state came back last time. The fold:

1. records the event as `applied: false` with a reason,
2. leaves the entity's status unchanged,
3. auto-raises an `ERROR`-level observation → attention banner, and
4. reports the anomaly in the command's envelope so ROOT sees it in the same
   tool result.

The human sees every anomaly on the dashboard; correction is a follow-up
event, never an edit to the log.

### CLI contract — `grind`

Standalone package `packages/grind/`, command `grind` on PATH (installed by
the installer via `uv tool install`, receipt-tracked, like `workcli` and
`prgroom`). All commands take `--dir <grind-dir>` (default: cwd). All output
is a JSON envelope on stdout (the house pattern); exit code 0 unless the
command itself failed (an *anomalous event* still exits 0 — it was recorded;
anomalies are data, not errors).

| Verb | Does | Returns |
|------|------|---------|
| `grind create --file seed.json` | Validates the seed (a `grind_created` payload), writes `events.jsonl` with the first event, folds, writes `state.json`, renders the dashboard | `{ok, state_summary}` |
| `grind log <type> [payload flags or --json '<payload>']` | Validates payload shape at the boundary, appends, refolds, rewrites `state.json`, re-renders | The **emit-back envelope** (below) |
| `grind status [--handoff] [--full]` | Reads the log, folds, reports | Default: summary + conditions. `--full`: entire state. `--handoff`: the compaction handoff (below). |
| `grind render` | Refolds and re-renders `dashboard.html` only | `{ok, path}` |
| `grind check [--max-age <dur>]` | Staleness probe (below) | `{ok, last_event_ts, age_s, stale}` — exit **1** when stale |
| `grind finish --summary <text>` | Appends `grind_finished`, final fold + render | Final state summary |

Event payloads are validated per-type at the CLI boundary (parse once, trust
inward); a malformed *payload* is a command error (exit ≠ 0, nothing
appended) — malformation is caught before the log, illegality is caught after
(accept-and-flag). This is the seam between "you typed it wrong" and "the
world is in a state you didn't expect."

### Emit-back — the envelope and the condition vocabulary

Every `grind log` returns:

```json
{
  "ok": true,
  "applied": true,
  "anomaly": null,
  "delta": { "entity": "wgclw.30.1", "old_status": "pr-open", "new_status": "in-review" },
  "conditions": [
    { "condition": "review_stalemate_risk", "item": "wgclw.30.2", "round": 4, "since": "2026-07-19T03:10:00Z" }
  ]
}
```

so ROOT reads decision-relevant state in the same tool result as the append —
zero extra round-trips, and a post-compaction ROOT is re-oriented by its
first `log` call.

**HARD SEAM: the script surfaces conditions — facts with evidence — and ROOT
decides actions.** No orchestration policy lives in the state layer: a
condition never says "nudge the lane" or "escalate"; it says what is true and
shows its evidence. The seam is documented in the package and enforced by
review; a condition whose name is an imperative is a defect.

| Condition | Fires when | Evidence carried |
|---|---|---|
| `lane_complete` | last item in a lane's queue reaches `done` | lane |
| `grind_complete` | every lane complete | — |
| `stale_item` | item not terminal/parked and no event references it for > `config.stale_item_after` | item, age |
| `stale_lane` | no event referencing a lane for > `config.stale_lane_after` | lane, age |
| `attention_pending` | unresolved attention entries exist | count, oldest age |
| `blocked_chain` | an item is blocked on an item that is itself blocked/parked/waiting-human | the chain, as an ordered item list |
| `review_stalemate_risk` | round ≥ `config.stalemate_risk_round` with no intervening `pr_opened`/commit-bearing event — dumb arithmetic only; stalemate *declaration* stays with the review skill's §3 rule | item, round |
| `item_unblocked` | all blocker edges of a `blocked` item just resolved | item(s) now startable |

Thresholds live in `grind_created.config` with defaults
(`stale_item_after: 45m`, `stale_lane_after: 30m`, `stalemate_risk_round: 3`);
staleness conditions are computed against the CLI invocation's wall clock at
fold time. Conditions are recomputed on every fold; `grind status` returns
the currently-true set, so a condition is never "missed" by not watching the
right `log` call.

### Staleness watchdog

The fold can self-report a stale *item* or *lane* only when something invokes
it — a fully-quiet grind emits nothing, so the last mile needs an **external**
probe. `grind check --max-age 30m` compares the log's last event timestamp to
now and exits 1 when exceeded. Absence of `grind_finished` + stale log =
stalled or crashed grind.

The probe is armed the same way PR watchers are: ROOT launches a dumb
background timer loop (`run_in_background`, direct — never nested in a
wrapper) that runs `grind check` on an interval and rings on staleness. Keep
it dumb for the same reasons the PR watcher is dumb: a clever watchdog that
dies silently is indistinguishable from a healthy quiet grind. The ring is a
doorbell; ROOT (or the human, for a dead ROOT) interprets.

### Compaction handoff — `grind status --handoff`

Replaces `ORCHESTRATION-STATE.md` §7 entirely. The handoff is a rendered
projection containing exactly §7's anatomy, sourced as follows:

| §7 item | Source in the log |
|---|---|
| 1. Mission + out-of-scope | `grind_created.mission` |
| 2. Pause state + resume checklist | `grind_paused` (if unresumed) |
| 3. Roster + exact positions | `grind_created.lanes` + `lane_handover` + derived item statuses |
| 4. Merged/closed ledger | `item_merged` / `item_done` projections |
| 5. Human docket + recommendations | attention list + `item_waiting_human.why` |
| 6. Operating protocols in force | `grind_created.protocols` |
| 7. Repo quirks and traps | `WARN`/`LESSON` observations |

Because every source is written *when context was fresh* (setup, or the
moment a quirk was hit), the handoff no longer degrades with ROOT's context.
Recovery = `grind status --handoff`, read, resume. Hand-maintained handoff
files: retired.

### Integration into orchestrated-grind

`orchestrated-grind/SKILL.md` changes (this spec's .30.7 scope; the skill
text itself is written at implementation):

- **ROOT's loop becomes log → read → act.** Every state change ROOT learns of
  is a `grind log` call; the returned envelope (delta + conditions) is what
  ROOT acts on. ROOT never computes board state in its head and never edits
  state artifacts.
- **§5 (bookkeeper) is rewritten around the CLI.** The bookkeeper teammate is
  removed from the topology and the roster diagram; `state.json` and
  `dashboard.html` become build artifacts of the log. The dashboard-contract
  requirements move to the renderer (dashboard spec). Open-once stays ROOT's
  job: `open <path>` on macOS / `xdg-open` elsewhere, exactly once at
  creation (per bead wgclw.28.4 — never a browser-automation MCP).
- **§7 (compaction safety) is rewritten** to: run `grind status --handoff`.
  The "write it before you need it" rule dissolves — there is nothing to
  write.
- **Setup sequence:** "spawn the bookkeeper first" is replaced by
  `grind create` with the seed file (mission, protocols, config, lanes) that
  ROOT composes from the human-confirmed partition.
- **Watchers (§6) unchanged**; the staleness watchdog joins them as a
  ROOT-armed background probe.
- Lieutenants do not run `grind` in v1 (single-writer); they report to ROOT
  as today, and ROOT logs.

The event log also subsumes the shutdown ledger-reconciliation input: §Shutdown's
"reconcile against the tracker directly" stays, but the grind-side ledger it
reconciles is now the fold's projection, not a hand-tended list.

## Package and CI

- `packages/grind/` — standalone uv project, own `pyproject.toml`, laid out
  like `workcli` (src layout, typed boundaries, Result-style expected
  failures at the CLI seam).
- Gate: `make ci-grind` (lint, format-check, typecheck, coverage, audit,
  entry-verify), wired into whole-repo `make ci`.
- Installed onto PATH by the installer (`uv tool install`, receipt-tracked,
  pruned on retirement) — same lifecycle as `workcli`/`prgroom`.

## Testing

Per the house floor (80% line / 70% branch on changed code), behavioral tests
only:

- **Fold unit tests** — the heart. Every legal transition in the table; every
  illegal one folds as an anomaly with status unchanged + ERROR observation;
  derived unblocking; derived lane status; derived counts from verdict
  dispositions; condition firing (each condition, plus threshold boundaries);
  torn-tail drop; unknown-type tolerance; post-`grind_finished` rejection.
- **CLI golden tests** — envelope shape per verb; payload validation errors
  exit ≠ 0 with nothing appended; anomalous-but-valid events exit 0;
  `check` exit-code behavior at the age boundary.
- **Replay property** — `fold(log)` equals `fold(log)` re-run on a copied
  file (determinism), and `state.json` is byte-identical after
  delete-and-refold.
- **Handoff projection test** — a fixture log covering all seven §7 items
  renders each into the handoff.

Renderer testing lives in the dashboard spec.

## Delivery

Implementation order follows the bead dependency graph, all under
`agents-config-wgclw.30`:

1. `.30.1` — schema + fold (this spec's taxonomy, transition table, anomaly
   policy) in `packages/grind/`, CI-gated.
2. `.30.2` — CLI verbs over the fold.
3. `.30.3` — `render` projection (dashboard spec).
4. `.30.4` — observations + routing (schema already lands in .30.1; this bead
   is the ERROR→attention and LESSON→panel routing plus its tests).
5. `.30.5` — emit-back envelope + condition vocabulary.
6. `.30.6` — `check` + watchdog arming guidance.
7. `.30.7` — SKILL.md integration; retire the bookkeeper and
   ORCHESTRATION-STATE.md.

## Continuations

The implementation items already exist as children of `agents-config-wgclw.30`
(`.30.1`–`.30.7`) — no new beads to mint. At spec-PR merge, the delivering
session:

- updates each child bead to cite this spec by name ("event-sourced grind
  runtime spec, section …"),
- updates `.30.3` to cite the grind dashboard renderer spec,
- stamps the readiness label on `.30.1`–`.30.7`,
- releases the claim on `agents-config-wgclw.30` (status back to open).
