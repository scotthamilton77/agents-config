# Install Receipt Pruning Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-maintained `installer.toml` `[prune]` glob list with a post-install *receipt* that records every file/dir the installer authors wholesale, so pruning becomes a differential of the prior receipt against the desired staged plan.

**Architecture:** New pure-core modules under `packages/installer/src/installer/core/` (`receipt.py`, `receipt_store.py`, `ownership.py`, `receipt_diff.py`, `receipt_build.py`, `receipt_lock.py`) build/read/validate/diff a central JSON receipt at `~/.config/agents-config/install-receipt.json`. The orphan **differ** replaces `core/prune.py::scan_orphans`; the existing `run_prune` deletion flow and `Orphan` model are reused. `sync_plan`/`sync_routes` are extended to report per-item install outcomes. A single advisory lock spans the install→prune→receipt-write section.

**Tech Stack:** Python ≥3.11, `uv`-managed, `mypy --strict`, `ruff`, `pytest --cov` (90% branch floor). Pure core + injected `IOPort`. Gate: `make ci-installer` from repo root.

**Spec:** `docs/specs/2026-06-25-install-receipt-pruning-design.md` (authoritative; this plan implements it).

**Bead:** `agents-config-abn9.37.1.2`.

---

## Conventions for every task

- Work from `packages/installer/`. Run tests with `uv run pytest …` (or `make test-installer` from repo root for the whole suite).
- Each new core module is a **pure function** set — no `print`/`input`, no `rich`, no `Date.now()`-style ambient state; inject `home`, clocks, and I/O.
- Commit after each task with a `feat(installer):` / `test(installer):` / `refactor(installer):` prefix.
- The **full gate** (`make ci-installer`) must pass before the final delivery, not necessarily after every task; run `make test-installer` for the inner loop.

## File structure (what each new/modified file owns)

| File | Responsibility |
|---|---|
| `core/receipt.py` (new) | `ReceiptEntry` + `Receipt` dataclasses; canonical serialization; `integrity` digest compute/verify |
| `core/receipt_store.py` (new) | Read (missing→`MISSING`, corrupt/integrity-mismatch→`CORRUPT`, ok→`OK` + receipt); atomic write |
| `core/receipt_lock.py` (new) | `receipt_lock(path)` exclusive advisory-lock context manager |
| `core/ownership.py` (new) | `is_prunable(item)`; `entry_for(item, *, tool, home)` → `ReceiptEntry` for wholesale-owned items |
| `core/receipt_build.py` (new) | `entries_from_outcomes(...)`; `merge_receipt(prior, *, installed, pruned, relinquished, live_roots)` |
| `core/receipt_diff.py` (new) | `desired_staged_keys(...)`; `validate_entry(...)`; `diff_orphans(...)` (replaces `scan_orphans`) |
| `core/prune_hash.py` (new) | `partition_file_orphans(orphans, *, home)` → `(to_prune, relinquished_paths)` |
| `core/model.py` (modify) | Add `InstallOutcome` record + `Outcome` enum |
| `core/sync.py` (modify) | Thread an optional `outcomes` collector through `sync_plan`/`sync_routes`/`_install_file`/`_install_dir` |
| `core/run.py` (modify) | `prune_pipeline` uses `diff_orphans` + hash filter; new receipt read/build/write; lock |
| `core/cli.py` (modify) | Thread discovered plugins, `home`, receipt path; acquire the lock around the mutation section |
| `core/prune.py` (modify→shrink) | Delete `scan_orphans`, `_scan_namespace`, `_staged_basenames`, `_routed_staged_basenames`, `_BEADS_*`, `_PRUNE_SUBDIRS` |
| `core/installer_toml.py` (modify) | Remove `prune_globs` loading (keep `[tools]` override loading) |
| `installer.toml` (modify) | Remove the `[prune]` section |

---

## Phase 1 — Tracer bullet (thin end-to-end slice)

Goal of the phase: prove the architecture — **install records a receipt; dropping a source file and reinstalling with `--prune` removes it** — through write→read→diff→prune, with *minimal* machinery (no integrity, no outcomes, no hash filter, no lock yet). Those layer on in later phases.

### Task 1: `ReceiptEntry` / `Receipt` model

