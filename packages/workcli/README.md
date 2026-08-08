# `work` — the issue-tracker facade CLI

`work` quarantines the issue-tracker backend (`bd`) behind one tested,
versioned surface. The repo's M0 charter states the end goal directly:
"beads is quarantined behind our own CLI" — this package is that CLI. Every
program that would otherwise shell out to `bd` directly (prgroom's
bd-adapter, the PDLC orchestrator's bd-adapter, ad-hoc skill scripts) shells
out to `work` instead, so `bd` schema/format drift lands in exactly one
place instead of being re-discovered per consumer.

This document is written for an engineer wiring a programmatic adapter
against `work` — the audience is a program, not a human at a terminal.

The repo installer installs `work` globally onto PATH (`uv tool install`,
receipt-tracked, pruned on retirement); `uv run work …` from inside
`packages/workcli/` remains the way to exercise an in-checkout, unreleased
change.

## Verb table

31 verbs; each is a subcommand of `work`.

| Verb | Args/flags |
|---|---|
| `work show IDS...` | — |
| `work create --raw --title T [--description D] [--type task] [--priority P2] [--parent ID] [--label L ...]` | `--label` repeatable |
| `work update ID [--set-title T] [--set-priority P] [--set-description D]` | ≥1 `--set-*` required; `--set-notes` and `--set-acceptance` → `E_FIELD_CLOBBER_GUARD` (both suppressed from `--help`) |
| `work note ID TEXT` | append-only |
| `work close IDS... [--disposition TEXT]` | disposition = one appended note per id |
| `work reopen ID` | — |
| `work list [--status S] [--label L] [--parent ID] [--type T] [--limit N]` | every status, closed included, and unbounded — `--status` and `--limit` are the only things that narrow either axis |
| `work ready [--label L]` | unbounded |
| `work dep {add,remove,list} ID [TARGET] [--type blocks]` | `dep add A B` = A depends on B |
| `work label {add,remove,list} ID [LABELS...]` | multi-label in one call |
| `work search QUERY [--in FIELD] [--status S] [--limit N]` | reads title, description and notes, every status, unbounded — `--in` (repeatable) narrows the fields, `--status`/`--limit` the rest |
| `work sync [--pull]` | — |
| global | `--format {json,human}` (human renders to **stderr**; stdout envelope unchanged), `--protocol-version`, `--config PATH` (explicit `project-config.toml`; overrides the upward search — track-layer surfaces only, see below) |

`epic`/`stats`/`compact`/`delete` are deliberately out of scope for v1 — no
programmatic consumer observed. A consumer that needs one adds it here; the
facade does not expose a way around itself.

**Creating a tracker workspace is out of scope for a different reason, and
permanently: it is not a facade operation.** A workspace is a directory-shaped
thing carrying storage-engine, remote and id-prefix decisions, and a backend
whose items live on a server rather than in a directory has nothing for such a
verb to mean. Setting one up is a per-project setup step, documented alongside
the tracker rather than offered here — which is why `E_NO_WORKSPACE` advises
running where a workspace already exists and says plainly that creation happens
elsewhere. This is the only gap the facade declares permanent — everything else
it omits is waiting on a consumer, and this is not.

## Lifecycle verbs

The lifecycle layer sits over the transport verbs above, on the same
`Backend` seam: **status only ever moves through a lifecycle verb** (plus
transport's `close`/`reopen`) — `work update` never touches status. `work
create` gains a noun-templated mode (`create <noun>`) alongside its
transport-thin `--raw` mode; the two modes share the `create` subcommand,
selected by whether a noun positional or `--raw` is given.

| Verb | Args/flags |
|---|---|
| `work create NOUN --title T (--parent ID \| --orphan) [--description D] [--priority P] [--acceptance AC] [--spec REF] [--trivial]` | `NOUN` one of `spike\|chore\|decision\|feat\|bugfix\|spec\|epic\|milestone`; placement is required-exactly-one; `--spec`/`--trivial` mutually exclusive |
| `work claim ID` | open, unblocked, unclaimed leaf → `in_progress`; refuses containers and blocked leaves |
| `work release ID` | `in_progress` → `open`, no phase advance |
| `work deliver ID [--spec PATH] [--pr REF] [--items ID,ID] [--trivial]` | on a design child: parses the merged spec's `## Continuations` manifest — one `- <noun>: <title> — AC: <acceptance>` bullet per follow-on item, or the single bullet `- none — <why there is none>` when the spec leaves no follow-on work (the reason is optional — a bare `- none` parses, and the reason is what lands as a note on the closed placeholder) — and reconciles the sibling placeholder; on a leaf: evidence-gated close |
| `work plan ID (--done \| --undo) [--force]` | stamps/revokes the `planned` label (Planning-queue membership) |
| `work promote ID` | a `shape-feat` leaf becomes a `shape-spec` container |
| `work defer ID [--note TEXT]` | sets an item aside as not-now → `deferred`; leaves `ready`, claims no obstruction, and never enters the parked staleness report |
| `work undefer ID` | `deferred` → `open` |
| `work acceptance set ID TEXT [--why REASON]` | restates the criteria a claim is checked against; `--why` is required once work has started (any status but `open`/`deferred`) |
| `work reconcile [--dry-run]` | recovery sweep over the states the tracker can still observe: interrupted delivers, unreconciled placeholders, interrupted expansions — idempotent, safe to run from any session or cron |

`defer`/`undefer` are deliberately not the park family (`work park
--reason`/`redispatch`/`abandon`), which states why work that *was* started
cannot merge and ages into a staleness report. A read envelope tells the two
apart on `status` alone — `deferred` versus a parked item's `blocked` beside
its `parked` label — so a consumer never parses a note to distinguish an idea
from an obstruction. Both `defer` and `undefer` are idempotent on replay. A
deferred child is not a closed one: it holds its parent open in the
close-walk exactly as an open child does, and never reaches the `held`
report, which is for parents whose children *are* all closed.

`acceptance set` is the only way criteria move after create: `update` refuses
`--set-acceptance` with `E_FIELD_CLOBBER_GUARD` and names this verb. The
criteria are the termination condition a claim is checked against, so a silent
replace would let a check pass because the contract moved rather than because
the work met it — and the two things that stop that are the verb's whole
content. The superseded text is quoted into a note (`> ` per line, under a
`[work] acceptance restated <ISO-8601>` marker; `[work] acceptance first set`
where the item carried none) and that note is written **before** the
replacement, so a failure between the two writes can only leave a trail
without a change, never a change without a trail — criteria still equal to the
quote are criteria the replacement never reached. Once work has started the
call additionally requires `--why`, which lands on the marker line beside the
status the item was in. Setting the criteria already in force writes nothing.

Protocol is `"1.13"` — additive-only bumps (new `ErrorCode` members, the
derived `Item.track` field and the `acceptance` field beside it, the
capability-disposition model, `partial_progress` detail below, `search`'s
optional narrowing flags, the close-walk's `held` key, the `defer`/`undefer`
pair, and `acceptance set`) never change an existing envelope or data shape. A
bump can still change what an unchanged call *answers*, in either direction:
1.8 makes `search` read descriptions and notes as well as titles, stop
excluding closed items, and stop stopping at the first page, so a query that
used to return nothing may now return matches — and `create <noun>` refuses a
title a closed item already carries. 1.10 narrows instead: the close-walk
stops closing a parent that carries scope of its own, so a parent that used
to appear under `walked` now appears under `held` with what is unfinished
named. 1.11 widens again, mildly: `status` can report `deferred` on an item
the facade itself set aside, a value the backend always could hold and this
contract always declared. 1.12 adds `acceptance set`, whose only visible mark
on an existing shape is a facade-authored marker line in `notes`, beside the
ones the park family and the `defer`/`undefer` pair already write. 1.13 is
1.8's case again, on `list`: a listing used to carry whatever statuses the
backend returned unasked, which was live work only, so an id that exists
could be absent from a complete-looking listing. It now carries every
status, closed included, and `--status` is the only thing that narrows it.
`ready` is unchanged — it answers the queue question, where closed work has
no place, and a caller wanting the queue view of a listing asks `list
--status open` for it.
`Capabilities` splits `ready` and `sync` into a `ReadySupport`/
`SyncSupport` disposition each (`NATIVE` | `EMULATED`/`SERVER_AUTHORITATIVE`
| `UNSUPPORTED`) instead of a single boolean, and `dep` gates only typed
writes via `supports_dep_write` — `dep list` is never gated, even when
writes are unsupported. bd itself declares every disposition `NATIVE`
(`supports_dep_write=True`), so nothing in this package needs the finer
split yet; it exists for the future non-bd (GH) adapter bead, which can
declare an honest server-authoritative `sync` no-op or an emulated `ready`
computed client-side from `query` + dep edges.

The seam's two irreducibly multi-call `Backend` primitives (`label_mutate` —
one `bd label` call per label; `sync` — `dolt commit` then `dolt push`) can
fail after some sub-steps already applied. A mid-sequence failure's
`WorkError` carries a `detail.partial_progress` record —
`{"operation": "label_mutate" | "sync", "steps_total": int, "completed":
[...], "failed": ..., "remaining": [...]}` — naming exactly what already
applied so a caller can resume safely instead of guessing. Both primitives
are idempotent as a whole (the adapter absorbs bd's already-applied/already-
absent outcomes as success), so retrying from the top after any failure —
with or without a `partial_progress` key — always completes safely; the
key's presence is caller-facing diagnostic detail, not a safety gate
(`work reconcile`'s sweep is lifecycle-scoped and does not consume it). Absence of the key is the contract signal that nothing
applied yet: a single-call primitive's `WorkError`, or a `label_mutate`/
`sync` failure on its first sub-step, never carries it.

## Envelope contract

Every invocation writes exactly one JSON object to stdout, always, whether
the verb succeeds or fails. Exit code mirrors `ok` (`0` on success, `1` on
failure). `--format human` (see below) never changes this — it only adds a
second, human-readable rendering on stderr.

Success:

```json
{"protocol": "1.13", "ok": true, "data": {"id": "x.1", "title": "..."}, "error": null}
```

Failure:

```json
{"protocol": "1.13", "ok": false, "data": null,
 "error": {"code": "E_TYPE_WALL", "message": "blocks: epic may not block task",
           "detail": {"from": "x.1", "to": "y.1", "dep_type": "blocks"}}}
```

## Error codes

| Code | Meaning |
|---|---|
| `E_NOT_FOUND` | the id(s) requested do not exist |
| `E_TYPE_WALL` | a `blocks` dep between an epic and a non-epic (pre-checked before any mutation reaches the backend) |
| `E_DEP_CYCLE` | the backend rejected a dep edge as a cycle |
| `E_FIELD_CLOBBER_GUARD` | a field-protecting guard refused the write: notes replaced via `update` instead of appended via `note`; acceptance criteria moved via `update --set-acceptance` instead of `acceptance set`; or `acceptance set` on an item work has started, with no `--why` — `detail` names the `field` and, for the last, the `status` |
| `E_LOCK_CONTENTION` | backend lock contention survived the bounded retry — from `label_mutate`/`sync`, may carry `detail.partial_progress` |
| `E_SYNC_BEHIND` | `sync --pull` with uncommitted local changes |
| `E_OPEN_BLOCKERS` | `close` refused: items blocking this one are still open — `detail.blocked_by` names them |
| `E_NO_WORKSPACE` | no tracker workspace is configured for the directory the verb ran in, so nothing was attempted — a configuration failure to fix, not a defect to report. No verb creates one; see the scope note under the verb table |
| `E_BACKEND_DRIFT` | the backend's output or behavior failed the facade's own model — the drift alarm; `detail.backend_diagnostic` carries what the backend reported, scrubbed of its identity and carrying no contract to match on |
| `E_UNSUPPORTED_CAPABILITY` | the verb is not supported by the active backend's declared `Capabilities` |
| `E_USAGE` | invalid CLI usage — bad flags, missing required args, or a rejected flag combination (e.g. `create` given neither `--raw` nor a noun; noun creation given `--type`/`--label`; `deliver` given flags for the wrong shape) |
| `E_INTERNAL` | an unexpected internal fault — the envelope invariant holds even on facade bugs |
| `E_DUPLICATE_TITLE` | `create <noun>` found an exact, case-sensitive title match before minting — in any status, closed included; `detail` carries the `id` and its `status` |
| `E_NOT_CLAIMABLE` | `claim` refused a container, a blocked leaf, or a closed item |
| `E_EVIDENCE` | `deliver` has no verifiable evidence (`--pr`/`--items`/`--trivial` missing, or `--items` didn't resolve) |
| `E_MANIFEST` | a spec's `## Continuations` section is missing, empty, or fails the manifest grammar |
| `E_TIMEOUT` | a non-idempotent backend mutation (`create`/`note`) timed out; it may have partially applied — run `work reconcile`. A retryable mutation (`label_mutate`/`sync`) surfaces this only after retry exhaustion, and may carry `detail.partial_progress` |

## Consumer handshake

Call `work --protocol-version` once at adapter init and pin the `MAJOR`
component; refuse to run against a mismatched facade rather than risk
mis-parsing mid-run:

```json
{"protocol": "1.13", "ok": true, "data": {"protocol": "1.13"}, "error": null}
```

Every other verb's envelope carries the same `protocol` field at the top
level — the handshake's `data.protocol` and every other verb's `protocol`
are the same value, always.

## Data-shape contract

- `show` with one id → `data` IS the item object (never a single-element
  array). `show` with 2+ ids, `list`, `ready`, `search` → `data =
  {"items": [...]}`.
- Every read item carries `acceptance`: the criteria the item was created
  with, or `null` when it has none. The key is always present on `show`,
  `list`, `ready` and `search` alike, so `null` reads as "this item has no
  criteria" and never as "this verb did not fetch them".
- `acceptance set` → `{"id", "acceptance", "previous", "status"}`: the criteria
  now in force, the ones superseded (`null` where the item had none), and the
  status the item was in when they moved. `previous == acceptance` is the
  no-op case — the criteria were already those, and nothing was written.
- `label list` → a bare `string[]` (never embedded objects).
- `dep list` → `data = {"depends_on": [...], "dependents": [...]}` (bd's own
  inverted `--direction` naming is translated to these names).
- `create --raw` → an object carrying the new item's `id` (see
  `verbs/write.py` for the exact shape).
- `update` / `note` / `reopen` → `data: null` (no return payload).
- `close` and `deliver` report the close-walk under two optional keys, each
  present only when it has something to say (`close` → `data: null` when
  neither does). `walked` is the ids the walk closed, in walk order. `held`
  is the exhausted parents it declined to close because they carry scope of
  their own — each entry carrying that item's `id`, `title`, `acceptance` (or
  `null`), the `reason`, and the `resolve` naming the two ways out, so a
  caller can act on the hold without re-reading the item. The ids a caller
  names on `close` are closed unconditionally; the walk's rules govern only
  what it infers.
- `sync` → `{"synced": ..., "mode": "push" | "pull" | "noop"}`. `"noop"` is
  reserved for server-authoritative backends (the CLI contract spec §6's
  declared no-op); the bd adapter only ever emits `"push"` or `"pull"`.
- `--protocol-version` → `{"protocol": "1.13"}`.

Human-readable output is opt-in only (`--format human`): it renders the
envelope's `data` (or `error`) to **stderr**, for direct human use at a
terminal. stdout is unaffected — it still carries the exact same JSON
envelope as the default `--format json`. Every programmatic consumer parses
stdout; `--format human` exists only for a human running `work` directly.
