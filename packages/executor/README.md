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
executor attempt it-1 --kind ci-fix                        # charge one fix attempt
executor next [--stale-days 30]                            # parked work, then ready work
```

`--dir` selects the grind directory; without it the runtime resolves its own.
`next` reads no grind directory at all.

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
| `attempt <id> --kind K`, under budget | `fix_attempted` | — |
| `attempt <id> --kind K`, at exhaustion | `item_parked` (`budget-exhausted`) | `work park --reason budget-exhausted` |

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

More generally, **every command refuses what the runtime would refuse** —
`start` outside `queued`, `park` on a merged or done item, `done` before a
merge, anything at all on a parked item, and a `pr-closed` naming a PR the item
is not on. The executor is the runtime's single writer, so a command it can
prove illegal is a caller's mistake rather than something that happened; the
log stays a record of transitions. For `start` and `park` it is also
correctness, since they write to the tracker before appending.

Re-parking an already-parked item under a *different* reason is refused too:
the parking lot's only exit is a redispatch or an abandon, so there is no
re-park to enact. The same reason with a differently worded note is the
ordinary idempotent retry.

## Opening new work

`executor next` is the one command with no row in that table, because it
mutates nothing. It reads the parked-work report, then the ready queue, and
answers with both:

```json
{"parked": [{"id": "wg-1", "reason": "merge-conflict", "parked_at": "...", "stale": true}],
 "ready":  [{"id": "wg-7", "status": "open", "...": "..."}]}
```

The order is the contract. Reviewing stuck work is the price of pulling new
work, so a parked report that fails takes the whole command down with it — the
ready queue is not even read, let alone reported. A caller never receives new
work beside a surfacing that quietly failed.

Both keys are always present; `"parked": []` means nothing is parked, and that
is a reported fact rather than a missing field.

`--stale-days` is forwarded to the report untouched, and omitting it forwards
nothing: the threshold has exactly one definition and it is the facade's. This
package neither holds a default nor recomputes a `stale` flag.

No event is appended, no tracker verb is enacted, and therefore no sync is
issued. The command also reads no grind state, so it works on a machine with
no run at all.

## Attempt budgets

`executor attempt` is where a caller declares a fix attempt **before making
it**. Under budget it appends `fix_attempted` and reports
`{kind, attempts, budget, remaining, proceed: true}`. The append is a
pre-charge: a crash after the call has already spent the attempt, and a budget
that counted only completed attempts would bound nothing. Two identical
`attempt` calls are therefore two attempts, not a command and its retry.

At exhaustion it refuses. `work park --reason budget-exhausted` runs first,
`item_parked` is appended second, and the envelope is a non-retryable
`E_BUDGET_EXHAUSTED` carrying the kind and both counts — plus what the park
landed, since this is the one refusal that mutates. A second `attempt` after
that park is refused as parked, mutating nothing.

**The runtime decides exhaustion, not this package.** The refusal fires on
grind's `attempt_budget_spent` condition; the executor keeps no counter of its
own. Budgets themselves are caller config seeded into the runtime
(`ci_fix_budget`, default 2; `rebase_budget`, default 1), and a seeded `0` is
legal — "spend nothing on this kind".

An attempt exists only inside a live PR cycle, so an item holding no open PR is
refused with `E_NO_OPEN_PR`. A reference a closure left behind does not count:
the runtime marks it closed, and that flag is what this checks.

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
| `E_NO_OPEN_PR` | no | a row needing a PR named an item holding none |
| `E_ITEM_PARKED` | no | a row that is not legal on a parked item named one |
| `E_BUDGET_EXHAUSTED` | no | `attempt` refused; its `data` carries `kind`, `attempts` and `budget` |
| `E_USAGE` | no | bad arguments, unknown item, a park reason on neither axis, or a transition the runtime flagged instead of applying |
| `E_INTERNAL` | no | an unexpected fault, typed rather than thrown |

A failed sync is repaired by running `work sync`, **never** by re-running the
command — that would repeat the mutations. The error's `data` shows what did
land.

The sync is owed by the mutation, not by the command succeeding: when a tracker
write lands and a later step fails, the sync is still issued before the failure
is reported. A command that mutated nothing syncs nothing.

## Not here yet

There is no dispatch loop: this package answers what a verb pairs with, not
when to run it.

## Development

```bash
make ci-executor     # the full gate: lint, format, types, coverage, audit, entry
make test-executor   # faster inner loop
```
