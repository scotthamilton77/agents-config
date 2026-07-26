# executor

Pairs grind runtime events with `work` tracker verbs. One command, one event,
at most one tracker write, one trailing sync.

```bash
executor start it-1                                        # claim + item_started
executor park it-1 --reason ci-failure --note "red on main"
executor redispatch it-1
executor abandon it-1 --pr 412 --reason superseded
executor pr-opened it-1 --pr 412
executor pr-closed it-1 --pr 412 --next queued --reason superseded
executor merged it-1 --sha 9fceb02
executor done it-1
```

`--dir` selects the grind directory; without it the runtime resolves its own.

## The pairing table

The executor's whole mutation surface. A blank tracker cell is deliberate, not
an omission.

| command | grind event | tracker |
|---|---|---|
| `start <id>` | `item_started` | `work claim` |
| `park <id> --reason <failure code>` | `item_parked` | `work park --reason` (same code) |
| `park <id> --reason <scheduling code>` | `item_parked` | — |
| `redispatch <id>` | `item_enqueued` | `work redispatch` |
| `abandon <id> --pr N` | `item_enqueued` + closure | `work abandon` |
| `pr-opened <id> --pr N` | `pr_opened` | — |
| `pr-closed <id> --pr N --next S --reason T` | `pr_closed` | — |
| `merged <id> --sha SHA` | `item_merged` | `work close` |
| `done <id>` | `item_done` | — |

`merged` takes its PR number from the fold, never from an argument: closed
means merged, and the executor must not be able to close against a PR the
runtime never saw. `done` is post-merge teardown with no tracker counterpart.

Park reasons cross **untranslated**. The failure axis is the shared park-reason
contract (`ci-failure`, `merge-conflict`, `approval-required`, `bot-declined`,
`budget-exhausted`); the scheduling axis (`discovered-work`, `later-wave`,
`deferred`) is runtime-native and reaches the tracker not at all.

A failure reason says this item's PR did not merge, so a failure-axis park on
an item holding no PR is refused with `E_NO_OPEN_PR` rather than half-enacted.
A scheduling park makes no such claim and needs no PR.

## Which side leads

An **intent** — something the executor is about to make true — calls the
tracker first and appends the event only on success, so a tracker failure
leaves the runtime un-advanced and the command retryable.

A **world-fact** — something that already happened outside — is appended first
and reported to the tracker second, so the fact stays recorded even when the
tracker call fails.

Neither rule prevents a one-sided state; both bound it to a single failed call
whose retry converges. Enactment is state-checked: when the runtime already
records the transition, no duplicate is appended and the tracker side is
re-issued anyway.

## Items with no tracker handle

`tracker_id = work_id or id`, with one exception. An item whose id matches
`disc-<n>` and which carries no work id is discovered work the tracker has
never heard of. Every tracker action for it is skipped, no sync is issued, and
the item is reported under `data.unpromoted`.

This is a success path. Minting a tracker item for such work takes placement,
type and priority judgment that arrives with a dispatch brief, so nothing here
guesses at it.

## The envelope

Exactly one JSON object on stdout per invocation, success or failure. Never a
traceback.

```json
{"protocol": "1", "ok": true, "data": {...}, "error": null}
{"protocol": "1", "ok": false, "data": null,
 "error": {"code": "E_SYNC_FAILED", "message": "...", "retryable": true, "data": {...}}}
```

Exit 0 on success, 1 on any typed failure.

| code | retryable | meaning |
|---|---|---|
| `E_RUNTIME_SUBPROCESS` | yes | the runtime call failed |
| `E_RUNTIME_ENVELOPE` | yes | the runtime replied with something unparseable |
| `E_TRACKER_SUBPROCESS` | yes | the facade call failed |
| `E_SYNC_FAILED` | yes | mutations landed, the sync did not — repair with `work sync` |
| `E_NO_OPEN_PR` | no | a merge or a failure-axis park named an item holding no PR |
| `E_ITEM_PARKED` | no | reserved for `attempt` |
| `E_BUDGET_EXHAUSTED` | no | reserved for `attempt` |
| `E_USAGE` | no | bad arguments, unknown item, a park reason on neither axis, or a transition the runtime flagged instead of applying |
| `E_INTERNAL` | no | an unexpected fault, typed rather than thrown |

A failed sync is repaired by running `work sync`, **never** by re-running the
command — that would repeat the mutations. The error's `data` shows what did
land.

The sync is owed by the mutation, not by the command succeeding: when a tracker
write lands and a later step fails, the sync is still issued before the failure
is reported. A command that mutated nothing syncs nothing.

## Not here yet

`attempt` (budget enforcement) and `next` (open-new-work surfacing) are named
in the verb universe and unwired. There is no dispatch loop: this package
answers what a verb pairs with, not when to run it.

## Development

```bash
make ci-executor     # the full gate: lint, format, types, coverage, audit, entry
make test-executor   # faster inner loop
```
