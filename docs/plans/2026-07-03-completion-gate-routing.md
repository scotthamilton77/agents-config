# Completion-Gate Routing Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three-tier completion-gate router (`SKIP` / `SERIAL` / `HEAVY`) — a deterministic `gate-triage` helper that routes each change to the right verification depth, a `.critical-paths` escalation marker, a `quality-gate` saved workflow for the `HEAVY` path, and the installer + rule wiring that makes it real.

**Architecture:** A pure-core Python helper (`gate_triage.py`) reads diff facts + markers + config and emits a tier floor as JSON. The `completion-gate` rule gains a routing preamble that runs the helper, applies a bounded risk-class escalation, announces, and routes. `HEAVY` invokes a saved Claude-only `quality-gate` workflow (steps 1–4 as multi-agent finders); step 5 (verify-checklist) is non-substitutable under every tier. Non-Claude tools degrade `HEAVY` → `SERIAL`.

**Tech Stack:** Python ≥ 3.11 (`uv run` + PEP 723 inline metadata + `pathspec` — a first-of-its-kind asset in this repo), pytest, the existing `packages/installer` (uv/ruff/mypy-strict/pytest), a Claude Code saved Workflow script (JS), and shared instruction/rule templates.

**Source spec:** `docs/specs/2026-07-02-completion-gate-routing-design.md` (bead `agents-config-abn9.38`). The convergence discipline for the `HEAVY` workflow's loop is deferred to its own lineage (`agents-config-vaac.2`, decision record `docs/specs/2026-07-03-adversarial-loop-convergence-decision.md`); this plan ships the **interim** capped-round loop that emits a dual-signal residual-risk report.

---

## Installer touch-points

Namespace awareness lives in four independently hardcoded Python lists (verified against the current installer; agrees with spec §7.1). Each must learn about `workflows`:

| Touch-point | Role | Task |
|---|---|---|
| `claude.py::scoped_namespaces()` (`claude.py:29-30`) | staging + deploy source | Task 1 |
| `ownership.py::PRUNE_NAMESPACES` (`ownership.py:15`) | receipt tracking + prune eligibility | Task 2 |
| `backup.py::_SCOPED_NAMESPACES` (`backup.py:24`) | sibling-dir backup routing (consistency) | Task 3 |
| `merge/registry.py::default_registry()` | collision strategy by namespace; un-wired → `UnknownMergeKeyError` on collision | Task 4 |

`scripts/install.sh` is untouched — a 6-line `exec uv run` stub with no namespace logic. `overlay.py::_TOOL_NAMESPACES` (plugin overlay) is out of scope: it matters only if a plugin ships workflows, and none do.

Net installer change: **4 code edits + 1 test-constant fix + 3 new tests.**

## Scope and PR phasing

One feature, five phases. Each phase is a coherent, independently-testable chunk; they can land as one PR or split at phase boundaries. Hard ordering constraint from spec §7.1/§10: **`HEAVY` routing (Phases 4–5) must not merge ahead of its deployment path (Phase 1).** Recommended: Phases 1–4 in one PR (namespace + helper + marker + workflow all wired together), Phase 5 (rule/template flip that turns routing on) last.

- **Phase 1 — Installer `workflows` namespace** (blocking prereq; own gate `make ci-installer`)
- **Phase 2 — `gate-triage` helper** (pure core + boundary; its own pytest suite)
- **Phase 3 — Config section + `.critical-paths` marker**
- **Phase 4 — `quality-gate` saved workflow**
- **Phase 5 — Rule preamble + shared tier wording** (the switch that activates routing)

## File structure

**New files**
- `src/user/.agents/skills/gate-triage/SKILL.md` — invocation contract (merge-guard-shaped)
- `src/user/.agents/skills/gate-triage/gate_triage.py` — the helper (PEP 723 + `pathspec`)
- `src/user/.agents/skills/gate-triage/gate_triage_test.py` — pytest suite (spec §9 behaviors)
- `src/user/.agents/skills/gate-triage/gate_triage_test.sh` — `*_test.sh` shim (repo gate glob discovers only `*_test.sh`)
- `src/user/.claude/workflows/quality-gate.md` — the saved workflow (see Task 15 for format confirmation)
- `.critical-paths` — repo-root marker (curated pattern list)
- `packages/installer/tests/unit/test_workflows_namespace.py` — staging + deploy + prune tests

**Modified files**
- `packages/installer/src/installer/tools/claude.py:30` — add `"workflows"`
- `packages/installer/src/installer/core/ownership.py:15` — add `"workflows"`
- `packages/installer/src/installer/core/backup.py:24` — add `"workflows"`
- `packages/installer/src/installer/core/merge/registry.py:106` — register workflows fatal
- `packages/installer/tests/unit/test_ownership.py:49` — update pinned tuple
- `src/user/.agents/rules/completion-gate.md` — routing preamble
- `src/user/.agents/INSTRUCTIONS.md.template:123` — three-tier wording in `<verification-checklist>`
- `project-config.toml` — new `[completion-gate]` section

---

## Phase 1 — Installer `workflows` namespace

Blocking prerequisite. Everything here is `packages/installer/` Python; **run `make ci-installer` from the repo root before any push** (ruff check + ruff format --check + mypy --strict + pytest --cov@90% branch + pip-audit + entry-verify). Faster inner loop: `make test-installer`.

### Task 1: Stage + deploy the `workflows` namespace

**Files:**
- Modify: `packages/installer/src/installer/tools/claude.py:29-30`
- Test: `packages/installer/tests/unit/test_workflows_namespace.py` (create)

- [ ] **Step 1: Write the failing staging test**

Model on `tests/unit/test_staging_build_plan.py` (its `_make_repo` + `build_plan` + `assert Path(...) in plan.items` idiom; the `hooks` case at line 74 is the closest twin). Uses the shared `ignore` fixture from `tests/unit/conftest.py`.

