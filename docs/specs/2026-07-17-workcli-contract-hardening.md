# workcli Contract Hardening — Containerhood Unification + Backend Seam

**Date:** 2026-07-17
**Status:** Draft — pending review
**Beads:** agents-config-wgclw.9.6 (containerhood), agents-config-38o1v (Backend seam); both children of the work-facade CLI epic `agents-config-wgclw.9`
**Decision:** Two contract-hardening decisions for workcli, grouped because both
pin seam/guard contracts before the facade deploys. (1) Declared state stays the
sole containerhood definition at every lifecycle guard; the legacy child-inferred
container population is migrated by a one-shot supervised shape-stamping sweep,
and the interim router's child-count inference is removed once the sweep's exit
criterion holds. (2) The Backend seam's capability surface is reshaped into
domain-shaped dispositions (read/write split for deps, disposition enums for
sync/ready), and the multi-step mutation primitives gain an idempotent-retry +
structured partial-progress contract.

## 1. Containerhood unification (plan --done child-guard)

The facade defines containerhood exactly once, in declared state: `is_container`
(`packages/workcli/src/workcli/lifecycle/__init__.py`) is true when a bead carries
a container-shape label (`shape-spec`, `shape-epic`, `shape-impl-container`) or is
of bd type `epic`/`milestone`. Every guard reads that one predicate — `claim`
refuses containers, `plan --done` requires one (or `--force`), `deliver` refuses
one. This is the work-lifecycle spec's invariant 5: "state is declared, not
inferred … never deduced from the shape of the tree."

The break is with the legacy population that predates the shape vocabulary. A
feature-typed spec container with no shape label, and a task-typed
container-with-children, are both invisible to the declared-state test yet are
real containers. The interim skill router (`src/user/.agents/skills/whats-next/collect.py`) still
recognizes them the old way — by counting non-closed children — so today the
router and the facade guards disagree on the same bead: the router hides it from
implementation queues as a container while `plan --done` rejects it as a non-container.
The two definitions must collapse to one, and the declared one wins.

### Decision

1. **Declared state is the sole containerhood definition, strict at every guard.**
   `is_container` remains declared-state only — a shape label or an `epic`/`milestone`
   bd type — with no child-count fallback, at `claim`, `plan --done`, `deliver`, and
   any future guard. Invariant 5 stands unamended. `--force` remains the documented
   escape hatch for stamping an as-yet-unstamped bead as planned.

2. **Legacy containers are migrated by a one-shot supervised shape-stamping sweep.**
   Every non-closed child-bearing bead lacking a declared containerhood marker is
   stamped with the correct shape label so the declared test recognizes it. The sweep
   runs inside the same supervised session as the track-backfill run but as a separate,
   independent script step with zero code coupling to the track layer.

3. **Legacy child-count inference in read/routing paths is removed — but only after
   the sweep's exit criterion passes.** The removal is gated on a mechanically-runnable
   check reporting zero non-closed child-bearing beads that lack a declared
   containerhood marker. Until that check is green the router keeps the legacy fallback;
   once green the router keys on declared markers alone, matching the facade.

### Inference-site inventory

Searched `packages/workcli/src/workcli` and `src/user/.agents/skills` /
`src/user/.claude`. The only child-count-based *containerhood* inference lives in
the interim router; every workcli `.children` read is operational, not a
containerhood test.

| Site | Lines | What it infers | Disposition |
|---|---|---|---|
| `whats-next/collect.py` — `CONTAINER_DESIGN = {"feature"}` | 191 | marks `feature` as child-count-conditional container | remove-after-sweep |
| `whats-next/collect.py` — `active_child_count` index build + fail-closed guard | 200, 464–489 | per-parent non-closed-child tally driving container tests | remove-after-sweep |
| `whats-next/collect.py` — `is_container(bead_id, bead_type)` | 203–223 | `feature` → container iff `active_child_count > 0` | remove-after-sweep (replace with declared-marker read) |
| `whats-next/collect.py` — `in_planning(b)` | 525–533 | planning-queue membership via `active_child_count != 0` | remove-after-sweep (replace with declared-marker read) |
| `whats-next/collect.py` — Filter Matrix docstring | 134–224 | codifies type × non-closed-children routing | remove-after-sweep (rewrite to declared shape) |
| `whats-next/collect.py` — `is_impl_candidate` | 242–256 | calls child-based `is_container` | update to declared read |
| workcli `is_container` | `__init__.py` 53–57 | declared shape-label OR `epic`/`milestone` type | **keep** — the canonical declared definition |
| workcli `_CONTAINER_TYPES = {epic, milestone}` | `__init__.py` 15 | bd-type test | **keep** — bd type is declared state, not child count |
| `create.py` `.children`; `deliver.py` `.children` (70, 239, 276); `reconcile.py` `children == []` | — | mint-missing-children, close-walk enumeration, leaf detection | **keep** — operational, never a containerhood test |

