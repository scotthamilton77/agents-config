# workcli Lifecycle Layer Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the
> `test-driven-development` skill (red-green-refactor per task) and the
> `writing-unit-tests` skill before naming any test. One fresh subagent per
> task. Workers spawn NO subagents — every step runs inline. Add each import
> together with its first use in the same edit (the post-edit ruff hook strips
> unused imports). Never run mutating `bd` commands against the real DB. Never
> edit files outside `packages/workcli/`, the root `Makefile`/`AGENTS.md`, or the
> spec files a task explicitly names.

**Goal:** Ship the lifecycle layer of `packages/workcli` (bead
agents-config-wgclw.9.2): noun-templated `work create <noun>` plus the guarded
lifecycle verbs `claim`/`release`/`deliver`/`plan`/`promote`/`reconcile`, built
over the transport layer's `Backend` seam, so **status never moves except
through a lifecycle verb** — passing work-lifecycle spec test-plan items 1–11
under the `make ci-workcli` gate.

**Spec:** `docs/specs/2026-07-05-work-lifecycle-and-facade.md` (read §§4–7 for
shapes, evidence rule, placeholder reconciliation, and the verb table; §14 is
the test plan; §15 is the assumption ledger this plan finalizes). Built on the
transport contract `docs/specs/2026-07-04-work-facade-cli-contract.md` and its
implementation plan `docs/plans/2026-07-10-workcli-transport-layer.md` (the
"Pinned shared contracts" section is the authority on existing dataclass
shapes). This plan pins the lifecycle contracts; the spec is the authority on
behavior.

**Architecture:** A new pure lifecycle layer (`src/workcli/lifecycle/`) over the
existing injected `Backend` seam. Lifecycle verb handlers keep the transport
handler signature `(Backend, Namespace) -> JsonValue`; they compose thin
`Backend` primitives (four new: `claim`, `set_status`, `set_type`,
`set_acceptance`) into guarded, **idempotent, state-derived** transitions.
Noun→shape templating and `## Continuations` manifest parsing are pure modules
with no backend dependency. Evidence is verified only against what bd can
observe (items exist) or the local filesystem (the merged spec) — **no `gh`, no
network**; merge-state is caller-attested at merge time and recovery is
bd-observable. All contract tests run against the existing `ScriptedBdRunner`
fake plus an injected file-reader fake — no live Dolt, no real subprocesses, no
real filesystem reads.

**Tech Stack:** Unchanged from the transport layer — Python ≥3.11, stdlib only
at runtime, pytest/ruff/mypy(strict)/pip-audit dev gate, uv project. Coverage
floor 90 / branch=true (100% today; keep it).

---

## Locked contract decisions (pinned here so slices agree; deviations need orchestrator sign-off)

These extend — never contradict — the transport plan's locked decisions 1–15.
The two settled transport rulings are load-bearing here and **must not be
re-litigated**: (a) `work create --raw` is the transport creation primitive —
the lifecycle `create <noun>` is a *separate mode of the same `create` verb*,
never a replacement; (b) notes are append-only (`work note`); `--set-notes` is a
help-suppressed clobber tripwire.

**L1. Status is lifecycle-verb-only.** `close`/`reopen` (transport) plus
`claim`/`release`/`deliver`/`reconcile` (this layer) are the *only* paths that
move status. `claim` maps to bd's own `update --claim` (atomic assignee + status
+ session stamp; idempotent if already claimed by the actor — so staleness is at
least *detectable*, invariant 3; full self-healing/auto-release of a dead
session's claim is the owner-deferred follow-up). `release`/`reconcile` use the
internal `set_status` primitive. `work update` still never touches status.

**L2. Four new seam primitives.** `claim(id)` → `bd update <id> --claim`;
`set_status(id, status)` → `bd update <id> --status <status>`; `set_type(id,
type)` → `bd update <id> --type <type>`; `set_acceptance(id, text)` → `bd update
<id> --acceptance <text>`. `set_*` are idempotent (setting a field to its
current value is a bd no-op) and keep `retry_on_timeout=True`; `claim` is
bd-idempotent (idempotent if already claimed by the actor) and likewise
timeout-retryable.

**L3. `CreateFields` gains two optional fields** (`acceptance: str | None`,
`blocked_by: str | None`), both defaulting `None`. When present the bd adapter
appends `--acceptance <text>` / `--deps <id>` (bare id — bd's `blocks:<id>`
form is the reverse direction). Transport `create --raw`
never sets them, so its argv and existing tests are unchanged. `blocked_by`
makes the spec-shape placeholder's blocks-edge a single atomic `bd create`,
shrinking the partial-failure surface.

