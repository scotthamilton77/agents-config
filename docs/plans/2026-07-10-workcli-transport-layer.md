# workcli Transport Layer Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task) and the `writing-unit-tests` skill before naming any test. One fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking. Workers spawn NO subagents — every step runs inline.

**Goal:** Ship `packages/workcli` — the `work` CLI transport layer (bead agents-config-wgclw.9.1): twelve contract verbs over a `Backend` seam with a JSON envelope, typed error codes, and a bd adapter behind a subprocess port, passing contract-spec test-plan items 1–10 under a `make ci-workcli` gate.

**Spec:** `docs/specs/2026-07-04-work-facade-cli-contract.md` (read it — §3 verbs, §4 envelope, §5 protocol, §6 seam, §11 test plan). This plan pins the shared contracts; the spec is the authority on behavior.

**Architecture:** Pure verb layer (normalization, typed errors, pre-checks) over an injected `Backend` protocol; the bd adapter owns backend I/O only and drives the real binary through a `BdRunner` subprocess port. All contract tests run against a `ScriptedBdRunner` fake — no live Dolt, no real subprocesses.

**Tech Stack:** Python ≥3.11, stdlib only at runtime (argparse/json/subprocess/dataclasses — zero runtime deps keeps the pip-audit surface nil; typer's decorator magic fights `mypy --strict disallow_any_decorated`, and consumers are programs, not humans). Dev: pytest, pytest-cov, pytest-xdist, ruff, mypy, pip-audit. uv project, hatchling build, mirroring `packages/installer` and `packages/prgroom` verbatim.

---

## Locked contract decisions (pinned here so slices agree; deviations need orchestrator sign-off)

1. **Exit codes:** 0 when `ok: true`, 1 when `ok: false`. Nothing else, ever.
2. **stdout invariant:** exactly one JSON envelope on stdout per invocation, including argparse
   errors (`E_USAGE`) and unexpected internal exceptions. Exception: `--help`/`-h` prints
   argparse help (human-facing, not a verb; consumers never call it).
3. **`E_INTERNAL` added to the error-code set** (contract-additive): unexpected internal
   exception → envelope `{code: "E_INTERNAL"}`, traceback to stderr, exit 1. The §4 invariant
   ("envelope on stdout, always") is unsatisfiable on facade bugs without it. Task 6 amends the
   spec's §4 list; flagged in the PR description for owner review.
4. **Unknown bd failure → `E_BACKEND_DRIFT`:** a nonzero bd exit whose stderr matches no known
   mapping is the same alarm class as an unparseable shape — the facade's model of bd broke.
   `detail` carries argv, exit code, stderr excerpt.
5. **Test-plan item 4 interpretation:** "bd never invoked" means the *mutating* `dep add` call
   never reaches bd. The pre-check fetches both items' types via `Backend.get` (the fake serves
   those reads); the assertion is zero `dep`-mutation invocations in the fake's call log.
6. **`E_FIELD_CLOBBER_GUARD` v1 trigger:** `work update --set-notes`/`--notes` → this code
   (notes are append-only via `work note`; a named clobber rejection beats a generic `E_USAGE`).
   No other v1 path fires it.
7. **`create` without `--raw` → `E_USAGE`** with message pointing at the lifecycle layer
   (public noun-templated creation is bead .9.2).
8. **Retry policy:** retryable = lock-contention stderr patterns
   (`database is locked`, `lock contention`, `resource temporarily unavailable`,
   `connection refused`) or subprocess `TimeoutExpired`; 3 attempts total, injectable
   `sleep(0.5)`, `sleep(1.0)` between them; exhaustion → `E_LOCK_CONTENTION`.
9. **`sync` semantics (bd):** default = `bd dolt commit` then `bd dolt push` (commit stderr
   containing `nothing to commit` is success — idempotent sync). `--pull` = `bd dolt pull`;
   stderr containing `cannot merge with uncommitted changes` → `E_SYNC_BEHIND`.
   Data: `{"synced": true, "mode": "push"|"pull"}`.