### Shape-stamping sweep

A one-shot script under `scripts/` (migration code earns no permanent residence),
run read-only-first then supervised-apply:

- **Input.** A live census of all non-closed beads (`bd list --status open,in_progress
  --limit 0 --json`), with child edges derived from the `parent` field — bd exposes no
  `children` key on `list`/`show`, so child-bearing is computed by grouping on `parent`.
- **Classification.** A bead is a stamp candidate when it bears ≥1 non-closed child
  AND carries no declared containerhood marker (no `shape-spec`/`shape-epic`/
  `shape-impl-container` label and bd type not in `{epic, milestone}`). Proposed shape:
  a `feature`-typed candidate → `shape-spec`; any other candidate carrying children →
  `shape-impl-container` (the declared multi-unit impl-container shape). `epic`/`milestone`
  beads are already declared by type and are never candidates.
- **Supervised flow.** Emit the proposal set for human confirmation (unambiguous
  proposals batch-applied; any bead whose correct shape is unclear is queued for the
  supervising human, never auto-stamped). Apply confirmed stamps via label add. No leaf
  is ever stamped — the child-bearing predicate is the gate.
- **Idempotency.** Label add is set-union and a bead already bearing a declared marker
  is not a candidate, so a re-run stamps nothing new and is a clean no-op. Re-running
  after a partial/interrupted run converges.
- **Exit-criterion check.** A mechanically-runnable lint-style check (its own script
  entry, or a `work lint`-style invariant) that enumerates non-closed beads bearing a
  non-closed child and reports every one lacking a declared containerhood marker. Exit
  zero with an empty violation list is the criterion; nonzero lists the violators. This
  check is the gate on Decision 3's router cutover — it may be run standalone at any time,
  independent of the sweep.
- **Sequencing.** Rides the same supervised session as the track-backfill supervised run
  (the track-partition design spec’s §7 backfill continuation — a cross-spec *scheduling*
  coupling only),
  as a separate independent step. No shared code, no shared state; either may run first.
  Match that run's exit-criterion style: a lint invariant reporting zero violations,
  held before the dependent flip proceeds.

### Acceptance criteria

1. `is_container` (workcli) is unchanged declared-state: a childless `epic` is refused
   at `claim`, and a `feature` with non-closed children but no shape label is treated as
   a non-container by every workcli guard (`claim`, `plan --done`, `deliver`).
2. `plan --done` on a legacy feature spec-container lacking a shape label fails
   `E_USAGE` without `--force` and succeeds with `--force`; on a `shape-spec`/`shape-epic`/
   `shape-impl-container` bead it succeeds without `--force`.
3. The sweep, over a fixture holding {feature+children no shape, task+children no shape,
   already `shape-spec`, childless leaf}, stamps `shape-spec` on the first, `shape-impl-container`
   on the second, and leaves the last two untouched; a second run stamps nothing.
4. The exit-criterion check exits zero with an empty violation list exactly when no
   non-closed bead bears a non-closed child while lacking a declared marker, and exits
   nonzero enumerating the violators otherwise.
5. After the check is green and the router cutover lands, `whats-next/collect.py` contains
   no `active_child_count`, no `CONTAINER_DESIGN`, and no child-count comparison
   (grep-checkable); its `is_container` keys only on declared markers (shape labels plus
   `epic`/`milestone` type).