```python
# packages/installer/tests/unit/test_workflows_namespace.py
from pathlib import Path

from installer.core.staging import build_plan
from installer.tools.claude import ClaudeAdapter


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    wf = repo / "src" / "user" / ".claude" / "workflows"
    wf.mkdir(parents=True)
    (wf / "quality-gate.md").write_text("# quality-gate workflow\n")
    return repo


def test_workflows_namespace_is_staged(tmp_path, ignore):
    repo = _make_repo(tmp_path)
    plan = build_plan(ClaudeAdapter(), repo_root=repo, ignore=ignore)
    assert Path("workflows/quality-gate.md") in plan.items
```

- [ ] **Step 2: Run it, verify it fails**

Run: `make test-installer` (or `cd packages/installer && uv run pytest tests/unit/test_workflows_namespace.py::test_workflows_namespace_is_staged -v`)
Expected: FAIL — `Path("workflows/quality-gate.md")` not in `plan.items` (namespace not staged).

- [ ] **Step 3: Add `workflows` to the staging tuple**

`packages/installer/src/installer/tools/claude.py:29-30`:
```python
    def scoped_namespaces(self) -> tuple[str, ...]:
        return ("commands", "skills", "agents", "rules", "hooks", "workflows")
```

- [ ] **Step 4: Run it, verify it passes**

Run: same as Step 2. Expected: PASS. `stage_namespace` is generic (walks `source_root/workflows/*`), so no other staging code changes.

- [ ] **Step 5: Add the deploy-to-disk test**

Model on `tests/unit/test_sync_claude.py:21` (`sync(ClaudeAdapter(), ..., home=, io=ScriptedIO())` then assert a file under `home/.claude/`). Assert `quality-gate.md` lands at `home/.claude/workflows/quality-gate.md`. (Follow that file's exact `sync(...)` signature and `ScriptedIO()` construction — mirror it, don't invent args.)

- [ ] **Step 6: Run + commit**

Run: `make test-installer`, expected PASS.
```bash
git add packages/installer/src/installer/tools/claude.py packages/installer/tests/unit/test_workflows_namespace.py
git commit -m "feat(installer): stage and deploy the claude workflows namespace"
```

### Task 2: Prune stale workflows (cleanup on rename/remove)

**Files:**
- Modify: `packages/installer/src/installer/core/ownership.py:15`
- Modify: `packages/installer/tests/unit/test_ownership.py:49`
- Test: `packages/installer/tests/unit/test_workflows_namespace.py` (extend)

- [ ] **Step 1: Write the failing prune test**

Model exactly on `tests/unit/test_receipt_pipeline.py::test_dropped_entry_is_pruned_and_outcome_names_it` (lines 51-79): build a `prior` `Receipt` with a workflow entry, a `plans` dict whose `StagingPlan` drops it, call `prune_pipeline([get_adapter(Tool.CLAUDE)], plans=, prior=, home=, discovered_plugin_names=set(), io=ScriptedIO(interactive=False), auto_yes=True, timestamp=_TS)`, then assert the file is gone and `outcome.pruned_paths == {Path(".claude/workflows/quality-gate.md")}`. Use the `ReceiptEntry(Path(".claude/workflows/quality-gate.md"), "claude", Path(".claude"), "file", sha)` helper shape from that test. Copy its imports/fixtures verbatim.

- [ ] **Step 2: Run it, verify it fails**

Run: `cd packages/installer && uv run pytest tests/unit/test_workflows_namespace.py -k prune -v`
Expected: FAIL — the dropped workflow is neither receipt-tracked nor pruned, so `pruned_paths` is empty (a stale `~/.claude/workflows/quality-gate.md` would survive a source rename/removal — the exact silent-stale-workflow hazard spec §7.1 calls out).

- [ ] **Step 3: Add `workflows` to `PRUNE_NAMESPACES`**

`packages/installer/src/installer/core/ownership.py:15`:
```python
PRUNE_NAMESPACES: tuple[str, ...] = ("commands", "skills", "agents", "rules", "workflows")
```
(Consumed by `is_prunable()` at `ownership.py:21` and `receipt_build.py:41` `entries_from_outcomes` — so this one edit makes workflows both receipt-recorded and prune-eligible.)

- [ ] **Step 4: Fix the constant-pinning test that now breaks**

`tests/unit/test_ownership.py:49-50` pins the exact tuple. Update its expectation:
```python
    assert PRUNE_NAMESPACES == ("commands", "skills", "agents", "rules", "workflows")
```

- [ ] **Step 5: Run both, verify pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_workflows_namespace.py tests/unit/test_ownership.py -v`
Expected: PASS (prune test + updated constant test).

- [ ] **Step 6: Commit**

```bash
git add packages/installer/src/installer/core/ownership.py packages/installer/tests/unit/test_ownership.py packages/installer/tests/unit/test_workflows_namespace.py
git commit -m "feat(installer): prune stale workflows on source rename/removal"
```

### Task 3: Route workflow backups to a sibling dir (consistency)

**Files:**
- Modify: `packages/installer/src/installer/core/backup.py:24`

- [ ] **Step 1: Add `workflows` to `_SCOPED_NAMESPACES`**

Cosmetic-but-consistent: without it a conflicting workflow backs up in-place (`quality-gate.md.backup-<ts>`) instead of to a sibling `workflows-backup/` dir like other namespaces. `backup.py:24`:
```python
_SCOPED_NAMESPACES = frozenset({"commands", "skills", "agents", "rules", "formulas", "workflows"})
```

- [ ] **Step 2: Verify existing backup tests still pass**

The parametrized backup tests (`tests/unit/test_sync.py:382`, `tests/unit/test_backup.py:43`) don't assert the full set, so they stay green. Add `workflows` to their parametrize lists only if you want positive coverage of the sibling-dir routing (optional).
Run: `cd packages/installer && uv run pytest tests/unit/test_backup.py tests/unit/test_sync.py -v` → PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/installer/src/installer/core/backup.py
git commit -m "feat(installer): route workflows namespace backups to a sibling dir"
```

### Task 4: Register a merge strategy for the `workflows` namespace