10. **`show` data shape:** one id → `data` IS the item object; 2+ ids → `data = {"items": [...]}`.
11. **Capability gate:** verb layer checks the adapter's `Capabilities` before dispatch;
    unsupported → `E_UNSUPPORTED_CAPABILITY`. bd's flags are all true, so the path is tested
    with a stub backend, not the bd adapter.
12. **v1 skips client-side `ready` emulation** (spec §6 requires it only for backends without
    blocker semantics; bd has them; JIRA/GH are out of scope).
13. **Injectability:** `main()` accepts `argv`, `runner`, `out`, `err`, `sleep` (signature in
    Task 1). Outside-world dependencies always arrive as arguments — never module globals.
14. **bd sample capture (goldens):** read-only `bd … --json` captures for parser fixtures run
    from the MAIN repo root (`/Users/scott/src/projects/agents-config`), never from the
    worktree (DB-in-main-tree rule), and only read verbs (`show`, `list`, `dep list`,
    `label list`). Mutating bd verbs are NEVER run against the real DB in this project.
15. **Coverage floor 90 / branch=true** (sibling standard supersedes the global 80/70 default).

## CLI surface (argparse; exact flags — cli.py is written once in Task 1 and extended per task)

| Verb | Args/flags |
|---|---|
| `show IDS...` | — |
| `create --raw --title T [--description D] [--type task] [--priority P2] [--parent ID] [--label L ...]` | `--label` repeatable |
| `update ID [--set-title T] [--set-priority P] [--set-description D]` | ≥1 required; `--set-notes`→`E_FIELD_CLOBBER_GUARD` |
| `note ID TEXT` | append-only |
| `close IDS... [--disposition TEXT]` | disposition = appended note per id |
| `reopen ID` | — |
| `list [--status S] [--label L] [--parent ID] [--type T] [--limit N]` | unbounded unless `--limit` |
| `ready [--label L]` | unbounded |
| `dep {add,remove,list} ID [TARGET] [--type blocks]` | `dep add A B` = A depends on B |
| `label {add,remove,list} ID [LABELS...]` | multi-label in one call |
| `search QUERY` | — |
| `sync [--pull]` | — |
| global | `--format {json,human}` (human renders to **stderr**; stdout envelope unchanged), `--protocol-version` |

## File structure

```
packages/workcli/
├── pyproject.toml                 # mirror prgroom's verbatim, adapted (Task 1)
├── uv.lock                        # committed (Task 1)
├── AGENTS.md                      # package gate + design guidance (Task 1)
├── README.md                      # verb table + envelope contract (Task 6)
├── src/workcli/
│   ├── __init__.py                # PROTOCOL_VERSION = "1.0"
│   ├── py.typed
│   ├── cli.py                     # argparse wiring + main() + dispatch + catch-all
│   ├── envelope.py                # ErrorCode, WorkError, success/failure/emit
│   ├── model.py                   # Item, DepEdge, DepListing, SyncResult, field sets
│   ├── backend.py                 # Backend protocol + Capabilities
│   ├── render.py                  # --format human stderr renderer (generic)
│   ├── verbs/
│   │   ├── __init__.py            # VERBS registry: name → handler
│   │   ├── read.py                # show, list, ready, search      (Task 3)
│   │   ├── write.py               # create --raw, update, note, close, reopen (Task 4)
│   │   ├── relations.py           # dep, label                     (Task 5)
│   │   └── syncing.py             # sync                           (Task 5)
│   └── adapters/
│       ├── __init__.py
│       └── bd/
│           ├── __init__.py
│           ├── runner.py          # BdRunner protocol + SubprocessBdRunner (S603/S607 ignores here only)
│           ├── parse.py           # bd JSON shape parsing + drift alarm
│           ├── retry.py           # bounded backoff (injectable sleep)
│           └── backend.py         # BdBackend: Backend impl over BdRunner
└── tests/
    ├── __init__.py
    ├── conftest.py                # fake fixtures, run_cli helper
    ├── fakes.py                   # ScriptedBdRunner (records calls, scripted results)
    ├── fixtures/                  # golden bd --json captures (Task 2)
    └── unit/
        ├── test_protocol_handshake.py     # item 10 (Task 1)
        ├── test_envelope.py               # envelope machinery (Task 1)
        ├── test_bd_parse.py               # golden-based parsing (Task 2)
        ├── test_lock_retry.py             # item 7  (Task 2)
        ├── test_drift_alarm.py            # item 9  (Task 2 core, Task 3 end-to-end)
        ├── test_show_normalization.py     # item 2  (Task 3)
        ├── test_list_unbounded.py         # item 5  (Task 3)
        ├── test_create_raw.py             # item 3  (Task 4)
        ├── test_note_append_only.py       # item 6  (Task 4)
        ├── test_dep_type_wall.py          # item 4  (Task 5)
        ├── test_sync.py                   # item 8  (Task 5)
        ├── test_capabilities.py           # stub-backend E_UNSUPPORTED_CAPABILITY (Task 5)
        └── test_envelope_invariants.py    # item 1 matrix, all 12 verbs × ok/fail (Task 6)
```

