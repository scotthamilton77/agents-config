# prgroom CLI — C4 Level 3: PR Session Store *(stub)*

> **Up**: [index](index.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md) — Section 2 (`prsession.Store` Protocol + state schema) + Section 8 (PR-memory read path)
> **Container**: `src/prgroom/prsession/` inside the prgroom package (see [`c4-l2-container.md`](c4-l2-container.md))
> **Status**: **STUB** — placeholder pending the `src/prgroom/prsession` implementation bead.

## Why this is a stub

Section 2 of the source spec is ratified at the interface level (`Store` shape, three adapters, transactional model, schema versioning). The internal component breakdown of `src/prgroom/prsession/` is not yet pinned at the same implementation-readiness level as `src/prgroom/lifecycle/` because no `[Impl]` child bead has opened against `src/prgroom/prsession/` yet.

This stub establishes the file's home and the components the eventual drawing must cover. When the impl bead opens, this file gets re-drawn at the same fidelity as the lifecycle L3.

## Expected components (when drawn)

The diagram should cover these named units inside `src/prgroom/prsession/`:

### Protocol + dispatch

- **`Store` Protocol** — the public surface (§2): `read / write / lock / list_refs / delete`. All five methods carry a `PRRef` parameter; the Protocol is per-PR keyed. Concrete adapters **structurally satisfy** the Protocol (no inheritance — `mypy --strict` checks the structural fit, exactly as `pdlc`'s `InMemoryWorkTracker` satisfies `WorkTracker`).
- **Adapter registry** — the runtime selector that maps `--store file` / `--store bd` / `PRGROOM_STORE` to a concrete adapter constructor. Default = `file`.
- **`PRGroomingState` type + schema validator** — the canonical schema (§2). Owns `schema_version` constant. Read-path validates the on-disk JSON; `STATE_SCHEMA_UNKNOWN` (exit 78) trips on mismatch.
- **Atomicity primitive** — a `write_atomic(path, data)` helper that writes to a `tempfile.NamedTemporaryFile` sibling then `os.replace`s onto the target path. Used by every adapter that backs to a filesystem.

### Adapters

- **`file` adapter** (`FileStore`) — MVP default.
  - Path resolver: `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`, fallback `~/.local/state/prgroom/`.
  - `fcntl.flock(fd, LOCK_EX)` lock holder. OS-released on process death (§3.7) — no stale-lock detection code.
  - Uses `write_atomic`.
- **`memory` adapter** (`InMemoryStore`) — tests only.
  - **Test-package-scoped** — lives under `tests/`, structurally satisfies the `Store` Protocol, and is never imported by production code (Python has no build tags; visibility is enforced by package layout, not a compile-time gate).
  - In-process `dict[PRRef, PRGroomingState]`; `threading.Lock` per ref for `lock`.
- **`bd` adapter** — **v2 (deferred)**.
  - Persists `PRGroomingState` JSON in a linked bead's `notes` field (cap ~65KB; externalise to a path-ref on overflow).
  - Linkage label: `for-pr-<owner>-<repo>-<n>`.
  - Lock: transient bd label `prgroom-lock-<pid>` written / removed via single `bd update`.
  - Atomicity: `bd update --notes <new>` replaces the entire field — no partial write possible.
  - **NOT in MVP.** Component is named here so the L3 has a slot when v2 opens.

### Schema-migration plumbing

- **Version constant** — `SchemaVersion = 1` in MVP. Bumped on any incompatible schema change.
- **Migration registry** — a `dict[int, Callable[[bytes], bytes]]` keyed by source version (each migrator raises on failure). MVP is empty (no migrations exist yet). Surface is reserved so the v2 → v3 path doesn't require adapter changes.
- **Read-path branch** — on `schema_version` mismatch with a registered migration: rewrite the state file in place via `write_atomic`, then proceed. Without a registered migration: trip `STATE_SCHEMA_UNKNOWN`.

### Transactional model (§2)

The transactional contract is at the verb level + the `run` aggregate level:

- **Verb-level** — every public verb (the locking wrappers around the `_`-prefixed internal functions) atomically replaces the full state at the end of its work. Crashed processes leave the prior `write` intact; no partial state can exist on disk (per §2 + §3.7 `flock(2)` semantics).
- **Run-aggregate level** — `_run` (§3.3) holds the lock for an entire cycle; each `_`-prefixed invocation does its own atomic `write` before returning, so the state file is recoverable to the last completed verb even if the process dies mid-cycle.

These commitments are realised by the `Store` Protocol itself — there are no explicit transaction begin/end methods. `lock` + atomic `write` + per-`_`-prefixed write discipline is the transaction.

### §8 PR-memory — read-path source, no schema change

The §8 PR-memory read path (§8.1) reads *through* this Store but adds **no** persisted fields. Before each fix dispatch, `src/prgroom/lifecycle` assembles the complete-PR snapshot, sourcing **prior-round dispositions** (`kind` / `rationale` / `commits` / `decided_by`) from the `PRGroomingState` this Store already persists (§2). The per-item `recurrence` signal is **derived from that disposition history at snapshot-assembly time** (§8.2) — never read from or written to the Store. `schema_version` therefore **stays `1`**: no `memory`, no `recurrence`, no Decisions-block fields enter the persisted schema — the PR itself is the durable memory (§8.0).

## Out of scope for this L3 (when drawn)

- **`PRGroomingState` schema content** — the fields themselves (`phase`, `round`, `items`, `reviewers`, `quiescence`, etc.) live in [`data-view.md`](data-view.md). This L3 covers the *adapter / migration / atomicity machinery*, not the data shape.
- **Operator-facing state-file inspection tooling** — `prgroom status --json` is built by `src/prgroom/lifecycle` reading state through the `Store`; it's not a `prsession` component.
- **Cross-PR enumeration semantics** — `list_refs() -> list[PRRef]` is on the Protocol; the `sweep` verb (`src/prgroom/lifecycle` or `cli.py`) consumes it. The adapter implementation is straightforward (file: read the state dir and parse filenames; bd: `bd list --label for-pr-*`).

## Cross-references

- **Container view**: [`c4-l2-container.md`](c4-l2-container.md)
- **Lifecycle that consumes the Store**: [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md)
- **Data shape stored**: [`data-view.md`](data-view.md)
- **Source spec**: [Section 2 — `prsession.Store` Protocol + state schema](../../plans/2026-05-12-prgroom-cli-design.md)