**Files:**
- Modify: `packages/installer/src/installer/core/merge/registry.py:106`
- Test: `packages/installer/tests/unit/test_workflows_namespace.py` (extend)

- [ ] **Step 1: Write the failing merge-resolution test**

A `.md` workflow classifies as `NAMESPACED_MD`; `default_registry().resolve(NAMESPACED_MD, "workflows")` must return a strategy, not raise. Model the assertion on how `test_merge_registry` (search `tests/unit/` for the registry test) checks `commands`/`skills`.

```python
from installer.core.merge.registry import default_registry
from installer.core.merge.strategies.fatal import FatalStrategy
from installer.core.model import FileKind


def test_workflows_namespace_has_a_merge_strategy():
    strategy = default_registry().resolve(FileKind.NAMESPACED_MD, "workflows")
    assert isinstance(strategy, FatalStrategy)
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd packages/installer && uv run pytest tests/unit/test_workflows_namespace.py -k merge_strategy -v`
Expected: FAIL — `UnknownMergeKeyError` (namespace un-wired). A `.md` workflow collision would raise rather than merge — the latent installer crash this registration closes.

- [ ] **Step 3: Register the strategy**

`packages/installer/src/installer/core/merge/registry.py`, after line 106 (the `agents` fatal registration):
```python
    registry.register(FileKind.NAMESPACED_MD, "workflows", FatalStrategy())
```
Rationale: workflows are single-source (Claude tool root only) and irreconcilable on collision — identical treatment to `commands`/`skills`/`agents`. If Task 15 confirms workflows are a **non-`.md`** format (→ `FileKind.OTHER`, already registered under `None` as `LastWinsSilent`), this registration is inert but harmless; keep it as defense.

- [ ] **Step 4: Run it, verify it passes**

Run: same as Step 2. Expected: PASS.

- [ ] **Step 5: Run the full installer gate + commit**

Run (repo root): `make ci-installer`
Expected: all stages green (lint, format, mypy --strict, pytest --cov ≥90% branch, pip-audit, entry-verify).
```bash
git add packages/installer/src/installer/core/merge/registry.py packages/installer/tests/unit/test_workflows_namespace.py
git commit -m "feat(installer): register fatal merge strategy for the workflows namespace"
```

---

## Phase 2 — `gate-triage` helper

A self-contained script (merge-guard-shaped: skill dir + `.py` + `*_test.py` + `*_test.sh` shim), but the repo's **first** `uv run` + PEP 723 + `pathspec` asset. Pure core over value types; git and filesystem confined to boundary functions. Tests are pytest run via `uv run --with pytest --with pathspec`. Behaviors are spec §9 items 1–30.

### Task 5: Module skeleton, value types, and the test shim

**Files:**
- Create: `src/user/.agents/skills/gate-triage/gate_triage.py`
- Create: `src/user/.agents/skills/gate-triage/gate_triage_test.py`
- Create: `src/user/.agents/skills/gate-triage/gate_triage_test.sh`

- [ ] **Step 1: Write the module header + value types**

Per writing-unit-tests, do NOT write tautology tests for dataclass shapes — types are exercised by the behavior tests that follow. This step lands the contract (spec §4.1).

```python
# src/user/.agents/skills/gate-triage/gate_triage.py
# /// script
# requires-python = ">=3.11"
# dependencies = ["pathspec>=0.12"]
# ///
"""gate-triage: compute the completion-gate tier floor (SKIP/SERIAL/HEAVY).

Pure core over value types; git + filesystem confined to boundary functions
(collect_diff, load_markers, load_config). Invoked by the completion-gate rule:
  uv run gate_triage.py --repo-root <root> --base-ref <default-branch>
Emits a JSON triage payload on stdout (spec §4.2)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import pathspec

DEPENDENCY_FILES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "uv.lock", "requirements.txt", "poetry.lock",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
})

# Gate policy inputs — always HEAVY, independent of any marker pattern (spec §5).
# A change to the gate's own policy is never evaluated under the policy it carries.
POLICY_INPUT_BASENAMES = frozenset({"project-config.toml", ".critical-paths"})


class Tier(str, Enum):
    SKIP = "SKIP"
    SERIAL = "SERIAL"
    HEAVY = "HEAVY"


class FileClass(str, Enum):
    DOCS = "docs"
    CONFIG = "config"
    CODE = "code"


@dataclass(frozen=True)
class ChangedFile:
    path: str
    old_path: str | None
    loc_changed: int
    status: str  # A/M/D/R; untracked (??) → "A"


@dataclass(frozen=True)
class DiffFacts:
    files: tuple[ChangedFile, ...]
    new_deps: bool
    base_ref: str


@dataclass(frozen=True)
class TriageConfig:
    heavy_min_files: int = 8
    heavy_min_loc: int = 400
    heavy_min_subsystems: int = 3
    trivial_max_loc: int = 3  # SKIP ceiling; hard-capped at 20 on load


@dataclass(frozen=True)
class CriticalMarker:
    folder: str  # repo-relative POSIX dir the marker lives in ("" == repo root)
    spec: pathspec.PathSpec


@dataclass(frozen=True)
class CriticalHit:
    path: str
    marker: str   # "<folder>/.critical-paths" or "<policy-input>"
    pattern: str


@dataclass(frozen=True)
class ScaleHint:
    finder_dimensions: int
    refuters: int
    synthesis_effort: str


@dataclass(frozen=True)
class TriageResult:
    tier_floor: Tier
    files: int
    loc_changed: int
    subsystems: int
    new_deps: bool
    file_classes: tuple[str, ...]
    critical_path_hits: tuple[str, ...]
    scale_hint: ScaleHint
```

- [ ] **Step 2: Write the test-file header + shim**

`gate_triage_test.py` header (imports the module by path-adjacent import):
```python
# src/user/.agents/skills/gate-triage/gate_triage_test.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gate_triage as gt  # noqa: E402
```