## Pinned shared contracts (copy exactly; do not restyle)

### envelope.py

```python
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TextIO

from workcli import PROTOCOL_VERSION

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ErrorCode(StrEnum):
    NOT_FOUND = "E_NOT_FOUND"
    TYPE_WALL = "E_TYPE_WALL"
    DEP_CYCLE = "E_DEP_CYCLE"
    FIELD_CLOBBER_GUARD = "E_FIELD_CLOBBER_GUARD"
    LOCK_CONTENTION = "E_LOCK_CONTENTION"
    SYNC_BEHIND = "E_SYNC_BEHIND"
    BACKEND_DRIFT = "E_BACKEND_DRIFT"
    UNSUPPORTED_CAPABILITY = "E_UNSUPPORTED_CAPABILITY"
    USAGE = "E_USAGE"
    INTERNAL = "E_INTERNAL"


@dataclass(frozen=True)
class WorkError(Exception):
    code: ErrorCode
    message: str
    detail: dict[str, JsonValue] = field(default_factory=dict)


def emit_success(data: JsonValue, out: TextIO = sys.stdout) -> int:
    json.dump({"protocol": PROTOCOL_VERSION, "ok": True, "data": data, "error": None}, out)
    out.write("\n")
    return 0


def emit_failure(err: WorkError, out: TextIO = sys.stdout) -> int:
    json.dump(
        {
            "protocol": PROTOCOL_VERSION,
            "ok": False,
            "data": None,
            "error": {"code": str(err.code), "message": err.message, "detail": err.detail},
        },
        out,
    )
    out.write("\n")
    return 1
```

### model.py (shapes; workers add constructors/serializers as needed)

```python
@dataclass(frozen=True)
class DepEdge:
    id: str
    type: str        # "blocks" | "related-to" | "parent-child" | "discovered-from" | ...
    status: str      # status of the bead at the other end


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    type: str        # task|bug|feature|epic|milestone (str, not enum: drift tolerance)
    status: str      # open|in_progress|closed|deferred
    priority: str    # "P0".."P4"
    labels: list[str]
    parent: str | None
    deps: list[DepEdge]        # up-edges (what this item depends on)
    children: list[str]
    description: str
    notes: str
    created: str | None        # ISO strings as bd emits them; no datetime parsing in v1
    updated: str | None


@dataclass(frozen=True)
class DepListing:
    up: list[DepEdge]
    down: list[DepEdge]


@dataclass(frozen=True)
class SyncResult:
    synced: bool
    mode: str  # "push" | "pull" | "noop"


@dataclass(frozen=True)
class CreateFields:
    title: str
    description: str | None = None
    type: str | None = None
    priority: str | None = None
    parent: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateFields:  # replace-semantics fields ONLY; notes never appear here
    title: str | None = None
    priority: str | None = None
    description: str | None = None
```

