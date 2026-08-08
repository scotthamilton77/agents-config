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

Twelve verbs; each is a subcommand of `work`.

| Verb | Args/flags |
|---|---|
| `work show IDS...` | — |
| `work create --raw --title T [--description D] [--type task] [--priority P2] [--parent ID] [--label L ...]` | `--label` repeatable |
| `work update ID [--set-title T] [--set-priority P] [--set-description D]` | ≥1 `--set-*` required; `--set-notes` → `E_FIELD_CLOBBER_GUARD` (suppressed from `--help`) |
| `work note ID TEXT` | append-only |
| `work close IDS... [--disposition TEXT]` | disposition = one appended note per id |
| `work reopen ID` | — |
| `work list [--status S] [--label L] [--parent ID] [--type T] [--limit N]` | unbounded unless `--limit` |
| `work ready [--label L]` | unbounded |
| `work dep {add,remove,list} ID [TARGET] [--type blocks]` | `dep add A B` = A depends on B |
| `work label {add,remove,list} ID [LABELS...]` | multi-label in one call |
| `work search QUERY [--in FIELD] [--status S] [--limit N]` | reads title, description and notes, every status, unbounded — `--in` (repeatable) narrows the fields, `--status`/`--limit` the rest |
| `work sync [--pull]` | — |
| global | `--format {json,human}` (human renders to **stderr**; stdout envelope unchanged), `--protocol-version`, `--config PATH` (explicit `project-config.toml`; overrides the upward search — track-layer surfaces only, see below) |

`epic`/`stats`/`compact`/`delete` are deliberately out of scope for v1 — no
programmatic consumer observed. A consumer that needs one adds it here; the
facade does not expose a way around itself.

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
| `work reconcile [--dry-run]` | recovery sweep over the states the tracker can still observe: interrupted delivers, unreconciled placeholders, interrupted expansions — idempotent, safe to run from any session or cron |

Protocol is `"1.10"` — additive-only bumps (new `ErrorCode` members, the
derived `Item.track` field and the `acceptance` field beside it, the
capability-disposition model, `partial_progress` detail below, `search`'s
optional narrowing flags, and the close-walk's `held` key) never change an
existing envelope or data shape. A bump can still change what an unchanged
call *answers*, in either direction: 1.8 makes `search` read descriptions and
notes as well as titles, stop excluding closed items, and stop stopping at
the first page, so a query that used to return nothing may now return matches
— and `create <noun>` refuses a title a closed item already carries. 1.10
narrows instead: the close-walk stops closing a parent that carries scope of
its own, so a parent that used to appear under `walked` now appears under
`held` with what is unfinished named. `Capabilities` splits `ready` and `sync` into a `ReadySupport`/
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
{"protocol": "1.10", "ok": true, "data": {"id": "x.1", "title": "..."}, "error": null}
```

Failure:

```json
{"protocol": "1.10", "ok": false, "data": null,
 "error": {"code": "E_TYPE_WALL", "message": "blocks: epic may not block task",
           "detail": {"from": "x.1", "to": "y.1", "dep_type": "blocks"}}}
```

## Error codes

| Code | Meaning |
|---|---|
| `E_NOT_FOUND` | the id(s) requested do not exist |
| `E_TYPE_WALL` | a `blocks` dep between an epic and a non-epic (pre-checked before any mutation reaches the backend) |
| `E_DEP_CYCLE` | the backend rejected a dep edge as a cycle |
| `E_FIELD_CLOBBER_GUARD` | an attempt to replace notes via `update` instead of appending via `note` |
| `E_LOCK_CONTENTION` | backend lock contention survived the bounded retry — from `label_mutate`/`sync`, may carry `detail.partial_progress` |
| `E_SYNC_BEHIND` | `sync --pull` with uncommitted local changes |
| `E_OPEN_BLOCKERS` | `close` refused: items blocking this one are still open — `detail.blocked_by` names them |
| `E_NO_WORKSPACE` | no tracker workspace is configured for the directory the verb ran in, so nothing was attempted — a configuration failure to fix, not a defect to report |
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
{"protocol": "1.10", "ok": true, "data": {"protocol": "1.10"}, "error": null}
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
- `--protocol-version` → `{"protocol": "1.10"}`.

Human-readable output is opt-in only (`--format human`): it renders the
envelope's `data` (or `error`) to **stderr**, for direct human use at a
terminal. stdout is unaffected — it still carries the exact same JSON
envelope as the default `--format json`. Every programmatic consumer parses
stdout; `--format human` exists only for a human running `work` directly.