**Files:**
- Create: `packages/installer/src/installer/core/receipt.py`
- Test: `packages/installer/tests/unit/test_receipt_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_receipt_model.py
from pathlib import Path

from installer.core.receipt import Receipt, ReceiptEntry


def test_entry_is_frozen_and_carries_fields() -> None:
    e = ReceiptEntry(
        path=Path(".claude/skills/foo"),
        owner="claude",
        root=Path(".claude"),
        kind="dir",
        sha256=None,
    )
    assert e.path == Path(".claude/skills/foo")
    assert e.owner == "claude"
    assert e.root == Path(".claude")
    assert e.kind == "dir"
    assert e.sha256 is None


def test_receipt_holds_schema_roots_and_entries() -> None:
    r = Receipt(schema_version=1, roots=(Path(".beads"),), entries=())
    assert r.schema_version == 1
    assert r.roots == (Path(".beads"),)
    assert r.entries == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_receipt_model.py -q`
Expected: FAIL — `ModuleNotFoundError: installer.core.receipt`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/receipt.py
"""The install receipt — a record of what the installer authored wholesale.

Distinct from the ``.installignore`` *exclusion manifest* (source-side); the
receipt records destination output so pruning can diff "what we installed" against
"what we still want installed". See docs/specs/2026-06-25-install-receipt-pruning-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReceiptEntry:
    """One wholesale-authored dest entry. ``path``/``root`` are home-relative."""

    path: Path
    owner: str
    root: Path
    kind: Literal["file", "dir"]
    sha256: str | None


@dataclass(frozen=True, slots=True)
class Receipt:
    """The whole receipt. ``roots`` is the persisted install-root allowlist."""

    schema_version: int = SCHEMA_VERSION
    roots: tuple[Path, ...] = ()
    entries: tuple[ReceiptEntry, ...] = ()
    integrity: str | None = field(default=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_receipt_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/receipt.py packages/installer/tests/unit/test_receipt_model.py
git commit -m "feat(installer): add ReceiptEntry/Receipt model"
```

### Task 2: JSON (de)serialize + minimal store (no integrity yet)

**Files:**
- Create: `packages/installer/src/installer/core/receipt_store.py`
- Test: `packages/installer/tests/unit/test_receipt_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_receipt_store.py
from pathlib import Path

from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    receipt = Receipt(
        roots=(Path(".claude"),),
        entries=(
            ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", "ab"),
        ),
    )
    write_receipt(path, receipt)
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    assert result.receipt.entries[0].path == Path(".claude/rules/x.md")
    assert result.receipt.roots == (Path(".claude"),)


def test_missing_file_is_missing(tmp_path: Path) -> None:
    result = read_receipt(tmp_path / "absent.json")
    assert result.status is ReadStatus.MISSING
    assert result.receipt is None


def test_unparseable_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    path.write_text("{ this is not json", encoding="utf-8")
    result = read_receipt(path)
    assert result.status is ReadStatus.CORRUPT
    assert result.receipt is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_receipt_store.py -q`
Expected: FAIL — `ModuleNotFoundError: installer.core.receipt_store`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/receipt_store.py
"""Read/write the install receipt with missing-vs-corrupt distinction.

Read never raises on bad data: a missing file is ``MISSING`` (bootstrap empty),
anything present-but-unusable is ``CORRUPT`` (fail closed). Write is atomic
(temp file + ``os.replace``). The integrity digest is added in Task 11.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from installer.core.receipt import SCHEMA_VERSION, Receipt, ReceiptEntry


class ReadStatus(Enum):
    MISSING = "missing"
    CORRUPT = "corrupt"
    OK = "ok"


@dataclass(frozen=True, slots=True)
class ReceiptRead:
    status: ReadStatus
    receipt: Receipt | None


def _entry_to_json(e: ReceiptEntry) -> dict[str, object]:
    return {
        "path": str(e.path),
        "owner": e.owner,
        "root": str(e.root),
        "kind": e.kind,
        "sha256": e.sha256,
    }


def _entry_from_json(d: object) -> ReceiptEntry:
    if not isinstance(d, dict):
        raise ValueError("entry is not an object")
    kind = d["kind"]
    if kind not in ("file", "dir"):
        raise ValueError(f"bad kind {kind!r}")
    sha = d["sha256"]
    if sha is not None and not isinstance(sha, str):
        raise ValueError("sha256 must be string or null")
    return ReceiptEntry(
        path=Path(str(d["path"])),
        owner=str(d["owner"]),
        root=Path(str(d["root"])),
        kind=kind,
        sha256=sha,
    )