6. On a fully-stamped fixture, the cutover router's queue routing (planning / brainstorm /
   implementation) is identical to the pre-removal child-inference router's routing —
   behavioral equivalence once the data is stamped.

## 2. Backend seam hardening

The `Backend` seam (`packages/workcli/src/workcli/backend.py`) is internal and
unexported, so contract changes cost nothing today — workcli is not yet wired
into the installer and bd is the only adapter. A holistic review of PR #241
surfaced four seam risks; items 3 (retry-on-timeout) and 4 (batch_get pinning)
shipped with the lifecycle layer. The two remaining items are pure seam-contract
questions with no bd-observable change, because bd sits at the "everything
native" corner of every capability axis — they exist to keep the seam honest for
the future GitHub-Issues adapter the transport spec (§6/§7) validated on paper.

Both decisions below keep `PROTOCOL_VERSION` at `1.0`. `Capabilities` is
internal (transport spec §6: "not exported"), so reshaping it is invisible to
the envelope; the only externally observable behaviors change for *non-bd*
backends that do not exist yet. No envelope or `data` shape changes.

### Item 1 — Capabilities granularity

The three `Capabilities` booleans conflate two orthogonal questions: *can the
backend perform this operation* and *what should the facade do when it cannot*.
`supports_dep_types=False` blocks the whole `dep` verb — including read-only
`dep list`, which a convention-based backend (GitHub task-list refs, §7) can
still serve. `supports_sync=False` can only yield `E_UNSUPPORTED_CAPABILITY`; it
cannot express the transport spec's own §6 promise of an honest
server-authoritative no-op (`data.synced: false`, `mode: "noop"` — a value
`SyncResult` already reserves in `model.py`).

| Alternative | Shape | Verdict |
|---|---|---|
| A. Per-verb capability map | `dict[verb, bool]` | Rejected — read/write still conflated *within* the `dep` verb (add vs list are one verb); says nothing about sync's third state. |
| B. Uniform tri-state enum on all three | each cap → `{NATIVE, EMULATED, UNSUPPORTED}` | Rejected — forces one vocabulary onto three unlike axes; `EMULATED` is meaningless for a dep *write*, and the dep read/write split is unrepresentable in a single value. |
| **C. Domain-shaped dispositions (chosen)** | dep → read ungated + `supports_dep_write: bool`; sync/ready → disposition enum | Each capability's type matches its real variance: read/write is the honest axis for deps, native/no-op/unsupported for sync. |

**Decision — C.** Model each capability with the type its honest degrees of
freedom demand. `dep` reads are always available (every seam-target backend can
at least enumerate relationships), so `dep list` is ungated and only typed dep
*writes* are gated by a boolean. `sync` and `ready` each become a disposition
enum, so a backend can declare an honest no-op / emulated path instead of a
binary can/can't. `ready` is converted in the same pass for consistency (the
gate already special-cases it); the `EMULATED` client-side computation itself is
deferred to the GH-adapter bead (bd is `NATIVE`), so a backend declaring
`EMULATED` today is guarded as unreachable until that path lands.

```python
class SyncSupport(StrEnum):
    NATIVE = "native"                          # real sync (bd dolt commit/push)
    SERVER_AUTHORITATIVE = "server_authoritative"  # nothing to sync → honest no-op success
    UNSUPPORTED = "unsupported"                 # → E_UNSUPPORTED_CAPABILITY

class ReadySupport(StrEnum):
    NATIVE = "native"       # backend computes ready (bd ready)
    EMULATED = "emulated"   # facade computes from query + dep edges (GH-adapter bead)
    UNSUPPORTED = "unsupported"

@dataclass(frozen=True)
class Capabilities:
    ready: ReadySupport
    sync: SyncSupport
    supports_dep_write: bool   # typed dep add/remove; `dep list` is never gated
```

`BdBackend.capabilities` → `Capabilities(ready=ReadySupport.NATIVE,
sync=SyncSupport.NATIVE, supports_dep_write=True)`.

The gate predicate widens to see the subcommand so gating stays centralized in
`cli.py` (never scattered into handlers):