Item/DepEdge/etc. serialize to envelope `data` via `dataclasses.asdict` (labels stay `string[]`, multi-line strings stay proper JSON strings — that IS the normalization contract).

### backend.py

```python
@dataclass(frozen=True)
class Capabilities:
    supports_ready: bool
    supports_dep_types: bool
    supports_sync: bool


class Backend(Protocol):
    @property
    def capabilities(self) -> Capabilities: ...  # pragma: no cover
    def get(self, item_id: str) -> Item: ...  # pragma: no cover
    def batch_get(self, ids: Sequence[str]) -> list[Item]: ...  # pragma: no cover
    def create(self, fields: CreateFields) -> str: ...  # returns new item id  # pragma: no cover
    def set_fields(self, item_id: str, fields: UpdateFields) -> None: ...  # pragma: no cover
    def append_note(self, item_id: str, text: str) -> None: ...  # pragma: no cover
    def close(self, ids: Sequence[str]) -> None: ...  # pragma: no cover
    def reopen(self, item_id: str) -> None: ...  # pragma: no cover
    def query(self, filters: QueryFilters) -> list[Item]: ...  # pragma: no cover
    def ready(self, label: str | None) -> list[Item]: ...  # pragma: no cover
    def dep_mutate(self, op: str, from_id: str, to_id: str, dep_type: str) -> None: ...  # pragma: no cover
    def dep_list(self, item_id: str) -> DepListing: ...  # pragma: no cover
    def label_mutate(self, op: str, item_id: str, labels: Sequence[str]) -> None: ...  # pragma: no cover
    def labels(self, item_id: str) -> list[str]: ...  # pragma: no cover
    def search(self, query: str) -> list[Item]: ...  # pragma: no cover
    def sync(self, pull: bool) -> SyncResult: ...  # pragma: no cover
```

`QueryFilters`: frozen dataclass `{status, label, parent, type, limit: int | None}` — `limit=None`
means unbounded, and the bd adapter ALWAYS passes `--limit 0` unless a positive limit is given.

### runner.py (the subprocess port — the fake's seam)

```python
@dataclass(frozen=True)
class BdResult:
    returncode: int
    stdout: str
    stderr: str


class BdRunner(Protocol):
    def run(self, args: Sequence[str]) -> BdResult: ...  # pragma: no cover


class SubprocessBdRunner:
    """Drives the real bd binary. timeout=60s; TimeoutExpired is retryable (decision 8)."""
```

### main() signature (cli.py)

```python
def main(
    argv: Sequence[str] | None = None,
    *,
    runner: BdRunner | None = None,       # None → SubprocessBdRunner()
    out: TextIO | None = None,            # None → sys.stdout
    err: TextIO | None = None,            # None → sys.stderr
    sleep: Callable[[float], None] | None = None,  # None → time.sleep
) -> int: ...
```

Console script: `work = "workcli.cli:entry"` where `entry()` is `sys.exit(main())`.
Argparse subclass overrides `error()` to raise (so `E_USAGE` goes through the envelope);
`--protocol-version` is a top-level flag short-circuiting before subcommand validation.

### tests/fakes.py — ScriptedBdRunner

```python
@dataclass
class ScriptedStep:
    expect_prefix: tuple[str, ...]   # e.g. ("show",) — matched against args[:len(prefix)]
    result: BdResult


class ScriptedBdRunner:
    """Feeds scripted BdResults in order; records every call's full args.

    - .calls: list[tuple[str, ...]]  — every invocation, in order (the assertion surface
      for items 3, 4, 6, 8: what reached bd, and in what order)
    - mismatch between the next step's expect_prefix and actual args → test failure with
      a diff of expected vs actual (never a silent skip)
    - running past the script → test failure
    """
```

