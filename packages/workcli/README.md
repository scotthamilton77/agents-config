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

## Verb table

Twelve verbs; each is a subcommand of `work`.

| Verb | Args/flags |
|---|---|
| `work show IDS...` | — |
| `work create --raw --title T [--description D] [--type task] [--priority P2] [--parent ID] [--label L ...]` | `--label` repeatable |
| `work update ID [--set-title T] [--set-priority P] [--set-description D]` | ≥1 `--set-*` required; `--set-notes` → `E_FIELD_CLOBBER_GUARD` (suppressed from `--help` — tripwire only) |
| `work note ID TEXT` | append-only |
| `work close IDS... [--disposition TEXT]` | disposition = one appended note per id |
| `work reopen ID` | — |
| `work list [--status S] [--label L] [--parent ID] [--type T] [--limit N]` | unbounded unless `--limit` |
| `work ready [--label L]` | unbounded |
| `work dep {add,remove,list} ID [TARGET] [--type blocks]` | `dep add A B` = A depends on B |
| `work label {add,remove,list} ID [LABELS...]` | multi-label in one call |
| `work search QUERY` | — |
| `work sync [--pull]` | — |
| global | `--format {json,human}` (human renders to **stderr**; stdout envelope unchanged), `--protocol-version` |

`epic`/`stats`/`compact`/`delete` are deliberately out of scope for v1 — no
programmatic consumer observed; use `bd` directly for those.

## Envelope contract

Every invocation writes exactly one JSON object to stdout, always, whether
the verb succeeds or fails. Exit code mirrors `ok` (`0` on success, `1` on
failure). `--format human` (see below) never changes this — it only adds a
second, human-readable rendering on stderr.

Success:

```json
{"protocol": "1.0", "ok": true, "data": {"id": "x.1", "title": "..."}, "error": null}
```

Failure:

```json
{"protocol": "1.0", "ok": false, "data": null,
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
| `E_LOCK_CONTENTION` | backend lock contention survived the bounded retry |
| `E_SYNC_BEHIND` | `sync --pull` with uncommitted local changes |
| `E_BACKEND_DRIFT` | the backend's output or behavior failed the facade's own model — the drift alarm |
| `E_UNSUPPORTED_CAPABILITY` | the verb is not supported by the active backend's declared `Capabilities` |
| `E_USAGE` | invalid CLI usage (bad flags, missing required args, `create` without `--raw`) |
| `E_INTERNAL` | an unexpected internal fault — the envelope invariant holds even on facade bugs |

## Consumer handshake

Call `work --protocol-version` once at adapter init and pin the `MAJOR`
component; refuse to run against a mismatched facade rather than risk
mis-parsing mid-run:

```json
{"protocol": "1.0", "ok": true, "data": {"protocol": "1.0"}, "error": null}
```

Every other verb's envelope carries the same `protocol` field at the top
level — the handshake's `data.protocol` and every other verb's `protocol`
are the same value, always.

## Data-shape contract

- `show` with one id → `data` IS the item object (never a single-element
  array). `show` with 2+ ids, `list`, `ready`, `search` → `data =
  {"items": [...]}`.
- `label list` → a bare `string[]` (never embedded objects).
- `dep list` → `data = {"depends_on": [...], "dependents": [...]}` (bd's own
  inverted `--direction` naming is translated to these names).
- `create --raw` → an object carrying the new item's `id` (see
  `verbs/write.py` for the exact shape).
- `update` / `note` / `close` / `reopen` → `data: null` (no return payload).
- `sync` → `{"synced": ..., "mode": "push" | "pull" | "noop"}`. `"noop"` is
  reserved for server-authoritative backends (the CLI contract spec §6's
  declared no-op); the bd adapter only ever emits `"push"` or `"pull"`.
- `--protocol-version` → `{"protocol": "1.0"}`.

Human-readable output is opt-in only (`--format human`): it renders the
envelope's `data` (or `error`) to **stderr**, for direct human use at a
terminal. stdout is unaffected — it still carries the exact same JSON
envelope as the default `--format json`. Every programmatic consumer parses
stdout; `--format human` exists only for a human running `work` directly.