```python
REQUIRED_CAPABILITY: dict[str, Callable[[Capabilities, Namespace], bool]] = {
    "ready": lambda c, a: c.ready is not ReadySupport.UNSUPPORTED,
    "sync":  lambda c, a: c.sync is not SyncSupport.UNSUPPORTED,
    "dep":   lambda c, a: a.dep_op == "list" or c.supports_dep_write,
}
```

The `sync` verb handler (`verbs/syncing.py`) branches on the disposition:
`NATIVE` → `backend.sync(pull)`; `SERVER_AUTHORITATIVE` →
`SyncResult(synced=False, mode="noop")` *without* calling `backend.sync`;
`UNSUPPORTED` is already refused at the gate.

**Error-code / protocol impact:** none new. `E_UNSUPPORTED_CAPABILITY` keeps its
meaning (genuinely unsupported only). bd stays at the native corner, so its
observable contract is unchanged and `PROTOCOL_VERSION` stays `1.0`.

### Item 2 — Multi-step mutation partial-progress

Two seam primitives are irreducibly multi-call: `label_mutate` (one `bd label`
call per label — a bd limitation) and `sync` (`dolt commit` then `dolt push`).
When call *k* of *n* fails, the raised `WorkError` carries only that call's
`argv`/`stderr` (via `map_bd_failure`); a caller cannot tell "nothing applied"
from "labels 1..k-1 applied, k failed." `dep_list` is also two-call but
read-only (no partial-mutation hazard). Composed multi-step at the *verb* layer
(e.g. `close` then disposition `note`) is out of seam scope — it already
recovers through the lifecycle's in-band markers (`[work] delivered:`) and
`reconcile` (lifecycle plan L7/L10).

| Alternative | Verdict |
|---|---|
| A. Decompose to single-call primitives | Partial — pushes the loop (and the same partial-progress gap) up to the caller; doesn't help sync, whose commit-before-push ordering is essential. |
| B. Structured partial-result detail | Diagnosable, resumable, no new failure mode. Alone it still lets a caller retry into a half-applied state blindly. |
| **A+B. Idempotent-retry + structured detail (chosen)** | Idempotency makes retry-from-top the recovery; structured detail makes the failure diagnosable and lets `reconcile` prioritize. |
| C. Seam-level transactions | Rejected — bd/dolt cannot roll back a completed `push`, and there is no cross-invocation transaction primitive. |

**Decision — A+B.** Pin a contract on the declared multi-step seam primitives
(`label_mutate`, `sync`):

1. **Idempotent as a whole** — re-invoking the same primitive with the same
   arguments completes safely. The adapter MUST absorb bd's "label already
   present" / "label absent" stderr as success (the marker-tolerance pattern
   already used for `nothing to commit`), and `sync` re-commit/re-push is
   already tolerant.
2. **Structured partial-progress on failure** — a mid-sequence failure raises
   the *cause-coded* `WorkError` (`E_LOCK_CONTENTION`, `E_BACKEND_DRIFT`, …,
   unchanged — the cause is preserved, not replaced) with a `partial_progress`
   record added to `detail`.
3. **Absence means atomic** — a `WorkError` from any single-call primitive, or a
   multi-step primitive that failed on step 1, carries no `partial_progress`
   key; its absence is the contract signal that no sub-step applied.

```python
@dataclass(frozen=True)
class StepProgress:
    operation: str            # "label_mutate" | "sync"
    steps_total: int
    completed: tuple[str, ...]  # replayable sub-step ids (labels applied; ["commit"])
    failed: str                 # the sub-step that failed
    remaining: tuple[str, ...]

    def as_detail(self) -> dict[str, JsonValue]:
        return {"partial_progress": {
            "operation": self.operation, "steps_total": self.steps_total,
            "completed": list(self.completed), "failed": self.failed,
            "remaining": list(self.remaining)}}

def with_progress(err: WorkError, progress: StepProgress) -> WorkError:
    return WorkError(err.code, err.message, {**err.detail, **progress.as_detail()})
```

`label_mutate` tracks applied labels and wraps the mapped failure with
`with_progress(...)`; `sync` on a push failure attaches
`StepProgress("sync", 2, ("commit",), "push", ())`.