`conftest.py` provides `run_cli(argv, steps, *, sleep=None) -> tuple[int, dict, str]`
(exit code, parsed envelope from a StringIO stdout, stderr text) so every test reads as
behavior: invoke verb, assert envelope + call log.

---

## Tasks

Worker protocol for every task: (1) announce the task; (2) invoke `test-driven-development`
and `writing-unit-tests` skills; (3) red-green-refactor per step; (4) run the gate commands
listed; (5) commit with the given message; (6) report back: files changed, test evidence
(pasted pytest/gate tail), decisions made, open questions. Spawn no subagents. Add each
import together with its first use in the same edit (the post-edit ruff hook strips unused
imports). Never run mutating `bd` commands. Never edit files outside `packages/workcli/`,
the root `Makefile`, or paths a task explicitly names.

### Task 1: Scaffold, envelope, protocol handshake, CI gate

**Files:**
- Create: `packages/workcli/pyproject.toml`, `uv.lock`, `AGENTS.md`,
  `src/workcli/{__init__.py,py.typed,envelope.py,cli.py}`,
  `tests/{__init__.py,conftest.py}`, `tests/unit/{test_protocol_handshake.py,test_envelope.py}`
- Modify: root `Makefile` (WORKCLI var, `ci-workcli` block mirroring `ci-installer`
  one-for-one, add `ci-workcli` to the `ci:` line before `lint-actions`, extend `.PHONY`)

- [x] Copy `packages/prgroom/pyproject.toml` as the base: name `workcli`, description
  "work — facade CLI quarantining the issue-tracker backend (bd) behind a stable contract.",
  `dependencies = []`, `[project.scripts] work = "workcli.cli:entry"`,
  hatch wheel `packages = ["src/workcli"]`, coverage `source = ["src/workcli"]`,
  same ruff/mypy/coverage config verbatim, plus per-file-ignores
  `"src/workcli/adapters/bd/runner.py" = ["S603", "S607"]`
- [x] `src/workcli/__init__.py`: `PROTOCOL_VERSION = "1.0"` (+ docstring); create `py.typed`
- [x] Write failing tests: `--protocol-version` emits success envelope with
  `data == {"protocol": "1.0"}`, exit 0 (item 10); envelope unit tests (success/failure
  shapes, exit codes, `E_USAGE` on unknown verb goes through envelope not argparse stderr;
  unexpected exception → `E_INTERNAL` envelope + exit 1)
- [x] Implement `envelope.py` (pinned above) and minimal `cli.py`: parser with
  `--protocol-version`, `--format`, subparsers placeholder, dispatch loop with
  WorkError/catch-all handling, `main()` with the pinned signature
- [x] `uv sync` (generates uv.lock; commit it), run: `cd packages/workcli && uv run pytest -q`
  → all pass; `uv run ruff check && uv run ruff format --check && uv run mypy --strict src`
- [x] Wire root Makefile; `verify-entry-workcli` is BOTH:
  `uv --project $(WORKCLI) run work --protocol-version > /dev/null` and
  `uv --project $(WORKCLI) run work --help > /dev/null`
- [x] Write `packages/workcli/AGENTS.md` modeled on prgroom's (gate: `make ci-workcli`;
  design rules: verb layer never imports subprocess; adapters never print; all I/O
  injectable; contract tests via ScriptedBdRunner only)
- [x] From repo root: `make ci-workcli` → green. Commit:
  `feat(workcli): scaffold package with envelope, protocol handshake, CI gate`

### Task 2: Model, Backend seam, bd adapter core, scripted fake

**Files:**
- Create: `src/workcli/{model.py,backend.py}`,
  `src/workcli/adapters/{__init__.py,bd/__init__.py,bd/runner.py,bd/parse.py,bd/retry.py,bd/backend.py}`,
  `tests/fakes.py`, `tests/fixtures/*.json`,
  `tests/unit/{test_bd_parse.py,test_lock_retry.py,test_drift_alarm.py}`

