# prgroom CLI — C4 Level 3: PR Session Store *(stub)*

> **Up**: [index](index.md)
> **Source bead**: `agents-config-fca6.12`
> **Source spec**: [`docs/plans/2026-05-12-prgroom-cli-design.md`](../../plans/2026-05-12-prgroom-cli-design.md) — Section 2 (`prsession.Store` interface + state schema)
> **Container**: `internal/prsession/` inside the prgroom binary (see [`c4-l2-container.md`](c4-l2-container.md))
> **Status**: **STUB** — placeholder pending the `internal/prsession` implementation bead.

## Why this is a stub

Section 2 of the source spec is ratified at the interface level (`Store` shape, three adapters, transactional model, schema versioning). The internal component breakdown of `internal/prsession/` is not yet pinned at the same implementation-readiness level as `internal/lifecycle/` because no `[Impl]` child bead has opened against `internal/prsession/` yet.

This stub establishes the file's home and the components the eventual drawing must cover. When the impl bead opens, this file gets re-drawn at the same fidelity as the lifecycle L3.

## Expected components (when drawn)

The diagram should cover these named units inside `internal/prsession/`:

### Interface + dispatch

- **`Store` interface** — the public surface (§2): `Read / Write / Lock / List / Delete`. All five methods carry a `PRRef` parameter; the interface is per-PR keyed.
- **Adapter registry** — the runtime selector that maps `--store file` / `--store bd` / `PRGROOM_STORE` to a concrete adapter constructor. Default = `file`.
- **`PRGroomingState` type + schema validator** — the canonical schema (§2). Owns `schema_version` constant. Read-path validates the on-disk JSON; `STATE_SCHEMA_UNKNOWN` (exit 78) trips on mismatch.
- **Atomicity primitive** — `WriteAtomic(path, bytes) error` helper that `mktemp`s a sibling file then `rename(2)`s onto the target path. Used by every adapter that backs to a filesystem.

### Adapters

- **`file` adapter** — MVP default.
  - Path resolver: `$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`, fallback `~/.local/state/prgroom/`.
  - `flock(2)` lock holder. OS-released on process death (§3.7 line 958) — no stale-lock detection code.
  - Uses `WriteAtomic`.
- **`memory` adapter** — tests only.
  - Build-tag-gated (`//go:build test_only`) or test-package-scoped to prevent production import.
  - In-process `map[PRRef]*PRGroomingState`; `sync.Mutex` per ref for `Lock`.
- **`bd` adapter** — **v2 (deferred)**.
  - Persists `PRGroomingState` JSON in a linked bead's `notes` field (cap ~65KB; externalise to a path-ref on overflow).
  - Linkage label: `for-pr-<owner>-<repo>-<n>`.
  - Lock: transient bd label `prgroom-lock-<pid>` written / removed via single `bd update`.
  - Atomicity: `bd update --notes <new>` replaces the entire field — no partial write possible.
  - **NOT in MVP.** Component is named here so the L3 has a slot when v2 opens.

### Schema-migration plumbing

- **Version constant** — `SchemaVersion = 1` in MVP. Bumped on any incompatible schema change.
- **Migration registry** — a `map[int]func(oldBytes []byte) (newBytes []byte, error)` keyed by source version. MVP is empty (no migrations exist yet). Surface is reserved so the v2 → v3 path doesn't require adapter changes.
- **Read-path branch** — on `schema_version` mismatch with a registered migration: rewrite the state file in place via `WriteAtomic`, then proceed. Without a registered migration: trip `STATE_SCHEMA_UNKNOWN`.

### Transactional model (§2)

The transactional contract is at the verb level + the `run` aggregate level:

- **Verb-level** — every public verb (the locking wrappers around `*Locked` functions) atomically replaces the full state at the end of its work. Crashed processes leave the prior `Write` intact; no partial state can exist on disk (per §2 + §3.7 `flock(2)` semantics).
- **Run-aggregate level** — `runLocked` (§3.3) holds the lock for an entire cycle; each `*Locked` invocation does its own atomic `Write` before returning, so the state file is recoverable to the last completed verb even if the process dies mid-cycle.

These commitments are realised by the `Store` interface itself — there are no explicit transaction begin/end methods. `Lock` + atomic `Write` + per-`*Locked` Write discipline is the transaction.

## Out of scope for this L3 (when drawn)

- **`PRGroomingState` schema content** — the fields themselves (`Phase`, `Round`, `Items`, `Reviewers`, `Quiescence`, etc.) live in [`data-view.md`](data-view.md). This L3 covers the *adapter / migration / atomicity machinery*, not the data shape.
- **Operator-facing state-file inspection tooling** — `prgroom status --json` is built by `internal/lifecycle` reading state through the `Store`; it's not a `prsession` component.
- **Cross-PR enumeration semantics** — `List() ([]PRRef, error)` is on the interface; the `sweep` verb (`internal/lifecycle` or `cmd/prgroom`) consumes it. The adapter implementation is straightforward (file: `readdir` and parse filenames; bd: `bd list --label for-pr-*`).

## Cross-references

- **Container view**: [`c4-l2-container.md`](c4-l2-container.md)
- **Lifecycle that consumes the Store**: [`c4-l3-lifecycle.md`](c4-l3-lifecycle.md)
- **Data shape stored**: [`data-view.md`](data-view.md)
- **Source spec**: [Section 2 — `prsession.Store` interface + state schema](../../plans/2026-05-12-prgroom-cli-design.md)