**L4. Retry-safety fix (38o1v #3 — a real latent bug).** `run_with_retry` gains
`retry_on_timeout: bool = True`. Non-idempotent bd mutations (`create`,
`append_note`) pass `retry_on_timeout=False`: a `TimeoutExpired` is NOT retried
(re-running a possibly-completed create/append duplicates it) — it surfaces the
new `E_TIMEOUT`. Lock-contention *stderr* retry is unchanged for all commands
(that stderr proves bd did not run). Every read verb and every idempotent
mutation (`claim`/`set_status`/`set_type`/`set_acceptance`/`set_fields`/`close`/
`reopen`/`dep_mutate`/`label_mutate`/`sync`) keeps `retry_on_timeout=True`.

**L5. `batch_get` edge cases pinned (38o1v #4).** Empty `ids` → `[]` with **zero
bd calls**. Duplicate requested id → the same `Item` at each position (already
the contract; add a test). bd returning extra records not requested → ignored
(the `by_id` lookup already drops them; add a test). Missing requested id →
`E_NOT_FOUND` (already).

**L6. Capability model (38o1v #1) — deferred, documented.** The finer capability
split (read-only dep listing surviving `supports_dep_types=False`; an honest
server-authoritative `sync` no-op) is a *transport-seam* refinement whose only
consumer is a future non-bd adapter. bd has every flag `True`, so the lifecycle
layer needs nothing here. Deferred to the GH-adapter bead; recorded in this plan
and in `packages/workcli/AGENTS.md`. No code in 9.2.

**L7. Idempotency is state-derived, not journalled.** Every lifecycle mutation
first reads current state and no-ops when already applied (already-closed
deliver → exit 0; already-`in_progress` claim → exit 0; placeholder already
reconciled → skip). bd-observable markers make partial progress recoverable —
each chosen so it is either directly **queryable** (a label) or lives on an
item reconcile already fetches:
- Label `impl-placeholder` — an unreconciled/expanding spec placeholder; removed
  **strictly last**, only once the placeholder is fully reconciled (L9/L10). It
  is the queryable handle reconcile enumerates on.
- Note line `[work] delivered: <evidence>` on the leaf — a leaf deliver in
  flight (written before `close`; presence makes the append idempotent and lets
  `reconcile` finish an interrupted close).
- Note line `[work] spec: <path>` **on the placeholder** — the merged-spec path
  recorded by a design `deliver`, so `reconcile` can re-parse the manifest from
  its `query(label=impl-placeholder)` result (bd `list` carries `notes`).
- Note line `[work] orphan-by-choice` on the item — placement recorded when
  `--orphan` is chosen (never orphan-by-accident).

**L8. Evidence model — bd-observable only (owner ruling 2026-07-12).** `deliver`
verifies `--items ID,ID` via `batch_get` (a `batch_get` `E_NOT_FOUND` is
**translated to `E_EVIDENCE`** by the verb — the items are the evidence, not a
lookup target); records `--pr <ref>` as the delivered-marker note **without**
contacting `gh` (caller-attested at merge time — the monitor-pr common case);
`--trivial` records a trivial acknowledgement. A design `deliver` reads the
merged spec from a local `--spec <path>` via an injected file-reader.
`reconcile` recovers only bd-observable states (L10). Dead-session
already-merged-PR auto-detection is a documented follow-up gated on bead↔PR
linkage — out of 9.2.

**L9. Noun → bd type + shape label (finalizes §15).** bd natively supports
`chore` and `decision` types (verified `bd create --help`), so those nouns map
straight through:

| Noun | bd `--type` | Shape label(s) at birth | Template |
|---|---|---|---|
| `spike` | `task` | `shape-spike` | terminal leaf, dispatchable at birth |
| `chore` | `chore` | `shape-chore` | terminal leaf, dispatchable at birth |
| `decision` | `decision` | `shape-decision` | terminal leaf, dispatchable at birth |
| `feat` | `feature` | `shape-feat` (+ `spec-ready` iff evidence) | impl leaf, evidence rule |
| `bugfix` | `bug` | `shape-bugfix` (+ `spec-ready` iff evidence) | impl leaf, evidence rule |
| `spec` | `feature` | `shape-spec` (+ `planned` **stamped last**, L16) | container + design child + placeholder |
| `epic` | `epic` | `shape-epic` | structural container, born unplanned |

The design child of a `spec` is `--type task` + label `shape-design`. The
placeholder is `--type task` + label `impl-placeholder`, blocked-by the design
child. `epic` carries `shape-epic` (a declared container-shape handle so `claim`
and the future router key on a label, never on child count — §5/invariant 5).

**L10. `reconcile` scope (bd-observable, idempotent).** reconcile's findings list
**is** the attention self-report (§8 Attention = human-labeled + reconcile
findings), so every state below is visible even before repair — satisfying
invariant 2. Candidate sets are enumerated only through queryable handles;
because `query()`/`list`-sourced Items always have `children == []` and no deps
(bd `list` has no `dependents` key — see `adapters/bd/parse.py`), reconcile
**`get()`s each candidate** before reading its children/deps. Three finding
classes:
- **Interrupted-deliver leaf** — an `in_progress` leaf carrying the
  `[work] delivered:` note but still open → `close` it (item 11's "claimed leaf
  with merged evidence → delivers retroactively", bd-observable form). Enumerate
  via `query(status="in_progress")` then `get()`; filter on the note marker.
- **Unreconciled placeholder** — enumerate via `query(label=impl-placeholder)`,
  `get()` each; if its design-child sibling is `closed` and a `[work] spec:`
  note is present → re-parse and reconcile (idempotent, reuses
  `reconcile_placeholder`); if the spec note is absent → report as an attention
  finding, no auto-repair.
- **Interrupted expansion** — the same `query(label=impl-placeholder)` set: a
  placeholder mid-multi-unit-expansion still carries `impl-placeholder` (removed
  last) with fewer children than its recorded manifest → mint only the missing
  children, then remove `impl-placeholder`. The objective legitimately stays
  `planned` (its plan is the template); the *placeholder* is the incomplete part
  and is found via its label.
`--dry-run` reports findings without mutating. Repairs are idempotent: a second
run over a healed tree finds nothing. (The §6 "lazy path" — a plain leaf whose
brainstorm reveals scope — reduces to `promote` in this design, which creates a
placeholder, so it recovers through the same handle. No separate lazy-decompose
mechanism in 9.2.)

**L11. New error codes (additive; protocol stays `1.0`).** `E_DUPLICATE_TITLE`,
`E_NOT_CLAIMABLE`, `E_EVIDENCE`, `E_MANIFEST`, `E_TIMEOUT`. Additive to the enum
only — envelope shape and every existing data shape are unchanged, so a `1.0`
consumer neither breaks nor needs them (it pins MAJOR); `PROTOCOL_VERSION` stays
`"1.0"`, exactly as `E_INTERNAL` was added within `1.0`. A MINOR bump to
advertise the expanded surface is a trivial documented follow-up, not this bead.

**L12. Injected file reads.** `main()` gains
`read_file: Callable[[str], str] | None = None` (default:
`lambda p: Path(p).read_text(encoding="utf-8")`). It is resolved once in
`main()` and attached to the parsed `Namespace` as `args.read_file` before
dispatch — matching the codebase's existing Any-typed `Namespace`-attribute
access, so handler signatures stay `(Backend, Namespace)`. Only `deliver` and
`reconcile` read it. No handler ever imports `pathlib` or touches the real
filesystem directly. Both `run_cli` and `run_cli_with_runner` (conftest) thread
an optional `read_file`.

**L13. Duplicate-title guard.** `create <noun>` calls `backend.search(title)`
and rejects an **exact, case-sensitive** title match among the results with
`E_DUPLICATE_TITLE` (detail names the colliding id) **before any `create` call
reaches bd**. No other create path fires it.

**L14. Placement is explicit.** `create <noun>` requires **exactly one** of
`--parent <id>` / `--orphan`; neither or both → `E_USAGE`. `--orphan` creates
with no parent and records a `[work] orphan-by-choice` note.

**L15. One PR, sliced into the tasks below.** `packages/**` floors the
completion gate to HEAVY (per repo policy); expect the quality-gate workflow at
delivery, then `verify-checklist` with fresh `make ci-workcli` evidence.

**L16. Mint-before-`planned` (invariant-2 fix).** A container is claimable-blind
but must never be queue-invisible. `planned` is what removes a container from the
Planning queue (§8), so it is stamped **strictly last**, only after the template's
children exist:
- `create spec`: container (`shape-spec`, **not** planned) → design child →
  placeholder → **then** `label add planned`.
- `promote`: `label add shape-spec` → `label remove shape-feat` →
  `instantiate_spec_shape` (design child + placeholder) → **then** `label add
  planned`.
Any interruption (process death or a bd error mid-template) therefore leaves a
`shape-spec` container that is **not** `planned` → it self-reports into the
Planning queue (container, not planned, unclaimed). Recovery is planning /
replanning (§5), not a blind `create` re-run (which the L13 duplicate-title
guard would reject — a *visible* stuck state, not a silent one). No new reconcile
class is needed for interrupted *creation*; the Planning queue is the safety net.

## CLI surface (argparse; exact flags — extend `cli.py` per task)

| Verb | Args/flags |
|---|---|
| `create [NOUN] [--raw] --title T ...` | `NOUN` optional positional, `choices=spike,chore,decision,feat,bugfix,spec,epic`; `--raw` (transport primitive, no NOUN); with NOUN: `(--parent ID \| --orphan)` required-exactly-one, `[--description D] [--priority P] [--acceptance AC] [--spec REF] [--trivial]`; `--type` rejected with a NOUN (noun sets type); `--spec`+`--trivial` together → `E_USAGE` |
| `claim ID` | — |
| `release ID` | — |
| `deliver ID` | `[--spec PATH] [--pr REF] [--items ID,ID] [--trivial]` |
| `plan ID` | `--done` \| `--undo` (exactly one); `--done` takes `[--force]` |
| `promote ID` | — |
| `reconcile` | `[--dry-run]` |

Dispatch precedence inside `create`: `--raw` → transport `create_raw`; else NOUN
present → lifecycle `create_noun`; else → `E_USAGE` (message names both `--raw`
and the noun set).

## File structure

```
packages/workcli/
├── src/workcli/
│   ├── envelope.py                 # +5 ErrorCode members (Task 1)
│   ├── model.py                    # CreateFields += acceptance, blocked_by (Task 1)
│   ├── backend.py                  # Backend += claim/set_status/set_type/set_acceptance (Task 1)
│   ├── cli.py                      # extend create; +6 subparsers; read_file inject (Tasks 3-6)
│   ├── adapters/bd/
│   │   ├── retry.py                # run_with_retry += retry_on_timeout (Task 1)
│   │   └── backend.py              # impl 4 primitives; create --acceptance/--deps (Task 1)
│   ├── verbs/__init__.py           # register lifecycle verbs in VERBS (Tasks 3-6)
│   └── lifecycle/                  # NEW subpackage — the lifecycle layer
│       ├── __init__.py             # marker constants + has_marker + is_container
│       ├── nouns.py                # noun taxonomy table + shape labels (Task 2)
│       ├── manifest.py             # ## Continuations parser (Task 2)
│       ├── create.py               # create_noun + instantiate_spec_shape (Task 3)
│       ├── transitions.py          # claim, release, plan, promote (Task 4)
│       ├── deliver.py              # deliver + reconcile_placeholder helper (Task 5)
│       └── reconcile.py            # reconcile sweep (Task 6)
└── tests/unit/
    ├── test_seam_lifecycle.py      # claim/set_status/type/acceptance + create acceptance/deps (Task 1)
    ├── test_retry_safety.py        # retry_on_timeout matrix (Task 1)
    ├── test_batch_get_edges.py     # empty/duplicate/extra records (Task 1)
    ├── test_nouns.py               # noun→type/label table + is_container (Task 2)
    ├── test_manifest.py            # manifest grammar incl. wrapped bullets + drift (Task 2)
    ├── test_create_noun.py         # items 1,2,3 (Task 3)
    ├── test_transitions.py         # items 8,9,10 (Task 4)
    ├── test_deliver.py             # items 4,5,6 (Task 5)
    ├── test_reconcile.py           # items 7,11 (Task 6)
    └── test_envelope_invariants.py # extend matrix to lifecycle verbs (Task 7)
```

## Pinned shared contracts (copy exactly; do not restyle)

### envelope.py — added ErrorCode members

```python
    # ... existing members unchanged ...
    DUPLICATE_TITLE = "E_DUPLICATE_TITLE"
    NOT_CLAIMABLE = "E_NOT_CLAIMABLE"
    EVIDENCE = "E_EVIDENCE"
    MANIFEST = "E_MANIFEST"
    TIMEOUT = "E_TIMEOUT"
```

### model.py — CreateFields extension (only these two lines added)

```python
@dataclass(frozen=True)
class CreateFields:
    title: str
    description: str | None = None
    type: str | None = None
    priority: str | None = None
    parent: str | None = None
    labels: tuple[str, ...] = ()
    acceptance: str | None = None      # NEW — bd `--acceptance`
    blocked_by: str | None = None      # NEW — bd `--deps <id>` (bare; atomic blocks-edge at creation)
```

### backend.py — four new Protocol methods

```python
    def claim(self, item_id: str) -> None: ...  # bd `update --claim`  # pragma: no cover
    def set_status(self, item_id: str, status: str) -> None: ...  # pragma: no cover
    def set_type(self, item_id: str, item_type: str) -> None: ...  # pragma: no cover
    def set_acceptance(self, item_id: str, text: str) -> None: ...  # pragma: no cover
```

### adapters/bd/retry.py — new signature

```python
def run_with_retry(
    runner: BdRunner,
    args: Sequence[str],
    *,
    sleep: Callable[[float], None],
    retry_on_timeout: bool = True,
) -> BdResult:
    ...
```

Behavior: on `TimeoutExpired`, retry only when `retry_on_timeout` is `True`;
when `False`, raise `WorkError(E_TIMEOUT, "bd timed out; the operation may have
partially applied — run `work reconcile`", detail={"argv": [...]})` immediately.
Lock-contention stderr retry is unchanged and independent of this flag.

### lifecycle/__init__.py — markers + container test

```python
from __future__ import annotations

from workcli.model import Item

DELIVERED_MARKER = "[work] delivered:"     # leaf note prefix; full: "[work] delivered: <evidence>"
SPEC_MARKER = "[work] spec:"               # placeholder note prefix; full: "[work] spec: <path>"
ORPHAN_MARKER = "[work] orphan-by-choice"  # item note (exact)

_CONTAINER_SHAPE_LABELS = frozenset({"shape-spec", "shape-epic"})
_CONTAINER_TYPES = frozenset({"epic", "milestone"})  # legacy/unstamped fallback


def has_marker(notes: str, prefix: str) -> bool:
    return any(line.strip().startswith(prefix) for line in notes.splitlines())


def is_container(item: Item) -> bool:
    """Declared-state container test — never child-count (spec §5/invariant 5)."""
    if _CONTAINER_SHAPE_LABELS & set(item.labels):
        return True
    return item.type in _CONTAINER_TYPES
```

### lifecycle/nouns.py — taxonomy

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Noun(StrEnum):
    SPIKE = "spike"
    CHORE = "chore"
    DECISION = "decision"
    FEAT = "feat"
    BUGFIX = "bugfix"
    SPEC = "spec"
    EPIC = "epic"


@dataclass(frozen=True)
class NounTemplate:
    bd_type: str                 # bd --type value
    shape_label: str             # birth shape label, e.g. "shape-feat"
    is_container: bool           # True for spec/epic
    expects_evidence: bool       # True for feat/bugfix (evidence rule applies)
    born_planned: bool           # True for spec — but `planned` is stamped LAST (L16)


NOUN_TEMPLATES: dict[Noun, NounTemplate] = {
    Noun.SPIKE:    NounTemplate("task",     "shape-spike",    False, False, False),
    Noun.CHORE:    NounTemplate("chore",    "shape-chore",    False, False, False),
    Noun.DECISION: NounTemplate("decision", "shape-decision", False, False, False),
    Noun.FEAT:     NounTemplate("feature",  "shape-feat",     False, True,  False),
    Noun.BUGFIX:   NounTemplate("bug",      "shape-bugfix",   False, True,  False),
    Noun.SPEC:     NounTemplate("feature",  "shape-spec",     True,  False, True),
    Noun.EPIC:     NounTemplate("epic",     "shape-epic",     True,  False, False),
}

DESIGN_CHILD_LABEL = "shape-design"
IMPL_PLACEHOLDER_LABEL = "impl-placeholder"
PLANNED_LABEL = "planned"
SPEC_READY_LABEL = "spec-ready"
```

### lifecycle/manifest.py — grammar (finalizes §15's manifest assumption)

```python
@dataclass(frozen=True)
class ManifestItem:
    noun: str          # a bare Noun value — placement is NOT a manifest field (all items
    title: str         # mint under the objective/placeholder; §12's cross-parent design-doc
    acceptance: str    # annotations like "(under X)" are not part of the facade grammar)


@dataclass(frozen=True)
class Manifest:
    items: tuple[ManifestItem, ...]   # empty iff the manifest is the literal `- none`
    none_reason: str | None           # non-None iff `- none`; None otherwise


def parse_continuations(spec_text: str) -> Manifest: ...
```

Grammar (raise `WorkError(E_MANIFEST, ...)` on any violation):
- Locate the section whose header line is exactly `## Continuations`
  (case-sensitive). Absent → `E_MANIFEST` ("spec has no ## Continuations
  manifest"). The section body is the lines after it up to the next line
  starting `## ` or EOF.
- **Bullets may wrap across physical lines.** Accumulate an item's text starting
  at a `- ` line and appending any following lines that are neither a new `- `
  bullet, a blank line, nor a `## ` header (joined with a single space, stripped).
  Blank lines and non-bullet prose between bullets are ignored.
- A single item `- none` (optionally `- none — <reason>`) →
  `Manifest(items=(), none_reason=<reason or "">)`. A `none` bullet coexisting
  with real item bullets → `E_MANIFEST` (ambiguous).
- Each real item: `- <noun>: <title> — AC: <acceptance>`. Split the accumulated
  text on the first `: ` (→ `<noun>` / rest) then on the first ` — AC: ` (→
  `<title>` / `<acceptance>`). `<noun>` must be **exactly** a `Noun` value after
  stripping (a token like `feat (under \`x\`)` is invalid → `E_MANIFEST`, with a
  message pointing at the bare-noun requirement); `<title>` and `<acceptance>`
  are non-empty stripped strings (else `E_MANIFEST`).
- Zero item bullets and no `none` bullet → `E_MANIFEST` ("empty manifest").

> Facade-authored specs use bare-noun bullets; converting the pre-facade loose
> Continuations forms in PRs #220–#227 is the specfest-repair continuation
> bead's job, not 9.2's.

### lifecycle verb handler signature (unchanged from transport)

```python
def <verb>(backend: Backend, args: Namespace) -> JsonValue: ...
```

Registered in `verbs/__init__.py`'s `VERBS` dict alongside the transport verbs.
`deliver`/`reconcile` read `args.read_file` (injected in `main()`, L12).

### Shared cross-task helpers (name + signature pinned; workers must export these)

```python
# lifecycle/create.py — used by create_noun (Task 3) AND promote (Task 4)
def instantiate_spec_shape(backend: Backend, container_id: str, title: str) -> tuple[str, str]:
    """Create the design child + blocked placeholder under an existing container.

    Returns (design_child_id, placeholder_id). Does NOT stamp `planned` — the
    caller stamps it LAST (L16). Records the `impl-placeholder` label on the
    placeholder; the design child gets `shape-design`.
    """

# lifecycle/deliver.py — used by deliver (Task 5) AND reconcile (Task 6)
def reconcile_placeholder(backend: Backend, placeholder_id: str, manifest: Manifest) -> None:
    """Idempotently reconcile one placeholder against a parsed manifest (§6):
    none → close + reason note; single → set_type + retitle + set_acceptance +
    label swap (+ spec-ready); multi → mint the MISSING children (compare to
    existing), removing `impl-placeholder` STRICTLY LAST once all exist.
    Short-circuits on already-reconciled state (no `impl-placeholder` label).
    """
```

---

## Tasks

Worker protocol for every task: (1) announce the task; (2) invoke
`test-driven-development` and `writing-unit-tests`; (3) red-green-refactor per
step; (4) run `make ci-workcli` from the repo root; (5) commit with the given
message; (6) report back: files changed, pasted gate tail, decisions, open
questions. Spawn no subagents. Never run mutating `bd`. Call-log assertions use
`run_cli_with_runner` (conftest.py:39 — `run_cli` discards its runner and
exposes no `.calls`).

### Task 1: Foundation — error codes, seam primitives, retry-safety, batch_get pins

**Files:**
- Modify: `src/workcli/envelope.py` (L11 codes), `src/workcli/model.py` (L3),
  `src/workcli/backend.py` (L2 Protocol methods),
  `src/workcli/adapters/bd/retry.py` (L4), `src/workcli/adapters/bd/backend.py`
  (impl 4 primitives; `create` appends `--acceptance`/`--deps`; pass
  `retry_on_timeout=False` in `create`/`append_note`; empty-ids guard in
  `batch_get`)
- Create: `tests/unit/test_seam_lifecycle.py`, `tests/unit/test_retry_safety.py`,
  `tests/unit/test_batch_get_edges.py`

- [ ] **Failing tests first.**
  - `test_seam_lifecycle.py`: a `BdBackend` over a `ScriptedBdRunner` —
    `claim("x")` sends `("update","x","--claim")`; `set_status("x","open")` sends
    `("update","x","--status","open")`; `set_type("x","bug")` sends
    `("update","x","--type","bug")`; `set_acceptance("x","AC")` sends
    `("update","x","--acceptance","AC")`; each raises the mapped `WorkError` on a
    scripted failure. `create(CreateFields(title="T", acceptance="A",
    blocked_by="d1"))` argv contains `--acceptance A` and `--deps d1`;
    `create(CreateFields(title="T"))` argv contains neither (transport unchanged).
  - `test_retry_safety.py`: with a runner that raises `TimeoutExpired` once then
    would succeed — `run_with_retry(..., retry_on_timeout=True)` retries and
    succeeds (1 sleep); `run_with_retry(..., retry_on_timeout=False)` raises
    `E_TIMEOUT`, **zero** retries (call log length 1). Lock-contention stderr
    still retries under `retry_on_timeout=False`. End-to-end: `create`/`note`
    verbs surface `E_TIMEOUT` (not duplicate calls) when the fake times out;
    `close`/`update`/`label` still retry a timeout.
  - `test_batch_get_edges.py`: `batch_get([])` → `[]` and `runner.calls == []`;
    `batch_get(["a","a"])` with one scripted record for `a` → two positions, same
    `Item`; a scripted `show` returning an extra unrequested record → ignored,
    only requested ids returned.
- [ ] **Implement.** Add the 5 codes; extend `CreateFields`; add the 4 Protocol
  methods + `BdBackend` impls (each one `bd update` call via `run_with_retry`,
  mapped failure via `map_bd_failure`); extend `retry.py` per L4; make
  `create`/`append_note` pass `retry_on_timeout=False`; guard `batch_get` empty
  ids with an early `return []` before building argv.
- [ ] `make ci-workcli` green. Commit:
  `feat(workcli): lifecycle seam primitives, retry-safety fix, batch_get pins (9.2)`

### Task 2: Nouns taxonomy + manifest parser (pure)

**Files:**
- Create: `src/workcli/lifecycle/__init__.py` (markers + `has_marker` +
  `is_container`), `src/workcli/lifecycle/nouns.py`,
  `src/workcli/lifecycle/manifest.py`, `tests/unit/test_nouns.py`,
  `tests/unit/test_manifest.py`

- [ ] **Failing tests first.**
  - `test_nouns.py`: `NOUN_TEMPLATES` has all 7 nouns mapping to the L9 table.
    `has_marker("a\n[work] delivered: pr#1\nb", DELIVERED_MARKER)` is `True`;
    absent → `False`. `is_container` is `True` for an `Item` with a `shape-spec`
    or `shape-epic` label, or `type in {epic, milestone}`; **`False` for a
    childless `epic`-labeled... no**: `True` for `type=="epic"`; and critically
    `is_container` of a `feature` item with children but no container label/type
    is `False` (never child-count).
  - `test_manifest.py`: a three-item `## Continuations` → three `ManifestItem`s;
    a bullet that **wraps across two physical lines** parses into one item
    (title/AC joined); `- none — this spec is the deliverable` →
    `Manifest(items=(), none_reason="this spec is the deliverable")`; missing
    section → `E_MANIFEST`; a `feat (under \`x\`):` non-bare noun → `E_MANIFEST`;
    unknown noun → `E_MANIFEST`; `none` mixed with real items → `E_MANIFEST`;
    empty section → `E_MANIFEST`; an item missing ` — AC: ` → `E_MANIFEST`; a
    second `## ` header ends the section.
- [ ] **Implement** `nouns.py`, `manifest.py`, `__init__.py` per the pinned
  contracts. Pure — no `Backend`, no I/O.
- [ ] `make ci-workcli` green. Commit:
  `feat(workcli): noun taxonomy and wrap-tolerant ## Continuations parser (9.2)`

### Task 3: `work create <noun>` — noun-templated creation

**Files:**
- Create: `src/workcli/lifecycle/create.py`, `tests/unit/test_create_noun.py`
- Modify: `src/workcli/cli.py` (extend the `create` subparser: optional `noun`
  positional with `choices`, add `--orphan`/`--spec`/`--trivial`/`--acceptance`),
  `src/workcli/verbs/__init__.py` (route `create` to a dispatcher that picks
  `create_raw` vs `create_noun`)

- [ ] **Failing tests first (call-log tests via `run_cli_with_runner`).**
  - **Item 1** — `create spec --title T --parent P`: the fake call log shows, in
    order, a container `create` (`--type feature`, label `shape-spec`, **no
    `planned` on this create**), a design-child `create` (`--parent
    <container>`, label `shape-design`), a placeholder `create` (`--parent
    <container>`, `--deps <designchild>` (bare id), label `impl-placeholder`, title
    `[Impl] T (scope: per spec)`), and **finally** a `label add <container>
    planned` (L16 — planned is stamped last, after both children exist).
    Envelope `data` returns the container id + child ids.
  - **Item 2** — `create feat --spec S --parent P`: labels include `shape-feat`
    **and** `spec-ready`. `create feat --parent P` (no evidence): `shape-feat`,
    **no** `spec-ready`. `create feat --trivial --parent P`: `spec-ready`
    present. `--spec` + `--trivial` → `E_USAGE`.
  - **Item 3** — every noun requires exactly one of `--parent`/`--orphan`:
    neither → `E_USAGE`, both → `E_USAGE`. `--orphan` → `create` with no
    `--parent` and a `note` carrying `[work] orphan-by-choice`. Exact duplicate
    title (scripted `search` returns a same-title item) → `E_DUPLICATE_TITLE`
    naming the collision, and **no** `create` reaches the fake. `create feat
    --type bug` → `E_USAGE`. `create --title T` (no noun, no `--raw`) →
    `E_USAGE`. `create --raw --title T` still works (transport unchanged).
- [ ] **Implement** `create.py`: dispatch on noun; duplicate guard via `search`
  (L13); placement validation (L14); per-shape instantiation using
  `NOUN_TEMPLATES` + the Task-1 seam. Terminal-leaf nouns → one `create` + shape
  label. `feat`/`bugfix` → one `create` + shape label (+`spec-ready` when
  `--spec`/`--trivial`). `spec` → container (shape-spec, not planned) →
  `instantiate_spec_shape` → `label add planned` last (L16). `epic` → one
  `create` (`--type epic`, `shape-epic`). Export `instantiate_spec_shape`. Wire
  cli + registry dispatcher.
- [ ] `make ci-workcli` green. Commit:
  `feat(workcli): noun-templated work create with evidence rule and placement (9.2)`

### Task 4: `claim` / `release` / `plan` / `promote`

**Files:**
- Create: `src/workcli/lifecycle/transitions.py`, `tests/unit/test_transitions.py`
- Modify: `src/workcli/cli.py` (4 subparsers), `src/workcli/verbs/__init__.py`
  (register)

- [ ] **Failing tests first (call-log via `run_cli_with_runner`).**
  - **Item 8** — `claim ID` on an open, unblocked leaf (scripted `show` open + no
    container label + `ready` includes ID) → `claim ID` (bd `--claim`), envelope
    `data.status == "in_progress"`. `claim` on a container **detected by label**:
    a **childless `epic`** (`show` returns `shape-epic`, no children) → still
    `E_NOT_CLAIMABLE`, no `claim` call (proves the guard is label-based, not
    child-count). `claim` on a leaf absent from the scripted `ready` set →
    `E_NOT_CLAIMABLE` ("blocked"), no `claim`. `claim` on already `in_progress` →
    no-op exit 0, no `claim`. `claim` on `closed` → `E_NOT_CLAIMABLE`. `release
    ID` on `in_progress` → `set_status ID open`; already `open` → no-op exit 0;
    `closed` → `E_USAGE`.
  - **Item 9** — `plan ID --done` on a container with children → `label add ID
    planned`; on a childless item without `--force` → `E_USAGE`; with `--force`
    → stamps `planned`. Already `planned` → no-op exit 0. `plan ID --undo` →
    `label remove ID planned`. Neither/both of `--done`/`--undo` → `E_USAGE`.
  - **Item 10** — `promote ID` on a `shape-feat` leaf → in order: `label add ID
    shape-spec`, `label remove ID shape-feat`, a design child `create --parent
    ID`, a placeholder `create --parent ID --deps <designchild>` (bare id),
    **finally** `label add ID planned` (L16); the fake shows **no**
    reparent/new-parent call on ID (id + parent + edges preserved). `promote` on
    a non-`shape-feat` item → `E_USAGE`; already `shape-spec` → no-op exit 0.
- [ ] **Implement** `transitions.py`: `claim` (get → status guard →
  `is_container` guard → ready-set membership guard → `backend.claim`), `release`
  (get → `set_status` open), `plan` (`--done`/`--undo`, child/`--force` guard,
  label add/remove, idempotent), `promote` (add shape-spec, remove shape-feat,
  `instantiate_spec_shape`, add planned last — L16). Wire cli + registry.
- [ ] `make ci-workcli` green. Commit:
  `feat(workcli): claim/release/plan/promote guarded transitions (9.2)`

### Task 5: `deliver` + placeholder reconciliation

**Files:**
- Create: `src/workcli/lifecycle/deliver.py`, `tests/unit/test_deliver.py`
- Modify: `src/workcli/cli.py` (`deliver` subparser + resolve/attach
  `args.read_file` in `main()` per L12), `src/workcli/verbs/__init__.py`,
  `tests/conftest.py` (thread an optional `read_file` into BOTH `run_cli` and
  `run_cli_with_runner`; default a dict-backed fake reader)

- [ ] **Failing tests first (`run_cli_with_runner` with injected `read_file`).**
  - **Item 4** — `deliver DESIGN --spec path`, `read_file(path)` returns a
    manifest; DESIGN carries `shape-design`, its parent's children include the
    placeholder:
    - single-unit → placeholder `set_type` to the noun's bd type, retitle
      (`set_fields`/update title), `set_acceptance`, label swap (`remove
      impl-placeholder`, `add <noun shape>` + `spec-ready`), then design child
      `close`. `impl-placeholder` removed after the field mutations.
    - multi-unit (N=3) → three `create --parent <placeholder>` (typed, AC, shape
      label), then `remove impl-placeholder` from the placeholder **last**,
      design child `close`.
    - `- none` → placeholder `close` + a `note` with the none-reason, design
      child `close`.
    The `[work] spec: <path>` note is recorded on the **placeholder** before the
    reconciliation mutations.
  - **Item 5** — replay: a second identical `deliver DESIGN --spec path` when the
    design child is already `closed` and the placeholder already reconciled (no
    `impl-placeholder`) → no-op, exit 0, no mutations.
  - **Item 6** — `deliver LEAF` (shape-feat): `--items x,y` where scripted `show
    x y` reports a missing id → the `batch_get` `E_NOT_FOUND` is translated to
    `E_EVIDENCE`; no `close`, no delivered-note. No `--pr`/`--items`/`--trivial`
    → `E_EVIDENCE`. `deliver LEAF --pr URL` → append `[work] delivered: URL` then
    `close LEAF`; replay (already closed) → no-op exit 0; interrupted replay
    (open, delivered-note present) → no duplicate note, just `close`.
- [ ] **Implement** `deliver.py`: dispatch on the `shape-design` label. Design
  path → find sibling placeholder via parent's children, parse manifest
  (`args.read_file`), record `[work] spec:` on the placeholder, call
  `reconcile_placeholder`, close the design child. Leaf path → verify evidence
  (L8, translate `E_NOT_FOUND`→`E_EVIDENCE`), append delivered-note if absent
  (`has_marker`), close. Export `reconcile_placeholder`. Add `read_file`
  injection to `main()` and both conftest helpers.
- [ ] `make ci-workcli` green. Commit:
  `feat(workcli): deliver with evidence rule and placeholder reconciliation (9.2)`

### Task 6: `reconcile` sweep

**Files:**
- Create: `src/workcli/lifecycle/reconcile.py`, `tests/unit/test_reconcile.py`
- Modify: `src/workcli/cli.py` (`reconcile` subparser), `src/workcli/verbs/__init__.py`

- [ ] **Failing tests first (`run_cli_with_runner` with injected `read_file`).**
  - **Item 7** — interrupted expansion: `query(label=impl-placeholder)` returns a
    placeholder that still carries `impl-placeholder`, `get()` shows 1 of 3
    manifest children and a `[work] spec:` note → `reconcile` mints only the 2
    missing children then removes `impl-placeholder`; a second `reconcile` over
    the healed tree mutates nothing.
  - **Item 11** — three detections, each idempotent:
    - `query(status=in_progress)` → `get()` a leaf carrying `[work] delivered:`
      still open → `close`; re-run no-ops.
    - `query(label=impl-placeholder)` → `get()`; design-child sibling `closed` +
      `[work] spec:` note present → `reconcile_placeholder`; spec note absent →
      reported as a finding, **no** mutation.
    - `--dry-run` → findings in `data`, **zero** mutating bd calls.
- [ ] **Implement** `reconcile.py`: enumerate the bd-observable candidate sets
  (L10) via `query` then `get()` each candidate (query results carry no
  children/deps), reusing `reconcile_placeholder`; honor `--dry-run`; return a
  findings list in `data`. Wire cli + registry.
- [ ] `make ci-workcli` green. Commit:
  `feat(workcli): reconcile recovery sweep for bd-observable states (9.2)`

### Task 7: Contract matrix, docs, spec status

**Files:**
- Modify: `tests/unit/test_envelope_invariants.py` (add the 7 lifecycle verbs ×
  {success, failure} — every invocation one parseable envelope carrying
  `protocol`, exit mirrors `ok`), `packages/workcli/README.md` (lifecycle verb
  table + the new error codes + the L6/L11 deferral notes),
  `packages/workcli/AGENTS.md` (note the lifecycle layer + L6 capability
  deferral), `docs/specs/2026-07-05-work-lifecycle-and-facade.md` (Status:
  Draft → Implemented for the lifecycle layer; do not touch the design body)

- [ ] **Failing matrix test** covering `create <noun>`/`claim`/`release`/
  `deliver`/`plan`/`promote`/`reconcile` success+failure envelopes.
- [ ] Update README/AGENTS/spec status. No `whats-next` router work — that is a
  separate Continuation bead (test item 12), explicitly out of 9.2.
- [ ] From the repo root: `make ci-workcli` then `make ci` (all packages +
  lint-actions) → green; paste evidence. Commit:
  `docs(workcli): lifecycle verb contract matrix, README, spec status (9.2)`

---

## Delivery (orchestrator-owned; not worker tasks)

1. Completion gate per the completion-gate rule: `gate-triage` → expected HEAVY
   (`packages/**`) → `Workflow({name: "quality-gate", args: <triage JSON>})` →
   address findings → `verify-checklist` with fresh `make ci-workcli` evidence.
2. `finishing-a-development-branch` → PR (**explicit** merge policy — no merge
   without owner instruction) → `wait-for-pr-comments` monitoring until
   quiescent.
3. `bd dolt push` + `git push` before any pause. Bead 9.2 notes updated with
   state; close 38o1v's #3/#4 as addressed and record the #1/#6 + merged-PR
   detection deferrals.

## Self-review (done at authoring)

- **Spec coverage:** §4 shapes/nouns → Task 2 + Task 3; §4 evidence rule → Task 3
  (item 2); §5 containers/`planned` → Task 4 (item 9) + L16; §6 placeholder +
  manifest reconciliation → Task 2 (parser) + Task 5 (items 4–6); §7 verb table
  → Tasks 3–6; §7 out-of-band/idempotency → L7/L10 + Tasks 5–6; test-plan items
  1–11 mapped 1:1 (item 12, the router, is a separate bead — out of scope, noted
  in Task 7). 38o1v #2 → L7/L10 (Tasks 5–6); #3 → L4 (Task 1); #4 → L5 (Task 1);
  #1 → L6 (deferred, documented).
- **Type consistency:** all cross-task shapes (`CreateFields`, the 4 seam
  methods, `Noun`/`NounTemplate`/`NOUN_TEMPLATES`, `Manifest`/`ManifestItem`,
  the marker/`is_container` helpers, `instantiate_spec_shape`,
  `reconcile_placeholder`, the 5 error codes) live in "Pinned shared contracts"
  — workers copy, never re-derive. Handler signature is the transport's
  `(Backend, Namespace) -> JsonValue` throughout.
- **No placeholders:** every task carries concrete failing-test assertions tied
  to a numbered test-plan item and a named implementation shape.
- **Ordering:** Task 1 (seam) → Task 2 (pure) unblock the verb tasks; Task 3
  exports `instantiate_spec_shape` (reused by Task 4); Task 5 exports
  `reconcile_placeholder` (reused by Task 6); Task 7 closes the matrix + docs.

## Review outcome (deep-review gate — provenance, not in-body narration)

Deep-review route (plan diverges from spec via the owner-approved bd-observable
evidence model; cross-task helper coupling). One independent adversarial reviewer
(opus) — recorded verdict **FAIL**, all findings fixed inline before execution:

- BLOCKING — born-`planned` childless container was reconcile-blind and
  queue-invisible → **L16** mint-before-`planned` (create spec + promote stamp
  `planned` last; interrupted creation self-reports into the Planning queue).
- MAJOR — `claim` container guard inferred containerhood from child count →
  now label/type based via `is_container` (§5/invariant 5).
- MAJOR — reconcile could not enumerate interrupted expansions → `impl-placeholder`
  removed **strictly last**; reconcile enumerates via `query(label=impl-placeholder)`.
- MAJOR — manifest grammar rejected wrapped / annotated bullets → wrap-tolerant
  accumulation + bare-noun requirement documented; placement is not a manifest field.
- MAJOR — interrupted expansion visibility → reconcile findings are the attention
  self-report; objective staying `planned` is correct.
- MINORs — `run_cli_with_runner` for call-log tests; named/pinned shared helpers;
  `[work] spec:` recorded on the placeholder; reconcile `get()`s candidates
  (query children always `[]`); `claim` uses bd `--claim` (invariant 3 detection);
  `--items` `E_NOT_FOUND`→`E_EVIDENCE` translation pinned.

Ground-truth accuracy and all four 38o1v dispositions were confirmed by the
reviewer against the shipped code and the real bd binary.