- [x] Capture goldens from the MAIN repo root (read-only, decision 14):
  `bd show agents-config-wgclw.9 --json`, `bd show agents-config-wgclw.9.1 --json`,
  `bd list --status open --limit 5 --json`, `bd dep list agents-config-wgclw.9.1 --json`
  (try `--direction up` and `--direction down`), `bd label list agents-config-wgclw.9.1 --json`
  → save raw into `tests/fixtures/`. Also capture `--help` of `bd show/list/create/update/dep/label`
  into a scratch note (NOT committed) to confirm flag names the adapter must emit.
- [x] Write failing parse tests from the goldens: `show` single-element array → one `Item`;
  `.dependencies[]` full-bead-with-`dependency_type` → lean `DepEdge`; label list flat
  `string[]`; multi-line notes/description survive as JSON strings; missing/renamed keys →
  `WorkError(BACKEND_DRIFT)` (item 9 core)
- [x] Implement `model.py`, `backend.py` (pinned above), `parse.py`
- [x] Write failing retry tests (item 7): scripted runner fails twice with
  `database is locked` then succeeds → `ok: true` and 2 sleep calls recorded; fails 3× →
  `E_LOCK_CONTENTION`; non-retryable stderr → immediate mapped error, zero retries
- [x] Implement `retry.py` (attempts=3, backoff [0.5, 1.0], injectable sleep),
  `runner.py`, and `bd/backend.py` methods needed so far (`get`, `batch_get`, `query`)
  with the error-mapping table: not-found stderr → `E_NOT_FOUND`; type-wall → `E_TYPE_WALL`;
  cycle/deadlock → `E_DEP_CYCLE`; unknown → `E_BACKEND_DRIFT` (decision 4)
- [x] Implement `tests/fakes.py` ScriptedBdRunner + conftest `run_cli` helper (pinned above)
- [x] `cd packages/workcli && uv run pytest -q` green, then lint/format/mypy trio. Commit:
  `feat(workcli): Backend seam, bd adapter core with retry + drift alarm, scripted fake`

### Task 3: Read verbs — show, list, ready, search

**Files:**
- Create: `src/workcli/verbs/{__init__.py,read.py}`,
  `tests/unit/{test_show_normalization.py,test_list_unbounded.py}`
- Modify: `src/workcli/cli.py` (wire subparsers → registry), `src/workcli/adapters/bd/backend.py`
  (`ready`, `search`), `tests/unit/test_drift_alarm.py` (end-to-end case)

- [x] Failing tests first (via `run_cli`): item 2 — `work show X` → `data` is an object with
  lean deps + `string[]` labels; `work show X Y` → `data.items` length 2 (decision 10).
  Item 5 — fake returns 60 rows for `list` and 120 for `ready`; all surface; the fake's
  call log shows `--limit 0` was passed; `--limit 7` passes `--limit 7`. Item 9 end-to-end —
  scripted garbage `show` shape → envelope `E_BACKEND_DRIFT`, exit 1. `--parent` filter
  applied client-side if capture in Task 2 showed bd lacks the flag.
- [x] Implement `verbs/read.py` + registry + cli wiring; capability gate (decision 11) in the
  dispatch path
- [x] Full local gate trio + pytest. Commit: `feat(workcli): read verbs with normalization and unbounded defaults`

### Task 4: Write verbs — create --raw, update, note, close, reopen

**Files:**
- Create: `src/workcli/verbs/write.py`, `tests/unit/{test_create_raw.py,test_note_append_only.py}`
- Modify: `cli.py`, `adapters/bd/backend.py` (`create`, `set_fields`, `append_note`, `close`, `reopen`)

- [x] Failing tests: item 3 — `create --raw --parent P --title T` → fake log shows exactly ONE
  bd invocation (`create` with `--parent`), and NO `dep add` call; without `--raw` → `E_USAGE`
  (decision 7). Item 6 — two `note` calls → two `--append-notes` invocations in order; grep
  the adapter call log: no call ever carries the bare replace flag `--notes`;
  `update --set-notes x` → `E_FIELD_CLOBBER_GUARD` (decision 6). `close A B --disposition d`
  → one bd close with both ids + one append-note per id. `update` with no `--set-*` → `E_USAGE`.