def to_json_obj(receipt: Receipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "integrity": receipt.integrity,
        "roots": [str(r) for r in receipt.roots],
        "entries": [_entry_to_json(e) for e in receipt.entries],
    }


def _receipt_from_json(data: object) -> Receipt:
    if not isinstance(data, dict):
        raise ValueError("receipt is not an object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}")
    roots_raw = data.get("roots", [])
    entries_raw = data.get("entries", [])
    if not isinstance(roots_raw, list) or not isinstance(entries_raw, list):
        raise ValueError("roots/entries must be lists")
    return Receipt(
        schema_version=SCHEMA_VERSION,
        roots=tuple(Path(str(r)) for r in roots_raw),
        entries=tuple(_entry_from_json(e) for e in entries_raw),
        integrity=(str(data["integrity"]) if data.get("integrity") is not None else None),
    )


def read_receipt(path: Path) -> ReceiptRead:
    if not path.is_file():
        return ReceiptRead(ReadStatus.MISSING, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        receipt = _receipt_from_json(data)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return ReceiptRead(ReadStatus.CORRUPT, None)
    return ReceiptRead(ReadStatus.OK, receipt)


def write_receipt(path: Path, receipt: Receipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_json_obj(receipt), indent=2, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_receipt_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/receipt_store.py packages/installer/tests/unit/test_receipt_store.py
git commit -m "feat(installer): add receipt store with missing/corrupt read distinction"
```

### Task 3: Ownership classifier + entry assignment

**Files:**
- Create: `packages/installer/src/installer/core/ownership.py`
- Test: `packages/installer/tests/unit/test_ownership.py`

Reference: `core/model.py` `StagedItem` (`dest_relpath`, `kind`, `namespace`, `content`, `executable`); `core/merge/registry.py` strategy mapping. A wholesale-owned item is a namespaced `commands/skills/agents/rules` entry or a plugin route file — **not** `settings.json` (`SETTINGS_JSON`) nor an append-merged instruction file (`NAMESPACED_MD` with namespace not in the prune set is fatal/owned; the assembled instruction files are `OTHER`/`*_MD` written outside the prune namespaces). v1 rule: **prunable iff `kind` is `DIR` or `FILE` and the item's first-level namespace is one of `commands/skills/agents/rules`** (tool-tree), plugin route entries are classified separately in Task 4.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ownership.py
from pathlib import Path

from installer.core.model import FileKind, Provenance, StagedItem
from installer.core.ownership import PRUNE_NAMESPACES, entry_for, is_prunable


def _item(relpath: str, kind: FileKind, namespace: str | None) -> StagedItem:
    return StagedItem(
        source_path=Path("/src/x"),
        dest_relpath=Path(relpath),
        kind=kind,
        namespace=namespace,
        provenance=Provenance.SHARED,
        content=(b"x" if kind != FileKind.DIR else None),
    )


def test_skill_dir_is_prunable() -> None:
    assert is_prunable(_item("skills/foo", FileKind.DIR, "skills"))


def test_rule_file_is_prunable() -> None:
    assert is_prunable(_item("rules/x.md", FileKind.NAMESPACED_MD, "rules"))


def test_settings_json_is_not_prunable() -> None:
    assert not is_prunable(_item("settings.json", FileKind.SETTINGS_JSON, None))


def test_entry_for_a_tool_item_owns_by_tool_with_home_relative_root() -> None:
    item = _item("skills/foo", FileKind.DIR, "skills")
    entry = entry_for(item, tool="claude", dest_root=Path("/home/u/.claude"), home=Path("/home/u"))
    assert entry is not None
    assert entry.owner == "claude"
    assert entry.root == Path(".claude")
    assert entry.path == Path(".claude/skills/foo")
    assert entry.kind == "dir"


def test_prune_namespaces_constant() -> None:
    assert PRUNE_NAMESPACES == ("commands", "skills", "agents", "rules")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ownership.py -q`
Expected: FAIL — `ModuleNotFoundError: installer.core.ownership`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/ownership.py
"""Decide which staged items the receipt records (wholesale-owned, prune-eligible).

A merge-target (settings.json, append-merged instruction file) is never recorded:
dropping our contribution must not delete the whole file. Coincides with the
existing prune namespaces.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import FileKind, StagedItem

PRUNE_NAMESPACES: tuple[str, ...] = ("commands", "skills", "agents", "rules")


def is_prunable(item: StagedItem) -> bool:
    """True iff this item is a wholesale file/dir under a prune namespace."""
    parts = item.dest_relpath.parts
    if not parts or parts[0] not in PRUNE_NAMESPACES:
        return False
    if item.kind == FileKind.SETTINGS_JSON:
        return False
    return item.kind in (FileKind.DIR, FileKind.NAMESPACED_MD, FileKind.OTHER)


def entry_for(item: StagedItem, *, tool: str, dest_root: Path, home: Path):
    """Build a ReceiptEntry for a tool-tree item, or None if not prunable.

    sha256 is filled in by the builder from the install outcome (Task 8); here it
    is left None and the builder overwrites it for files.
    """
    from installer.core.receipt import ReceiptEntry

    if not is_prunable(item):
        return None
    return ReceiptEntry(
        path=(dest_root / item.dest_relpath).relative_to(home),
        owner=tool,
        root=dest_root.relative_to(home),
        kind=("dir" if item.kind == FileKind.DIR else "file"),
        sha256=None,
    )
```

> NOTE: confirm the exact `FileKind` members and `Provenance` values against `core/model.py` before running; adjust the import/enum names if they differ. The `is_prunable` kind set must include whatever kind individual `rules/*.md` files carry (`NAMESPACED_MD`) and skill/agent dirs carry (`DIR`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_ownership.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/ownership.py packages/installer/tests/unit/test_ownership.py
git commit -m "feat(installer): add receipt ownership classifier"
```

### Task 4: Minimal differ (prior − staged, tools-only scope) + plugin-route owner

**Files:**
- Create: `packages/installer/src/installer/core/receipt_diff.py`
- Test: `packages/installer/tests/unit/test_receipt_diff.py`

This is the tracer differ: scope = resolved tools only; diff prior receipt against the desired staged keys; emit `Orphan`. Plugin/owner scope, path validation, and root legitimacy are added in Phase 2/3.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_receipt_diff.py
from pathlib import Path

from installer.core.model import Orphan
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_diff import diff_orphans


def _entry(path: str, owner: str, root: str, kind: str = "file") -> ReceiptEntry:
    return ReceiptEntry(Path(path), owner, Path(root), kind, None)  # type: ignore[arg-type]


def test_dropped_entry_becomes_orphan() -> None:
    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(
            _entry(".claude/skills/keep", "claude", ".claude", "dir"),
            _entry(".claude/skills/drop", "claude", ".claude", "dir"),
        ),
    )
    desired = {("claude", Path(".claude/skills/keep"))}
    orphans = diff_orphans(
        prior,
        desired_keys=desired,
        scope_owners={"claude"},
        home=Path("/home/u"),
    )
    assert [o.path for o in orphans] == [Path("/home/u/.claude/skills/drop")]
    assert orphans[0].tool == "claude"


def test_untargeted_owner_is_untouched() -> None:
    prior = Receipt(
        roots=(Path(".codex"),),
        entries=(_entry(".codex/skills/x", "codex", ".codex", "dir"),),
    )
    orphans = diff_orphans(prior, desired_keys=set(), scope_owners={"claude"}, home=Path("/home/u"))
    assert orphans == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_receipt_diff.py -q`
Expected: FAIL — `ModuleNotFoundError: installer.core.receipt_diff`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/receipt_diff.py
"""Diff a prior receipt against the desired staged plan to find orphans.

Replaces core/prune.py::scan_orphans. Scope and path validation are layered on
in later tasks; this tracer covers the core differential. An orphan is a
recorded entry whose owner is in scope and whose (owner, path) is not desired.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import Orphan
from installer.core.receipt import Receipt


def diff_orphans(
    prior: Receipt,
    *,
    desired_keys: set[tuple[str, Path]],
    scope_owners: set[str],
    home: Path,
) -> list[Orphan]:
    orphans: list[Orphan] = []
    for e in prior.entries:
        if e.owner not in scope_owners:
            continue
        if (e.owner, e.path) in desired_keys:
            continue
        orphans.append(
            Orphan(
                tool=e.owner,
                namespace=e.path.parts[1] if len(e.path.parts) >= 2 else "",
                path=home / e.path,
                kind=e.kind,
            )
        )
    return orphans
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_receipt_diff.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/receipt_diff.py packages/installer/tests/unit/test_receipt_diff.py
git commit -m "feat(installer): add tracer receipt differ (prior - desired staged)"
```

### Task 5: Receipt builder from the plan (tracer) + `desired_staged_keys`

**Files:**
- Create: `packages/installer/src/installer/core/receipt_build.py`
- Test: `packages/installer/tests/unit/test_receipt_build.py`

Tracer builder: derive owned entries + desired keys directly from the `StagingPlan`s. (Phase 2 Task 8 swaps the *builder* source from the plan to actual install outcomes; `desired_staged_keys` stays plan-derived — that's correct, it is "what we want installed".)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_receipt_build.py
from pathlib import Path

from installer.core.receipt_build import desired_staged_keys, entries_from_plans
# Build a tiny StagingPlan with one skill dir under "claude". Use existing
# test helpers/factories in tests/ if present; otherwise construct StagedItem +
# StagingPlan inline as in test_ownership.py.


def test_entries_and_desired_keys_align(make_plan) -> None:  # make_plan: local fixture
    plans = {"claude": make_plan([("skills/foo", "dir")])}
    dest_roots = {"claude": Path("/home/u/.claude")}
    entries = entries_from_plans(plans, dest_roots=dest_roots, home=Path("/home/u"))
    keys = desired_staged_keys(plans, dest_roots=dest_roots, home=Path("/home/u"), scope_owners={"claude"})
    assert any(e.path == Path(".claude/skills/foo") for e in entries)
    assert ("claude", Path(".claude/skills/foo")) in keys
```

> Implementer note: factor a small local `make_plan` fixture (StagedItem→StagingPlan) into `tests/unit/conftest.py` if no equivalent exists; reuse it across receipt tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_receipt_build.py -q`
Expected: FAIL — `ModuleNotFoundError: installer.core.receipt_build`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/receipt_build.py
"""Build receipt entries and desired-key sets from staging plans / install outcomes.

desired_staged_keys is ALWAYS plan-derived (what we want installed now, built
even under --prune-only) and drives orphan detection. entries_from_plans is the
tracer source for the receipt write; Task 8 replaces it with entries_from_outcomes
(install-outcome-derived) for write correctness.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.ownership import entry_for
from installer.core.receipt import ReceiptEntry


def entries_from_plans(plans, *, dest_roots, home: Path) -> list[ReceiptEntry]:
    out: list[ReceiptEntry] = []
    for tool, plan in plans.items():
        dest_root = dest_roots[tool]
        for item in plan.items.values():
            entry = entry_for(item, tool=tool, dest_root=dest_root, home=home)
            if entry is not None:
                out.append(entry)
    return out


def desired_staged_keys(plans, *, dest_roots, home: Path, scope_owners) -> set[tuple[str, Path]]:
    keys: set[tuple[str, Path]] = set()
    for tool, plan in plans.items():
        if tool not in scope_owners:
            continue
        dest_root = dest_roots[tool]
        for item in plan.items.values():
            entry = entry_for(item, tool=tool, dest_root=dest_root, home=home)
            if entry is not None:
                keys.add((tool, entry.path))
    return keys
```

> Type note: `plans` is `dict[str, StagingPlan]` (string tool key here for uniformity with owners; convert from the existing `dict[Tool, StagingPlan]` at the call site in `run.py`). `dest_roots` is `dict[str, Path]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_receipt_build.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/receipt_build.py packages/installer/tests/unit/test_receipt_build.py packages/installer/tests/unit/conftest.py
git commit -m "feat(installer): add receipt builder + desired_staged_keys (plan-derived)"
```

### Task 6: Wire the tracer into `prune_pipeline` (end-to-end)

**Files:**
- Modify: `packages/installer/src/installer/core/run.py` (`prune_pipeline`, lines ~37-70)
- Test: `packages/installer/tests/unit/test_run_prune_pipeline.py` (extend) or new `test_receipt_pipeline.py`

Replace the `scan_orphans(...)` call in `prune_pipeline` with: build `desired_staged_keys` from `plans`, read the prior receipt, `diff_orphans(...)`, then `run_prune(...)`. After the prune, build the new receipt from the plans and `write_receipt(...)`. Keep `scan_orphans` importable for now (deleted in Phase 4). Thread a `receipt_path: Path` and `home` and `dest_roots` into `prune_pipeline`.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/unit/test_receipt_pipeline.py
# Drive prune_pipeline end-to-end through ScriptedIO:
#  1. write a prior receipt with two entries (keep, drop) under a tmp home
#  2. create the on-disk dirs for both
#  3. build plans that stage only "keep"
#  4. run prune_pipeline(..., auto_yes=True)
#  5. assert "drop" dir is gone, "keep" remains, and the rewritten receipt
#     contains only "keep".
```

(Write the concrete test using the package's existing `ScriptedIO` + plan factories; assert on the filesystem and the re-read receipt.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_receipt_pipeline.py -q`
Expected: FAIL — `prune_pipeline` still calls `scan_orphans`; new params unfilled.

- [ ] **Step 3: Modify `prune_pipeline`**

```python
# core/run.py (prune_pipeline) — replace the scan_orphans body
from installer.core.receipt_build import desired_staged_keys, entries_from_plans
from installer.core.receipt_diff import diff_orphans
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt
from installer.core.receipt import Receipt

# inside prune_pipeline(...), with new params: receipt_path, home, dest_roots,
# scope_owners (tracer: the resolved tool names):
prior_read = read_receipt(receipt_path)
prior = prior_read.receipt if prior_read.status is ReadStatus.OK else Receipt()
keys = desired_staged_keys(str_plans, dest_roots=dest_roots, home=home, scope_owners=scope_owners)
orphans = diff_orphans(prior, desired_keys=keys, scope_owners=scope_owners, home=home)
counters = run_prune(orphans, io=io, dry_run=dry_run, auto_yes=auto_yes, prune_only=prune_only, timestamp=timestamp)
if not dry_run:
    new_entries = entries_from_plans(str_plans, dest_roots=dest_roots, home=home)
    write_receipt(receipt_path, Receipt(roots=tuple(dest_roots[t].relative_to(home) for t in dest_roots), entries=tuple(new_entries)))
return counters
```

> Convert `plans: dict[Tool, StagingPlan]` → `str_plans: dict[str, StagingPlan]` keyed by `adapter.name`; build `dest_roots: dict[str, Path]` from `adapter.dest_dir(home)` for each adapter. The mirrors-disk subtraction of pruned/relinquished is added in Phase 2 (Task 9) — the tracer's blunt overwrite is replaced there.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_receipt_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(installer): wire tracer receipt prune end-to-end into prune_pipeline"
```

**Tracer checkpoint:** architecture validated — write→read→diff→prune works end-to-end. Pause for review before Phase 2.

---

## Phase 2 — Correctness (scope, outcomes, mirrors-disk)

### Task 7: Full scope — discovered plugins + prior-receipt plugin owners; plugin-route owner/root

**Files:**
- Modify: `core/receipt_diff.py` (add `scope_owners(...)`), `core/ownership.py` (plugin-route `entry_for`)
- Test: extend `test_receipt_diff.py`, `test_ownership.py`

Implement `scope_owners(resolved_tools, discovered_plugin_names, prior) = set(resolved_tools) | set(discovered_plugin_names) | {e.owner for e in prior.entries if e.owner not in all_tool_names}`. Add plugin-route classification: a `PluginRoute` dest file is owned by the **plugin name**, with `root = route.dest_dir.relative_to(home)`'s top segment. Tests: excluded plugin pruned; retired plugin (in prior, not discovered) still in scope; untargeted tool excluded.

(Full TDD steps: write the three scope tests RED, implement `scope_owners` + plugin-route `entry_for` GREEN, commit.)

### Task 8: Per-item install outcomes in `sync`; builder from outcomes

**Files:**
- Modify: `core/model.py` (add `Outcome` enum + `InstallOutcome`), `core/sync.py` (`sync_plan`/`sync_routes`/`_install_file`/`_install_dir`/`_record_write` thread an optional `outcomes: list[InstallOutcome] | None`)
- Add: `core/receipt_build.py::entries_from_outcomes`
- Test: `test_sync_outcomes.py`, extend `test_receipt_build.py`

```python
# core/model.py additions
class Outcome(Enum):
    WRITTEN = "written"          # created or updated
    SKIPPED_IDENTICAL = "skipped_identical"
    DECLINED = "declined"        # consent declined → user's bytes


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    dest_relpath: Path
    outcome: Outcome
    sha256: str | None  # for WRITTEN/SKIPPED_IDENTICAL files; None for dirs
```

Thread `outcomes` additively through `sync_plan`/`sync_routes` (default `None` → no recording; existing `Counters` return unchanged). At the create/update site (`_record_write`) append `WRITTEN`; at the hash-equal skip append `SKIPPED_IDENTICAL`; at the consent-decline skip (sync.py ~344, ~430) append `DECLINED`. `entries_from_outcomes(outcomes, *, tool, dest_root, home)` builds entries for `WRITTEN`/`SKIPPED_IDENTICAL` only, attaching the per-file `sha256`.

Tests (RED→GREEN→commit): (a) declined overwrite yields `Outcome.DECLINED` and is excluded from entries; (b) created/updated/skipped-identical are included with sha256; (c) the raw `Counters` tally is unchanged (regression).

### Task 9: Mirrors-disk receipt write with relinquishment

**Files:**
- Modify: `core/receipt_build.py` (`merge_receipt`), `core/prune_flow.py` (`run_prune` returns pruned paths), `core/run.py`
- Test: `test_receipt_build.py`, `test_run_prune_pipeline.py`

Extend `run_prune` to also return the set of actually-removed paths (e.g. return `tuple[dict[str, Counters], set[Path]]`, or thread a `removed: set[Path]` collector — pick the additive option and update callers). Implement:

```python
def merge_receipt(prior, *, installed, pruned_paths, relinquished_paths, live_roots):
    by_path = {e.path: e for e in prior.entries if e.path not in pruned_paths and e.path not in relinquished_paths}
    for e in installed:  # installed wins (refreshed sha256)
        by_path[e.path] = e
    roots = tuple(sorted(set(prior.roots) | set(live_roots), key=str))
    return Receipt(roots=roots, entries=tuple(by_path.values()))
```

`relinquished_paths` = consent-declined-of-already-recorded (from outcomes ∩ prior) ∪ (hash-mismatched file orphans, Task 12). `installed` = `entries_from_outcomes`. `pruned_paths` = home-relative forms of what `run_prune` removed. Tests: `--prune-only` over populated receipt preserves still-staged (RED for the mass-delete trap); a `--tools=claude` run preserves codex entries; declined-overwrite mid-life relinquishes.

---

## Phase 3 — Safety hardening

### Task 10: Single-writer advisory lock

**Files:**
- Create: `core/receipt_lock.py`; Modify: `core/cli.py` (wrap the install→prune→write section)
- Test: `test_receipt_lock.py`

```python
# core/receipt_lock.py
import fcntl
from contextlib import contextmanager
from pathlib import Path


class ReceiptLockBusy(RuntimeError):
    pass


@contextmanager
def receipt_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = lock_path.open("w")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ReceiptLockBusy("another install is in progress") from exc
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
```

Wrap the mutation section in `cli.main` (install_pipeline → install_plugin_routes → `_run_prune`) in `with receipt_lock(receipt_path.with_suffix(".lock")):`; on `ReceiptLockBusy`, `io.err(...)` and `return 1`. Test: a second acquire raises `ReceiptLockBusy` while the first is held; install/prune-race is asserted at integration level.

### Task 11: Integrity digest (compute on write, verify on read, fail closed)

**Files:**
- Modify: `core/receipt.py` (`canonical_bytes`, `compute_integrity`, `with_integrity`), `core/receipt_store.py` (write computes; read verifies → CORRUPT on mismatch/missing)
- Test: extend `test_receipt_store.py` (the integrity-gate case)

```python
# core/receipt.py additions
import hashlib

def canonical_bytes(receipt: Receipt) -> bytes:
    payload = {
        "schema_version": receipt.schema_version,
        "roots": [str(r) for r in receipt.roots],
        "entries": sorted(
            ([str(e.path), e.owner, str(e.root), e.kind, e.sha256] for e in receipt.entries),
            key=lambda row: row[0],
        ),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

def compute_integrity(receipt: Receipt) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(receipt)).hexdigest()
```

`write_receipt` sets `integrity = compute_integrity(receipt)` (over the integrity-free content) before serialization. `read_receipt`, after parsing, recomputes and compares; mismatch or missing `integrity` → `ReadStatus.CORRUPT`. Test: a parseable receipt with a self-consistent unintended `root`+entry but a broken/absent digest → CORRUPT (prunes nothing); same content with a valid digest → OK.

### Task 12: Path trust boundary + hash-aware file prune filter

**Files:**
- Modify: `core/receipt_diff.py` (`validate_entry`), Create: `core/prune_hash.py`
- Test: `test_receipt_diff.py` (validation matrix), `test_prune_hash.py`

`validate_entry(entry, *, home, live_roots_by_owner, allowlist)`:
- reject if `entry.path`/`entry.root` is absolute or has `..` part;
- containment (symlink-aware): `(home / entry.path).resolve()` must be relative to `(home / entry.root).resolve()`;
- root legitimacy: tool owner → `entry.root` == its live `dest_dir(home).relative_to(home)`; discovered plugin → in its live route roots; else (retired) → `entry.root in allowlist`.
Invalid → skip (not an orphan). Wire `validate_entry` into `diff_orphans` (filter before emitting).

`prune_hash.partition_file_orphans(orphans, *, home, recorded_sha_by_path)` → `(to_prune, relinquished_paths)`: for `kind=="file"`, hash the on-disk file; if it differs from the recorded sha256 → relinquish (keep file), else prune; `kind=="dir"` always to_prune. Wire into `prune_pipeline`: filter orphans through the hash partition before `run_prune`, and add `relinquished_paths` to `merge_receipt`. Tests cover the validation matrix (forged live-owner root rejected; retired-root-in-allowlist passes; symlink-escape rejected) and hash match→prune / mismatch→relinquish.

---

## Phase 4 — Cleanup & full wiring

### Task 13: Thread discovered plugins + receipt path through `cli.main` / `_run_prune`

**Files:** Modify `core/cli.py` (`main`, `_run_prune`), `core/run.py` (`prune_pipeline` final signature)
- Compute `discovered = discover(resolve_plugins_root(resolved_repo_root, os.environ))` once; pass `discovered` names + `plugins` (active) + `home` + `receipt_path = resolved_home / ".config/agents-config/install-receipt.json"` into `_run_prune` → `prune_pipeline`. Build `scope_owners` via Task 7. Move the lock (Task 10) to wrap the whole section. Add a unit test asserting a `--tools=claude` run leaves a codex receipt entry intact end-to-end.

### Task 14: Delete the glob-scan path

**Files:** Modify `core/prune.py` (delete `scan_orphans`, `_scan_namespace`, `_staged_basenames`, `_routed_staged_basenames`, `_BEADS_TOOL`, `_BEADS_NAMESPACE`, `_PRUNE_SUBDIRS`), update/remove `test_prune.py` accordingly. Remove the now-dead `scan_orphans` import in `run.py`. Confirm no other importers (`rg scan_orphans`).

### Task 15: Remove `[prune]` config

**Files:** Modify `installer.toml` (delete the `[prune]` section), `core/installer_toml.py` (remove `prune_globs` field + loading; keep `[tools]` override loading), update `test_installer_toml.py` (drop prune-glob cases; assert a present-but-no-`[prune]` file still loads). Remove `config.prune_globs` references.

### Task 16: Full test matrix + gate

**Files:** Add any missing tests from the spec's Testing strategy not yet covered (cross-tree relocation `zoom-out` integration; `~/.beads/scripts` route coverage; retired-plugin route + overlay integration; single-writer install/prune race; symlinked-root integration). Then:

- [ ] Run `make ci-installer` from the repo root.
- [ ] Expected: lint, format-check, `mypy --strict`, `pytest --cov` ≥90% branch, `pip-audit`, entry-verify all green.
- [ ] Fix any failures; re-run until clean.
- [ ] Commit.

---

## Self-review checklist (run before delivery)

- [ ] **Spec coverage:** every spec section maps to a task — schema (T1/T8/T11), store missing/corrupt (T2/T11), ownership (T3), scope incl. retired plugin (T4/T7), per-item outcomes (T8), mirrors-disk + relinquish (T9), lock (T10), integrity (T11), path trust boundary + symlink + hash filter (T12), wiring (T6/T13), deletions (T14/T15), tests (T16).
- [ ] **Placeholder scan:** no "TBD"/"handle edge cases" left; the prose tasks (T7–T12) name exact files, signatures, and test assertions.
- [ ] **Type consistency:** `Receipt`/`ReceiptEntry` fields, `ReadStatus`/`ReceiptRead`, `Outcome`/`InstallOutcome`, `entry_for`/`entries_from_*`, `diff_orphans`/`validate_entry`/`partition_file_orphans` signatures match across tasks.
- [ ] **`Orphan` shape:** `tool`/`namespace`/`path`/`kind` matches `core/model.py` (verify `kind` accepts `"dir"`/`"file"` strings as recorded).
- [ ] **Verify-before-code:** confirm `FileKind` member names, `Provenance` values, `is_safe_relpath` location, `Orphan` fields, and `discover`/`resolve_plugins_root` imports against the real source before each task (the plan cites them but the engineer must check).