**Error-code / protocol impact:** none new. `detail` is already open
`JsonValue`; adding the `partial_progress` key is additive and unschema'd, so
`PROTOCOL_VERSION` stays `1.0`. A MINOR bump to *advertise* the key in
`--protocol-version` is an optional documented follow-up, not this bead.

### Acceptance criteria

1. `Capabilities` exposes `ready: ReadySupport`, `sync: SyncSupport`,
   `supports_dep_write: bool`; a grep finds no `supports_ready` /
   `supports_dep_types` / `supports_sync` boolean fields remaining.
2. `BdBackend.capabilities == Capabilities(ReadySupport.NATIVE,
   SyncSupport.NATIVE, True)`.
3. `work dep list <id>` against a fake with `supports_dep_write=False` → `ok:
   true`; `work dep add`/`dep remove` on the same → `ok: false`,
   `E_UNSUPPORTED_CAPABILITY`, and `backend.dep_mutate` is never called.
4. `work sync` against `SyncSupport.SERVER_AUTHORITATIVE` → `ok: true`,
   `data.synced == false`, `data.mode == "noop"`, `backend.sync` never called;
   `UNSUPPORTED` → `E_UNSUPPORTED_CAPABILITY`; `NATIVE` → real commit/push.
5. `REQUIRED_CAPABILITY` predicates accept `(Capabilities, Namespace)`; the
   `dep` predicate returns `True` when `a.dep_op == "list"`.
6. The full bd contract suite (`make ci-workcli`) is green and
   `PROTOCOL_VERSION == "1.0"` — no envelope/`data`-shape change.
7. `label_mutate(["a","b","c"])` where the 2nd `bd label` call fails →
   `WorkError` with `detail.partial_progress == {operation:"label_mutate",
   steps_total:3, completed:["a"], failed:"b", remaining:["c"]}`; re-invoking
   the same call against a fake that heals after one failure completes with no
   error (idempotency).
8. `sync` push-phase failure → `detail.partial_progress` with
   `completed:["commit"], failed:"push"`; re-invoking `sync` completes.
9. A `WorkError` from a single-call primitive (e.g. `set_status`) carries no
   `partial_progress` key; likewise a `label_mutate` that fails on label 1.
10. The bd adapter treats "label already present" / "label absent" stderr as
    idempotent success (asserted against a scripted runner).


## Continuations

- shape-stamping-sweep: one-shot `scripts/` sweep + exit-criterion check, run in the
  track-backfill supervised session — AC: 3, 4; stamps every legacy child-bearing
  container with its declared shape, idempotent, human-confirmed (bead agents-config-wgclw.9.6).
- router-declared-cutover: rewire `whats-next/collect.py` to declared markers, delete the
  active-child-count index and `CONTAINER_DESIGN`, rewrite the Filter Matrix — gated on the
  sweep exit criterion — AC: 5, 6.
- force-escape-doc: document `plan --done --force` as the unstamped-bead escape hatch in the
  work-facade contract spec — AC: 2.
- feat: workcli capability-disposition seam — reshape `Capabilities` to
  `ready`/`sync` disposition enums + `supports_dep_write`, widen the gate
  predicate, add the `sync` no-op branch — AC: criteria 1–6.
- feat: workcli multi-step partial-progress contract — `StepProgress` +
  `with_progress`, wire `label_mutate`/`sync`, adapter label-idempotency
  absorption — AC: criteria 7–10.
- feat: GH-Issues adapter honoring the disposition matrix
  (`sync=SERVER_AUTHORITATIVE`, `supports_dep_write=False`, `ready=EMULATED`)
  and the client-side `EMULATED` ready computation from `query` + dep edges — AC:
  paper-seam (transport §7) validated with contract tests against a GH fake.
- chore: MINOR protocol bump advertising `partial_progress` + capability
  surface in the `--protocol-version` handshake and README — the concrete version
  number is assigned at merge time by landing order (competing MINOR claims exist
  in the track-partition and work-discover specs), never at spec-authoring time —
  AC: `PROTOCOL_VERSION` bumped, handshake test + README updated.
- feat: `reconcile` consumes `partial_progress` detail to rank resumable
  failures — AC: a seam failure carrying `partial_progress` surfaces as a
  resumable reconcile finding.