- [x] Implement; commit: `feat(workcli): write verbs with append-only notes and clobber guard`

### Task 5: Relations + sync — dep, label, sync

**Files:**
- Create: `src/workcli/verbs/{relations.py,syncing.py}`,
  `tests/unit/{test_dep_type_wall.py,test_sync.py,test_capabilities.py}`
- Modify: `cli.py`, `adapters/bd/backend.py` (`dep_mutate`, `dep_list`, `label_mutate`,
  `labels`, `sync`)

- [x] Failing tests: item 4 — `dep add EPIC TASK --type blocks` where scripted `get`s return
  type epic/task → `E_TYPE_WALL`, and the fake call log contains NO `dep` mutation (decision 5;
  wall rule: `blocks` requires both epics or both non-epics). Item 8 — `sync` → call log order
  is exactly `dolt commit` then `dolt push`; `sync --pull` with scripted
  `cannot merge with uncommitted changes` → `E_SYNC_BEHIND`; commit-step `nothing to commit`
  → still `ok: true` (decision 9). `label add ID a b c` → three bd label-add calls (one per
  label), one envelope. `test_capabilities.py`: stub backend with `supports_sync=False` →
  `sync` → `E_UNSUPPORTED_CAPABILITY` (decision 11).
- [x] Implement; commit: `feat(workcli): dep/label/sync verbs with type-wall pre-check and ordered sync`

### Task 6: Contract matrix, human format, docs, spec amendment

**Files:**
- Create: `tests/unit/test_envelope_invariants.py`, `src/workcli/render.py`,
  `packages/workcli/README.md`
- Modify: `docs/specs/2026-07-04-work-facade-cli-contract.md` (§4: add `E_INTERNAL` with
  one-line rationale), root `AGENTS.md` (packages list + `make ci` composition line),
  `cli.py` (`--format human` hookup)

- [x] Failing matrix test (item 1): parametrized over all twelve verbs × {success, failure} —
  every invocation yields exactly one parseable stdout envelope carrying `protocol`, and exit
  code mirrors `ok`. Handshake consistency (item 10 tail): `--protocol-version`'s
  `data.protocol` equals the `protocol` field of every other verb's envelope.
- [x] `--format human`: generic renderer to stderr; test asserts stdout envelope byte-identical
  with and without the flag
- [x] README: verb table, envelope + error-code contract, consumer handshake snippet
- [x] Full gate: `make ci-workcli` then `make ci` (all packages + lint-actions) from the
  worktree root → green; paste evidence. Commit:
  `feat(workcli): envelope invariant matrix, human format, docs; spec: add E_INTERNAL`

---

## Delivery (orchestrator-owned; not worker tasks)

1. Completion gate per the completion-gate rule: `gate-triage` → expected HEAVY →
   `Workflow({name: "quality-gate", args: <triage JSON>})` → address findings →
   `verify-checklist` with evidence.
2. `finishing-a-development-branch` → PR (explicit merge policy — no merge without owner
   instruction) → `monitor-pr` grooming.
3. `bd dolt push` + `git push` before any pause. Bead .9.1 notes updated with state.

## Self-review (done at authoring)

- Spec coverage: §3 all twelve verbs → Tasks 3–5; §4 envelope/errors → Task 1 + decisions 3–4;
  §5 handshake → Task 1 + Task 6 tail; §6 seam + capabilities → Task 2 + decision 11/12;
  §11 items 1–10 → mapped 1:1 in file structure table. §7/§8/§9 are design-time (no code).
- Type consistency: all cross-task signatures live in "Pinned shared contracts" — workers
  copy, never re-derive.
- No placeholders: implementation bodies are deliberately delegated (worker + spec + pinned
  contracts); every behavioral requirement carries its concrete assertion.
