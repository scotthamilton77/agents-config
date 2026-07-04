# Work-Facade CLI v1 — Contract Design

**Date:** 2026-07-04
**Status:** Draft (pending review)
**Bead:** agents-config-wgclw.9
**Decision:** One CLI (`work`) with ~10 coarse subcommand verbs over bd, a JSON-envelope output contract, and a backend adapter seam validated on paper against JIRA and GitHub Issues. bd is the only backend implemented in v1.

## 1. Problem

Every tool that drives bd re-implements the same quirk shims. The facade quarantines
bd behind one tested surface (the M0 charter: "beads is quarantined behind our own
CLI"), so bd schema/format drift lands in exactly one place.

Quirk-shim inventory the facade absorbs (each observed in current consumers):

| Quirk | Today's cost |
|---|---|
| `--json` shape drift (`bd show` = single-element array; deps carry full target bead; label list = bare string array) | per-consumer jq/Python parsing idioms |
| Multi-line fields with literal newlines break `jq` | "read with Python, not jq" tribal rule |
| `bd create --parent` auto-creates the dep edge; a second `dep add` is a deadlock error | callers must know the invariant |
| Type walls (`blocks`: epic↔epic, non-epic↔non-epic only) | hard error surfaced late |
| Replace-vs-append field semantics (`--notes` clobbers; `--append-notes` appends) | data-loss foot-gun |
| Default row caps (`list` 50, `ready` 100) silently truncate | "bead missing ≠ bead closed" confusion |
| Lock contention / stale `dolt sql-server` failures | ad-hoc retry advice in rules |
| Sync ceremony (`dolt commit` → `dolt push`; `pull` fails on uncommitted) | memorized recipe |

## 2. What this is / is not (from the bead, restated as contract)

- **IS**: a CLI surface both prgroom's bd-adapter and the PDLC orchestrator's
  bd-adapter shell out to; also usable directly by skills/rules prose.
- **IS NOT**: a unified `WorkTracker` interface across tools (prgroom's
  `prsession.Store` and PDLC's `WorkTracker` abstract different data and stay as
  they are), and NOT a replacement for either tool's internal typed adapter layer.

Locked owner decisions (interview 2026-07-04):

1. **No JIRA implementation — ever, in this repo.** JIRA participates as a
   design-time seam validation only (§7 mapping table).
2. **GitHub Issues is the second implementation** if one is needed for seam
   confidence — testable in this repo. v1 ships bd-only; the GH adapter is a
   follow-up bead gated on seam doubts surviving contract-test review.

## 3. Verb set (derived from observed usage)

Derivation evidence: grep of `bd` invocations across `src/user/.agents/skills/`
(whats-next `collect.py` is the heaviest programmatic consumer: `show`, `list
--status --limit 0`, `ready --limit 0`, `list --label`), the beads plugin rules,
prgroom (`escalation.py` names a deferred bd sink; `.prgroom.toml` chains), and
PDLC's `WorkTracker` protocol (get/bulk-get/children/parent-chain/reparent/
create/status/audit-note). Usage counts: `show` 11, `ready` 5, `label add` 5,
`close` 5, `update` 4, `list` 6, `dep add` 2, `create` 2, sync/reopen/search tail.

| Verb | Covers (bd today) | Notes |
|---|---|---|
| `work show <id>...` | `bd show` (+ batch = PDLC `bulk_get`) | one JSON shape: item + typed dep edges + children |
| `work create` | `bd create` incl. `--parent` | auto-edge quirk absorbed: facade never lets a caller double-add the parent edge |
| `work update <id>` | `bd update` status/claim/title/priority | field semantics explicit: `--set-X` replaces |
| `work note <id> <text>` | `bd update --append-notes` | append-only by contract (PDLC `append_audit_note`); no clobber verb for notes |
| `work close <id>... [--disposition <text>]` | `bd close` (+ note) | batch; disposition lands as an appended note |
| `work reopen <id>` | `bd reopen` | |
| `work list [--status --label --parent --type]` | `bd list` | **unbounded by default** (`--limit` opt-in) — kills the silent-truncation quirk |
| `work ready [--label]` | `bd ready` | unbounded by default |
| `work dep <add\|remove\|list> <id> [<target>]` | `bd dep add/list` | type walls pre-checked → typed error, not backend stderr |
| `work label <add\|remove\|list> <id> [<label>...]` | `bd label *` | multi-label add in one call (bd needs one call per label) |
| `work search <query>` | `bd search` | |
| `work sync [--pull]` | `bd dolt commit` + `push` (or `pull`) | one verb, correct ordering baked in |