`gate_triage_test.sh` (mirrors merge-guard's shim; the repo `[gates].test` glob discovers only `*_test.sh`):
```bash
#!/usr/bin/env bash
# Smoke-runs the gate-triage pytest suite via uv (PEP 723 deps + pytest).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --with pytest --with "pathspec>=0.12" python -m pytest "$HERE/gate_triage_test.py" -v
```

- [ ] **Step 3: Make the shim executable + smoke it**

Run: `chmod +x src/user/.agents/skills/gate-triage/gate_triage_test.sh && ./src/user/.agents/skills/gate-triage/gate_triage_test.sh`
Expected: pytest runs and reports "no tests ran" (or collects zero) — proves `uv` resolves `pathspec` + `pytest` and the module imports.

- [ ] **Step 4: Commit**

```bash
git add src/user/.agents/skills/gate-triage/
git commit -m "feat(gate-triage): module skeleton, value types, and test shim"
```

### Task 6: `load_config` (boundary — validate, fail-closed to defaults)

**Files:**
- Modify: `gate_triage.py` (add `load_config`)
- Test: `gate_triage_test.py` (spec §9 items 18–22)

- [ ] **Step 1: Write the failing tests**

```python
def _write_cfg(tmp_path, body: str) -> Path:
    (tmp_path / "project-config.toml").write_text(body)
    return tmp_path


def test_config_overrides_replace_defaults(tmp_path):  # §9.18
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_files = 5\n")
    assert gt.load_config(root).heavy_min_files == 5


def test_absent_section_yields_defaults(tmp_path):  # §9.18
    root = _write_cfg(tmp_path, "[project]\nname = 'x'\n")
    assert gt.load_config(root) == gt.TriageConfig()


def test_trivial_max_loc_clamped_to_20(tmp_path):  # §9.19
    root = _write_cfg(tmp_path, "[completion-gate]\ntrivial_max_loc = 999\n")
    assert gt.load_config(root).trivial_max_loc == 20


def test_heavy_min_loc_below_trivial_max_rejected(tmp_path):  # §9.20
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_loc = 2\ntrivial_max_loc = 3\n")
    assert gt.load_config(root) == gt.TriageConfig()  # nonsensical ordering → defaults


def test_bad_types_fall_back_to_defaults(tmp_path):  # §9.21
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_files = -4\n")
    assert gt.load_config(root) == gt.TriageConfig()


def test_unknown_key_ignored_known_kept(tmp_path):  # §9.22
    root = _write_cfg(tmp_path, "[completion-gate]\nheavy_min_files = 6\nbogus = 1\n")
    assert gt.load_config(root).heavy_min_files == 6


def test_absent_file_yields_defaults(tmp_path):  # §9.18
    assert gt.load_config(tmp_path) == gt.TriageConfig()
```

- [ ] **Step 2: Run, verify fail** (`AttributeError: module has no attribute 'load_config'`).

Run: `./…/gate_triage_test.sh` (or `cd` into the dir and `uv run --with pytest --with pathspec python -m pytest gate_triage_test.py -k config -v`).

- [ ] **Step 3: Implement `load_config`**

```python
def load_config(repo_root: Path) -> TriageConfig:
    """Boundary: read [completion-gate] from project-config.toml. Config decides
    whether review runs, so it is validated, not merely parsed. ANY failure,
    absent section, or absent file → defaults. Never fails open to 'no gate'."""
    default = TriageConfig()
    path = repo_root / "project-config.toml"
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return default
    section = data.get("completion-gate")
    if not isinstance(section, dict):
        return default
    fields = {f: getattr(default, f) for f in
              ("heavy_min_files", "heavy_min_loc", "heavy_min_subsystems", "trivial_max_loc")}
    for key, val in section.items():
        if key not in fields:
            continue  # unknown keys ignored
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            return default  # bad type/negative → fail closed
        fields[key] = val
    fields["trivial_max_loc"] = min(fields["trivial_max_loc"], 20)  # hard cap
    if fields["heavy_min_loc"] < fields["trivial_max_loc"]:
        return default  # nonsensical ordering → fail closed
    return TriageConfig(**fields)
```

- [ ] **Step 4: Run, verify pass.** Then **commit**: `git commit -am "feat(gate-triage): validated fail-closed config loading"`

### Task 7: `classify_file` (diagnostic classification)

**Files:** `gate_triage.py` (+`classify_file`), `gate_triage_test.py` (spec §9 item 10)

- [ ] **Step 1: Failing test**

```python
import pytest

@pytest.mark.parametrize("path,expected", [
    ("README.md", gt.FileClass.DOCS), ("a.rst", gt.FileClass.DOCS),
    ("cfg.toml", gt.FileClass.CONFIG), ("s.yaml", gt.FileClass.CONFIG),
    (".gitignore", gt.FileClass.CONFIG),  # extensionless dotfile
    ("main.py", gt.FileClass.CODE), ("run.sh", gt.FileClass.CODE),
    ("Makefile", gt.FileClass.CODE),  # unknown/no ext → CODE (fail toward scrutiny)
])
def test_classify_file(path, expected):  # §9.10
    assert gt.classify_file(path) == expected
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**

```python
_DOCS_EXT = {".md", ".rst", ".txt", ".adoc"}
_CONFIG_EXT = {".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


def classify_file(path: str) -> FileClass:
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    if suffix in _DOCS_EXT:
        return FileClass.DOCS
    if suffix in _CONFIG_EXT:
        return FileClass.CONFIG
    if suffix == "" and name.startswith("."):
        return FileClass.CONFIG  # extensionless dotfile
    return FileClass.CODE  # unknown/missing ext → CODE
```

- [ ] **Step 4: Run, pass. Commit** `git commit -am "feat(gate-triage): diagnostic file classification"`

### Task 8: `critical_hits` (subtree-scoped marker matching + policy inputs)

**Files:** `gate_triage.py` (+`critical_hits`, +`_hit_for`), `gate_triage_test.py` (spec §9 items 11–16)

- [ ] **Step 1: Failing tests** (pure, over constructed markers)

```python
def _marker(folder: str, *patterns: str) -> gt.CriticalMarker:
    spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
    return gt.CriticalMarker(folder=folder, spec=spec)


def _cf(path, status="M", old_path=None, loc=1):
    return gt.ChangedFile(path=path, old_path=old_path, loc_changed=loc, status=status)


def test_subtree_scoping_and_anchoring():  # §9.11
    m = _marker("src/auth", "*.py")
    hits = gt.critical_hits((_cf("src/auth/token.py"), _cf("src/auth/sub/x.py"),
                             _cf("src/other/token.py")), (m,))
    hit_paths = {h.path for h in hits}
    assert hit_paths == {"src/auth/token.py", "src/auth/sub/x.py"}


def test_nested_and_ancestor_markers_union():  # §9.12
    root = _marker("", "src/**")
    nested = _marker("src/auth", "*.py")
    hits = gt.critical_hits((_cf("docs/x.md"), _cf("src/auth/a.py")), (root, nested))
    assert {h.path for h in hits} == {"src/auth/a.py"}  # a.py hit; both markers union, no shadow


def test_negation_within_a_marker():  # §9.13
    m = _marker("src", "**/*.py", "!**/generated.py")
    hits = gt.critical_hits((_cf("src/a.py"), _cf("src/generated.py")), (m,))
    assert {h.path for h in hits} == {"src/a.py"}


def test_hit_carries_provenance():  # §9.14
    m = _marker("src/auth", "*.py")
    (hit,) = gt.critical_hits((_cf("src/auth/token.py"),), (m,))
    assert hit.marker == "src/auth/.critical-paths" and hit.pattern  # non-empty


def test_rename_out_and_into_marked_subtree():  # §9.15
    m = _marker("src/auth", "*.py")
    out = _cf("src/other/token.py", status="R", old_path="src/auth/token.py")
    into = _cf("src/auth/new.py", status="R", old_path="src/other/new.py")
    within = _cf("src/auth/b.py", status="R", old_path="src/auth/a.py")
    hits = gt.critical_hits((out, into, within), (m,))
    assert len(hits) == 3  # out (old_path), into (path), within (one hit, not two)
    assert sum(1 for h in hits if h.path == "src/auth/b.py") == 1


def test_delete_from_marked_subtree():  # §9.16
    m = _marker("src/auth", "*.py")
    (hit,) = gt.critical_hits((_cf("src/auth/gone.py", status="D"),), (m,))
    assert hit.path == "src/auth/gone.py"


def test_policy_input_is_always_a_hit_without_markers():  # §9.8, §9.9
    hits = gt.critical_hits((_cf("project-config.toml"), _cf("src/x/.critical-paths")), ())
    assert {h.path for h in hits} == {"project-config.toml", "src/x/.critical-paths"}
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**

```python
def _rel_to_marker(marker_folder: str, path: str) -> str | None:
    """Path relative to the marker's folder, or None if outside its subtree."""
    if marker_folder == "":
        return path
    prefix = marker_folder + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def _match_markers(candidate: str, markers: tuple[CriticalMarker, ...]) -> tuple[str, str] | None:
    """Return (marker_label, matched_pattern) for the first matching marker, else None."""
    for m in markers:
        rel = _rel_to_marker(m.folder, candidate)
        if rel is None:
            continue
        if m.spec.match_file(rel):
            label = (m.folder + "/.critical-paths").lstrip("/") or ".critical-paths"
            matched = next((p.pattern for p in m.spec.patterns
                            if p.include and p.match_file(rel)), "*")
            return (label, matched)
    return None


def critical_hits(files: tuple[ChangedFile, ...],
                  markers: tuple[CriticalMarker, ...]) -> tuple[CriticalHit, ...]:
    hits: list[CriticalHit] = []
    for f in files:
        candidates = [f.path] + ([f.old_path] if f.status == "R" and f.old_path else [])
        matched_here = False
        for cand in candidates:
            if Path(cand).name in POLICY_INPUT_BASENAMES:  # §5 hardcoded policy inputs
                hits.append(CriticalHit(path=cand, marker=Path(cand).name, pattern="<policy-input>"))
                matched_here = True
                break
            found = _match_markers(cand, markers)
            if found:
                hits.append(CriticalHit(path=f.path, marker=found[0], pattern=found[1]))
                matched_here = True
                break
        _ = matched_here
    return tuple(hits)
```
(Note: the rename-within case yields one hit because the loop breaks on the first matching candidate. Confirm the `pathspec` `.patterns[*].pattern`/`.include` attribute names against the installed `pathspec` version during green — adjust the provenance extraction if the API differs; the behavior assertions, not the attribute names, are the contract.)

- [ ] **Step 4: Run, pass. Commit** `git commit -am "feat(gate-triage): subtree-scoped critical-path matching with policy inputs"`

### Task 9: `compute_tier` (the tier floor logic)

**Files:** `gate_triage.py` (+`_subsystems`, +`compute_tier`), `gate_triage_test.py` (spec §9 items 1–9)

- [ ] **Step 1: Failing tests**

```python
def _facts(*files, new_deps=False):
    return gt.DiffFacts(files=tuple(files), new_deps=new_deps, base_ref="main")

CFG = gt.TriageConfig()  # files=8, loc=400, subsystems=3, trivial=3


def test_single_trivial_file_is_skip():  # §9.1
    assert gt.compute_tier(_facts(_cf("a.py", loc=3)), (), CFG) == gt.Tier.SKIP
    assert gt.compute_tier(_facts(_cf("a.py", loc=4)), (), CFG) == gt.Tier.SERIAL


def test_critical_hit_beats_skip():  # §9.2, §9.7
    hit = (gt.CriticalHit("a.py", "src/.critical-paths", "*.py"),)
    assert gt.compute_tier(_facts(_cf("a.py", loc=1)), hit, CFG) == gt.Tier.HEAVY


def test_two_trivial_files_not_skip():  # §9.3
    assert gt.compute_tier(_facts(_cf("a.py", loc=1), _cf("b.py", loc=1)), (), CFG) == gt.Tier.SERIAL


def test_mixed_small_multifile_is_serial():  # §9.4
    assert gt.compute_tier(_facts(_cf("a.md", loc=5), _cf("b.py", loc=5)), (), CFG) == gt.Tier.SERIAL


def test_each_quant_threshold_trips_heavy_at_boundary():  # §9.5
    files_min = tuple(_cf(f"d{i}/f.py", loc=1) for i in range(8))  # 8 files, 8 subsystems
    assert gt.compute_tier(_facts(*files_min), (), CFG) == gt.Tier.HEAVY
    loc_min = (_cf("a.py", loc=400),)
    assert gt.compute_tier(_facts(*loc_min), (), CFG) == gt.Tier.HEAVY
    subs_min = tuple(_cf(f"d{i}/f.py", loc=1) for i in range(3))  # 3 subsystems
    assert gt.compute_tier(_facts(*subs_min), (), CFG) == gt.Tier.HEAVY


def test_new_deps_trips_heavy():  # §9.6
    assert gt.compute_tier(_facts(_cf("pyproject.toml", loc=1), new_deps=True), (), CFG) == gt.Tier.HEAVY
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**

```python
def _subsystems(files: tuple[ChangedFile, ...]) -> int:
    """Distinct top-level dir touched; repo-root files and dotfile dirs each count once."""
    tops = set()
    for f in files:
        parts = Path(f.path).parts
        tops.add(parts[0] if len(parts) > 1 else "<root>")
    return len(tops)


def compute_tier(facts: DiffFacts, hits: tuple[CriticalHit, ...], config: TriageConfig) -> Tier:
    if hits:
        return Tier.HEAVY  # critical hit — unconditional, overrides SKIP
    files = facts.files
    loc = sum(f.loc_changed for f in files)
    if (len(files) >= config.heavy_min_files
            or loc >= config.heavy_min_loc
            or _subsystems(files) >= config.heavy_min_subsystems
            or facts.new_deps):
        return Tier.HEAVY
    if len(files) == 1 and loc <= config.trivial_max_loc:
        return Tier.SKIP
    return Tier.SERIAL
```
(§9.8/§9.9 — policy-input files as HEAVY — are covered end-to-end because `critical_hits` produces a hit for them, and `compute_tier` returns HEAVY on any hit. Task 12 asserts the full path through `triage()`.)

- [ ] **Step 4: Run, pass. Commit** `git commit -am "feat(gate-triage): tier floor logic"`

### Task 10: `compute_scale_hint`

**Files:** `gate_triage.py` (+`compute_scale_hint`), `gate_triage_test.py` (spec §9 item 17)

- [ ] **Step 1: Failing tests** — bucket boundaries → mapped tuples; monotonic (a strictly larger diff never gets a smaller fleet). Buckets from spec §7: small (3,2,high) / medium (4,2,high) / large (6,3,xhigh).

```python
def test_scale_hint_buckets():  # §9.17
    small = gt.compute_scale_hint(_facts(_cf("a.py", loc=10)))
    large = gt.compute_scale_hint(_facts(*[_cf(f"d{i}/f.py", loc=100) for i in range(9)]))
    assert (small.finder_dimensions, small.refuters, small.synthesis_effort) == (3, 2, "high")
    assert (large.finder_dimensions, large.refuters, large.synthesis_effort) == (6, 3, "xhigh")
    assert large.finder_dimensions >= small.finder_dimensions  # monotone
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Implement** — map a size score (files/loc/subsystems) to the three buckets. Small = below all heavy thresholds; medium = one heavy threshold; large = two+ heavy thresholds or new_deps. Keep it a pure function of `DiffFacts` + default thresholds. (Choose the exact bucket predicate to satisfy monotonicity; document the mapping in a docstring.)
- [ ] **Step 4: Run, pass. Commit** `git commit -am "feat(gate-triage): scale-hint bucketing"`

### Task 11: `triage` composition + CLI/JSON output

**Files:** `gate_triage.py` (+`triage`, +`_result_to_json`, +`main`), `gate_triage_test.py`

- [ ] **Step 1: Failing test** — `triage(facts, markers, config)` returns a `TriageResult`; JSON shape matches spec §4.2.

```python
def test_triage_composes_and_serializes():
    facts = _facts(_cf("src/auth/token.py", loc=1))
    m = _marker("src/auth", "*.py")
    result = gt.triage(facts, (m,), CFG)
    assert result.tier_floor == gt.Tier.HEAVY
    payload = json.loads(gt._result_to_json(result))
    assert payload["tier_floor"] == "HEAVY"
    assert payload["critical_path_hits"] == ["src/auth/token.py ← src/auth/.critical-paths:*.py"]
    assert set(payload["scale_hint"]) == {"finder_dimensions", "refuters", "synthesis_effort"}
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Implement** `triage` (pure: `critical_hits` → `compute_tier` → `compute_scale_hint` → assemble `TriageResult`), `_result_to_json` (hit strings as `"<path> ← <marker>:<pattern>"`), and `main` (argparse `--repo-root`, `--base-ref`; calls the boundary functions then `triage`; prints JSON). Default `--base-ref` resolves the repo default branch.
- [ ] **Step 4: Run, pass. Commit** `git commit -am "feat(gate-triage): triage composition and JSON CLI"`

### Task 12: Boundary functions — `collect_diff` + `load_markers` (integration)

**Files:** `gate_triage.py` (+`collect_diff`, +`load_markers`), `gate_triage_test.py` (spec §9 items 23–29, against a temp git repo)

- [ ] **Step 1: Failing integration tests** — build a temp git repo with `subprocess`, craft a branch off `main`, and assert. Cover: committed diff file set + LOC + rename `old_path`/`path` (§9.23); staged + unstaged + committed dedupe (§9.24); untracked `??` file → status "A", full-line-count LOC, participates in matching (§9.25); dep manifest present only as untracked/unstaged → `new_deps: true` incl. nested path (§9.26); `load_markers` discovers nested markers and anchors patterns (§9.27); committed rename-out then unstaged edit at new path keeps `old_path` + still hits (§9.28); one-line `project-config.toml` change → HEAVY end-to-end with no marker present (§9.29).

```python
import subprocess

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

def _init_repo(tmp_path):
    repo = tmp_path / "r"; repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n"); _git(repo, "add", "."); _git(repo, "commit", "-m", "seed")
    return repo

def test_collect_diff_untracked_file(tmp_path):  # §9.25
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feat")
    (repo / "new.py").write_text("a\nb\nc\n")  # untracked, 3 lines
    facts = gt.collect_diff(repo, "main")
    nf = next(f for f in facts.files if f.path == "new.py")
    assert nf.status == "A" and nf.loc_changed == 3
```
(Write the remaining §9.23–29 cases following this fixture idiom — each is one crafted git state + one assertion. Do not stub git; these are real-subprocess integration tests, few in number, per spec §9.)

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `collect_diff`** — shell `git merge-base`, `git diff --numstat <base>...HEAD`, `git diff --numstat` (unstaged) + `--cached` (staged), and `git status --porcelain=v1 --untracked-files=all`; parse into `ChangedFile`s; union + evidence-preserving dedupe by path (working-tree `loc_changed`/`status` win, but retain `old_path` if either committed or working-tree source reports a rename — spec §4.3); set `new_deps` = any `Path(f.path).name in DEPENDENCY_FILES`. **Implement `load_markers`** — walk for `.critical-paths` files, build `CriticalMarker(folder=<rel posix dir>, spec=PathSpec.from_lines("gitwildmatch", lines))`.
- [ ] **Step 4: Run, pass. Full shim run:** `./…/gate_triage_test.sh` → all green. **Commit** `git commit -am "feat(gate-triage): git + marker boundary collection"`

### Task 13: `SKILL.md` invocation contract

**Files:** Create `src/user/.agents/skills/gate-triage/SKILL.md`

- [ ] **Step 1:** Write `SKILL.md` (merge-guard-shaped): purpose, the `uv run gate_triage.py --repo-root <root> --base-ref <default-branch>` invocation, the JSON output contract (spec §4.2), and the exit-code contract. No code logic — documentation only. **Commit** `git commit -m "docs(gate-triage): skill invocation contract"`

---

## Phase 3 — Config section + `.critical-paths` marker

### Task 14: Add `[completion-gate]` to `project-config.toml` and seed the root marker

**Files:**
- Modify: `project-config.toml`
- Create: `.critical-paths` (repo root)
- Test: `gate_triage_test.py` (spec §9 item 30 — repo acceptance)

- [ ] **Step 1: Write the failing repo-acceptance test** (§9.30 — effective coverage of the *shipped* root marker, not its existence)

```python
def test_repo_root_marker_covers_load_bearing_surface(tmp_path):  # §9.30
    repo_root = Path(__file__).resolve().parents[4]  # worktree root
    markers = gt.load_markers(repo_root)
    reps = ["src/user/.agents/skills/gate-triage/SKILL.md",
            "src/user/.claude/AGENTS.md.template",
            "packages/installer/src/installer/cli.py",
            "scripts/install.sh", ".github/workflows/ci.yml", "Makefile"]
    for rel in reps:
        hits = gt.critical_hits((_cf(rel),), markers)
        assert hits, f"{rel} not covered by shipped root .critical-paths"
```

- [ ] **Step 2: Run, verify fail** (no `.critical-paths` yet → empty markers → no hits).
- [ ] **Step 3: Create `.critical-paths`** at repo root (spec §5 curated list):

```gitignore
# .critical-paths — force HEAVY completion gate on load-bearing changes (spec §5).
# gitignore syntax, anchored to repo root. Claude-only; other tools use the serial gate.
src/**
packages/**
scripts/**
.github/**
Makefile
```

- [ ] **Step 4: Add `[completion-gate]` to `project-config.toml`** (mirror the `[merge-policy]` `# Read by:` comment convention):

```toml
[completion-gate]
# Read by: src/user/.agents/skills/gate-triage/gate_triage.py (load_config)
# All optional; omitted keys use defaults. Invalid values fail closed to defaults.
heavy_min_files    = 8
heavy_min_loc      = 400
heavy_min_subsystems = 3
trivial_max_loc    = 3   # SKIP ceiling; hard-capped at 20
```

- [ ] **Step 5: Run, verify pass.** **Commit**
```bash
git add .critical-paths project-config.toml src/user/.agents/skills/gate-triage/gate_triage_test.py
git commit -m "feat(gate): seed repo-root .critical-paths and [completion-gate] config"
```

---

## Phase 4 — `quality-gate` saved workflow

### Task 15: Author the `quality-gate` workflow (interim capped-round loop)

**Files:** Create `src/user/.claude/workflows/quality-gate.md`

- [ ] **Step 1: Confirm the saved-workflow on-disk format.** No in-repo example exists. Verify against Claude Code's workflow loader whether `~/.claude/workflows/` entries are `.md` (frontmatter + JS script) or a bare script file, and the required filename↔`meta.name` relationship. Use the claude-code-guide agent or Claude Code docs. **If the format is not `.md`,** change the file extension here and in Task 1's fixtures, and note that Task 4's `NAMESPACED_MD` registration becomes inert (file classifies as `OTHER`) — harmless, keep it.

- [ ] **Step 2: Author the workflow script** implementing spec §7, interim convergence per the decision record (`2026-07-03-adversarial-loop-convergence-decision.md`):
  - `export const meta = {...}` — `name: "quality-gate"`, phases: Find, Verify, Synthesize.
  - Consume `args` = the triage JSON (`scale_hint` → finder_dimensions / refuters / synthesis_effort).
  - **Finder dimensions fold in simplify's axes** (reuse, quality, efficiency) as dimensions — the equivalence mapping that resolves the run-both duplication; simplify is NOT separately run on this path.
  - Adversarial refuter panels (width = `scale_hint.refuters`), **dedup-vs-seen across rounds**, synthesis at `synthesis_effort`.
  - **Interim convergence:** a hard round cap (default 3–5) + dedup-vs-seen; on exit emit a **dual-signal residual-risk report** — state whether the exit was acceptance (clean at floor) or termination (cap hit), never a bare "clean." (The full discipline replaces this when `vaac.2` lands.)
  - Hardening (spec §7): bounded StructuredOutput report fields, one-repair-attempt-then-abort chains, model/effort tiering, `resumeFromRunId` recovery documented in the header comment.
  - Apply-vs-flag bright line preserved in the fix wave.

- [ ] **Step 3: Static-validate the script** — confirm it parses as the workflow format (JS syntax; `meta` is a pure literal; phase titles match `meta.phases`). Do NOT execute it against real changes here (that's live-gate territory). **Commit**
```bash
git add src/user/.claude/workflows/quality-gate.md
git commit -m "feat(quality-gate): interim capped-round HEAVY workflow"
```

---

## Phase 5 — Rule preamble + shared tier wording (activates routing)

This phase flips routing on. Land it last.

### Task 16: Add the three-tier wording to the shared verification-checklist

**Files:** Modify `src/user/.agents/INSTRUCTIONS.md.template` (block at lines 121-143)

- [ ] **Step 1:** Insert the tier contract into the `<verification-checklist>` block, attached to the MANDATORY sentence (line 123). Add SKIP/SERIAL/HEAVY tier wording per spec §3 (one contract, three tiers, routed at gate time; `SKIP` is a size bound not a file-type bound; step 5 non-substitutable under every tier; `HEAVY` is Claude-only and degrades to `SERIAL` elsewhere). This block flattens verbatim into all four tools via DYNAMIC-INCLUDE — edit once, here. Keep tool-agnostic (no "Workflow" specifics — those live in the Claude rule).
- [ ] **Step 2:** Sanity-check no file-path citations leak into the shared block (they'd break on flatten). **Commit** `git commit -am "feat(gate): add three-tier routing to shared verification-checklist"`

### Task 17: Add the routing preamble to the completion-gate rule

**Files:** Modify `src/user/.agents/rules/completion-gate.md`

- [ ] **Step 1:** Insert the 4-step routing preamble between the "run in order" preamble sentence and step `1.` (spec §8):
  1. Run gate-triage (`uv run <gate-triage skill dir>/gate_triage.py --repo-root . --base-ref <default branch>`) and **capture its JSON payload** — tier floor, `scale_hint`, and `critical_path_hits`. Later steps refer to this as "the triage JSON."
  2. Apply the risk-class list (escalate-only): security/auth, concurrency/locking, public API/contract, data migration/schema, cross-subsystem architecture (spec §6). A hit raises the floor to `HEAVY`; it can never lower it.
  3. Announce one line (tier, driving facts, estimated `HEAVY` cost). Do not wait for approval.
  4. Route per the resolved tier, **passing the triage JSON through**:
     - `SKIP` → run **step 5 only** (verify-checklist mechanical evidence where tests/build apply); skip steps 1–4.
     - `SERIAL` → run the existing steps 1–5 **unchanged**.
     - `HEAVY` (Claude only) → invoke `Workflow({name: "quality-gate", args: <the triage JSON from step 1>})` **in place of steps 1–4**, then run step 5 after. Passing the triage JSON as `args` is **required, not optional**: the workflow sizes its fleet from `scale_hint` inside it — invoke it without `args` and it launches at default scale, silently defeating scale-to-the-diff. Step 5 (verify-checklist) still runs and is **non-substitutable**.
     - `HEAVY` **unavailable** (no Workflow harness — Codex/Gemini/OpenCode) → fall back to `SERIAL`.
  Leave the existing serial steps 1–5, subagent-dispatch rules, HARD STOP delivery sequence, and merge-authorization language **unchanged** (spec §8). The preamble only routes into them.
- [ ] **Step 2:** Verify the risk-class list and gate-triage invocation reference the skill by concept/name, not a project-internal file path (survives flatten). **Commit** `git commit -am "feat(gate): add routing preamble to completion-gate rule"`

---

## Self-review

**Spec coverage** — every spec section maps to a task:
- §2 tier table → Tasks 9, 16 (wording), 17 (routing). §3 tier contract → Task 16. §4 gate-triage contract → Tasks 5–12. §4.2 output → Task 11. §4.3 tier/dedupe/rename logic → Tasks 8, 9, 12. §5 `.critical-paths` + policy-input hardcoding → Tasks 8, 14. §6 risk-class list → Task 17. §7 workflow → Task 15. §7.1 installer → Phase 1. §8 rule changes → Task 17. §9 test plan (items 1–31) → Tasks 6–14 (mapped inline). §10 consequences (blocking prereqs) → phase ordering. §11 options → n/a (decision record).
- Test items 1–30 → Tasks 6 (18–22), 7 (10), 8 (11–16), 9 (1–9), 10 (17), 11, 12 (23–29), 14 (30). Item 31 (installer prune) → Task 2. **All 31 covered.**

**Placeholder scan** — Task 10 (scale-hint bucket predicate) and Task 15 (workflow authoring + format confirmation) are the two intentional judgment points; both carry concrete constraints (bucket tuples, monotonicity; the spec §7 checklist) rather than "TBD." Task 15 Step 1 is a genuine external-unknown verification, not a deferred decision. No "TODO/implement later" left.

**Type consistency** — `ChangedFile`/`DiffFacts`/`TriageConfig`/`Tier`/`FileClass`/`CriticalMarker`/`CriticalHit`/`ScaleHint`/`TriageResult` defined in Task 5 and used consistently (`compute_tier(facts, hits, config)`, `critical_hits(files, markers)`, `triage(facts, markers, config)`, `compute_scale_hint(facts)`) across Tasks 6–12. Installer touch-points cite verified line numbers.

**Ordering** — Phase 1 (deployment) precedes Phases 4–5 (routing activation), honoring spec §7.1/§10's "HEAVY must not merge ahead of its deployment path." The `[completion-gate]` config (Task 14) lands before the rule reads it (Task 17).