Twelve verbs; "~10 coarse" per the bead. `epic`/`stats`/`compact`/`delete` are
deliberately excluded from v1 — no programmatic consumer observed; direct `bd`
remains available for humans.

## 4. Output contract (bead open-Q2)

JSON envelope on stdout, always, exit code mirrors `ok`:

```json
{"protocol": "1.0", "ok": true, "data": { ... }, "error": null}
{"protocol": "1.0", "ok": false, "data": null,
 "error": {"code": "E_TYPE_WALL", "message": "blocks: epic may not block task",
           "detail": {"from": "x.1", "to": "y", "dep_type": "blocks"}}}
```

- `data` shapes are versioned with the protocol (§5) and normalized: `show`
  returns an object (never a single-element array); dep edges are lean
  (`{id, type, status}`, never full embedded beads); labels are always
  `string[]`; multi-line fields are proper JSON strings.
- Human-readable output is opt-in (`--format human`), for direct human use only;
  consumers MUST parse the envelope. Rationale: both known consumers are
  programs shelling out (prgroom Python↔Go boundary, PDLC adapters); evidence
  is every existing `bd … --json` call site.
- Typed error codes (initial set): `E_NOT_FOUND`, `E_TYPE_WALL`, `E_DEP_CYCLE`,
  `E_FIELD_CLOBBER_GUARD`, `E_LOCK_CONTENTION`, `E_SYNC_BEHIND`, `E_BACKEND_DRIFT`
  (bd output failed the facade's own parser — the drift alarm), `E_USAGE`.
- Lock-contention retry: bounded backoff inside the facade; only after
  exhaustion does `E_LOCK_CONTENTION` surface (quirk-shim inventory, last rows).

## 5. Protocol versioning (bead open-Q3)

- Every envelope carries `protocol` (semver `MAJOR.MINOR`). Additive fields bump
  MINOR; any breaking change to envelope or `data` shapes bumps MAJOR.
- `work --protocol-version` prints the version and exits 0 — the consumer
  handshake at adapter init (prgroom/PDLC pin a major and refuse a mismatch at
  startup rather than mis-parsing mid-run).

## 6. Backend adapter seam

Internal interface (not exported): one `Backend` protocol per the verb set's
primitive needs — `get/batch_get, create, set_fields, append_note, close, reopen,
query(filters), ready, dep_mutate, dep_list, label_mutate, labels, search, sync`.
The verb layer owns normalization, typed errors, and retries; adapters own only
backend I/O and concept mapping. v1 ships the `bd` adapter alone.

Capability flags per adapter (`supports_ready`, `supports_dep_types`,
`supports_sync`): a verb a backend cannot honor returns
`E_UNSUPPORTED_CAPABILITY` rather than emulating silently — with two declared
exceptions: `ready` is computed client-side from `query` + dep edges when the
backend lacks blocker semantics (both JIRA and GH need this; bd does not), and
`sync` on a server-authoritative backend succeeds honestly as a declared no-op
(`data.synced: false`) since there is nothing to synchronize.

## 7. Seam validation on paper (no code): JIRA and GitHub Issues

| Facade concept | bd | JIRA (mapping only) | GitHub Issues |
|---|---|---|---|
| item id | `prefix-hash` | issue key `PROJ-123` | `owner/repo#123` |
| type | task/bug/feature/epic/milestone | issue type (incl. Epic) | label or issue type (org-dependent) |
| parent | parent edge | Epic link / parent field | sub-issue / tracked-by |
| dep (`blocks`) | typed dep | issue link "blocks" | none native → convention (task-list refs) + client-side `ready` |
| labels | labels | labels | labels |
| status | open/in_progress/closed/deferred | workflow status (mapped table, per-instance config) | open/closed (+ labels for interim states) |
| notes append | `--append-notes` | comment add | comment add |
| ready | `bd ready` | client-side (JQL + link walk) | client-side (REST + convention walk) |
| sync | dolt commit/push | n/a (server-authoritative) → declared no-op (§6) | n/a → declared no-op (§6) |

Seam verdict: every verb maps or degrades through a declared capability flag; no
verb exists that only bd could implement. That is the confidence target; GH code
happens only if contract-test review still doubts the seam.

## 8. Naming (bead open-Q4 — owner passed)

`ASSUMPTION:` the CLI is named **`work`** — repo AGENTS.md already promises "a
higher-level `work` abstraction is planned", making the name discoverable and
self-documenting; `wt` collides with common git-worktree aliases, `bdsh` leaks
the backend into the name. Binary name is trivially changeable at implementation
time if `work` proves too collision-prone on PATH.

## 9. Sequencing (bead open-Q5 — owner passed) and PDLC timing (open-Q6)

`ASSUMPTION:` facade v1 lands **after prgroom MVP ships** and **before** any
prgroom bd-adapter work starts. Evidence: prgroom's bd escalation sink is
already explicitly deferred ("bd (v2, deferred)" in its escalation module), so
nothing in-flight blocks on the facade; building the facade first would stall
prgroom MVP on a dependency it does not yet consume.
- PDLC (open-Q6): its `WorkTracker` binds the facade only when its first
  bd-backed adapter is written (spec still in flux under the PDLC architecture
  epic); the in-memory tracker stays the test double. The facade's protocol
  handshake (§5) is what makes late binding safe.

## 10. Implementation shape (for the planning pass, not binding)

`ASSUMPTION:` Python package at `packages/workcli/` (uv project, CI-gated like
installer/prgroom — lint, format, mypy strict, coverage floor, audit). Python
over Go: shares toolchain with installer/PDLC; consumers shell out, so runtime
is irrelevant (the bead says language TBD). Thin `work` entry point;
pure verb layer over an injected `Backend`; bd adapter drives the real binary
behind a subprocess boundary port (contract decisions in §4 testable with a
scripted-bd fake, no live Dolt in unit tests).

## 11. Test plan (behavioral contracts)

1. Envelope invariants: every verb, success and failure, emits a parseable
   envelope with `protocol`, and exit code mirrors `ok`.
2. `show` normalization: single id → object; deps lean-shaped; labels `string[]`.
3. `create --parent` never double-adds the parent edge (fake records calls).
4. Type-wall pre-check: epic→task `dep add blocks` → `E_TYPE_WALL`, bd never invoked.
5. `list`/`ready` default unbounded: fake returns >50 rows, all surface.
6. Notes are append-only: two `note` calls concatenate; no verb path reaches
   bd's replace flag.
7. Lock-contention: fake fails N-1 times then succeeds → `ok:true`; fails N
   times → `E_LOCK_CONTENTION`.
8. `sync` ordering: commit before push; `--pull` with dirty state → `E_SYNC_BEHIND`.
9. Drift alarm: fake emits an unrecognized `show` shape → `E_BACKEND_DRIFT`.
10. Protocol handshake: `--protocol-version` output stable; envelope `protocol`
    matches.

## 12. Out of scope

- JIRA adapter code (locked decision — never in this repo).
- GitHub Issues adapter code (follow-up bead, only on surviving seam doubt).
- Migrating existing skills' direct `bd` calls (follow-up, after v1 stabilizes).
- prgroom/PDLC adapter rewrites (each tool owns its adapter; they consume this CLI).
- A `work` TUI/interactive mode.

## 13. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` §8 CLI named `work` (owner passed on naming).
- `ASSUMPTION:` §9 sequencing — after prgroom MVP, before any prgroom bd-adapter
  work (owner passed on sequencing).
- `ASSUMPTION:` §10 Python at `packages/workcli/`, CI-gated like siblings.
- `ASSUMPTION:` §3 v1 verb exclusions (`epic`, `stats`, `compact`, `delete`) —
  no programmatic consumer observed today.
- `ASSUMPTION:` §2/§7 GH Issues implementation deferred until contract-test
  review still doubts the seam; v1 is bd-only.
- `ASSUMPTION:` §4 envelope field names and initial error-code set.
