# S2 — Project-Scoped Install Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking. All paths are relative to the repo root `packages/installer/` unless absolute. Run the gate with `make ci-installer` from the repo root.

**Goal:** Add project-scoped install to the installer: `--project <path>` binds the project scope for a run, staging tool-scoped content under `<project>/.claude/` and a tool-agnostic `src/kits/` tree (v1: the beads `PRIME.md` kit) under the project root, tracked by a project-local receipt.

**Architecture:** Approach A — kits ride the S1 resolver for *selection* (via a nullable `UniverseRef.tool`) but materialize, record, and prune through the *existing plugin-route machinery* (a kit is the project-scope mirror of a plugin route, owner `kit:<name>`). The resolver is wired into `cli._run` after `stage_and_transform`; a `--project` run forks to a project tail (filtered `sync_plan` for tool refs + kit routes for kit refs) under a project-local receipt lock, and never runs the user tool sync or user plugin routes. The user run keeps byte-identical output, guarded by a parity golden.

**Tech Stack:** Python 3.12, uv, pytest (`--cov` branch ≥90%), mypy `--strict`, ruff. Source: `packages/installer/src/installer/`. Tests: `packages/installer/tests/unit/`.

**Spec:** `docs/specs/2026-07-12-s2-project-scoped-install-design.md` (committed `9814a9a`, RALF-converged PASS).

---

## Mechanism note (read before Task 8)

The spec's §6.2 sketched "`record_receipt` gains a kit-outcomes input." This plan uses the **cleaner realization**: because a kit is plugin-route-shaped, kit writes flow through the **existing** `plugin_outcomes` channel keyed by owner `kit:<name>`, and kit installs run through the **existing** `install_plugin_routes` / `prune_pipeline` `plugins` slot via a tiny `PluginAdapter`-conforming wrapper (`_KitRouteAdapter`). This needs **no signature change** to `record_receipt`, `install_plugin_routes`, or `prune_pipeline` — the same observable behavior (a `kit:<name>`-owned, `.beads`-rooted project receipt entry that prunes correctly). This is a deviation from the spec's *stated mechanism* (not its behavior) and is flagged for the plan-review gate.

`PluginAdapter` is a `@runtime_checkable Protocol` (`plugins/base.py:30-63`): `name` (property) · `source_path` (property) · `is_detected(home) -> bool` · `routes(home) -> tuple[PluginRoute, ...]`. A kit wrapper conforms structurally.

---

## File Structure

**New files:**
- `src/installer/core/kits.py` — kit staging: `stage_kits`, `kit_universe`, `kit_routes`, `kit_name_of`, and the `_KitRouteAdapter` plugin-wrapper. One responsibility: turn `src/kits/<kit>/**` into resolver refs + plugin-route adapters.
- `src/kits/beads/.beads/PRIME.md` — the beads kit content (v1's only kit file).
- `tests/unit/test_kits.py` — unit tests for `core/kits.py`.
- `tests/unit/test_cli_project.py` — integration tests for `--project` runs.

**Modified files:**
- `src/installer/core/profiles.py` — nullable `UniverseRef.tool`; sort-key fix (`:447`).
- `profiles.toml` (repo root) — add `kits/** = project` scope + `[profiles.beads-kit]`.
- `src/installer/tools/base.py` — add `project_namespaces()` to the `ToolAdapter` Protocol.
- `src/installer/tools/{claude,codex,gemini,opencode}.py` — implement `project_namespaces()`.
- `src/installer/cli.py` — `--project`/`--profiles` flags; the project-run fork; resolver-on for user runs; detection suggestion; dump-stage kit rendering.
- `src/installer/core/config.py` — project profile-set persistence read/write (`project-config.toml [install]`).
- `tests/unit/test_profiles.py` — coverage-guard test; nullable-ref sort test.

---

## Phase 0 — Foundations (no user-visible behavior change)

### Task 1: Nullable `UniverseRef.tool` + sort-key fix

**Files:**
- Modify: `src/installer/core/profiles.py` (`UniverseRef` ~:221; `resolve` sort key `:447`)
- Test: `tests/unit/test_profiles.py`

- [ ] **Step 1: Write the failing test**

The test must drive the real `resolve()` sort key (`profiles.py:447`) with a `tool=None` ref — not reimplement the sort inline — so it genuinely goes red on the unfixed line. Use a self-contained synthetic manifest (Task 1 runs before the `profiles.toml` edits in Task 2, so do not depend on the shipped manifest):

```python
# tests/unit/test_profiles.py
from pathlib import Path
from installer.core.profiles import Manifest, Profile, IncludeEntry, UniverseRef, resolve, Scope
from installer.core.model import Tool

def test_resolve_sorts_tool_none_kit_ref_without_crash() -> None:
    kit_ref = UniverseRef(tool=None, dest_relpath=Path(".beads/PRIME.md"))
    tool_ref = UniverseRef(tool=Tool.CLAUDE, dest_relpath=Path("skills/x"))
    universe = {"kits/beads/PRIME": [kit_ref], "skills/x": [tool_ref]}
    manifest = Manifest(
        schema=1,
        scopes={"kits/**": Scope.PROJECT, "skills/**": Scope.PROJECT},
        profiles={"p": Profile(name="p", includes=(IncludeEntry(selector="**", scope=None),), excludes=())},
    )
    resolved = resolve(manifest, ("p",), universe, bound_scopes=frozenset({Scope.PROJECT}))
    proj = resolved.included[Scope.PROJECT]
    assert proj[0].tool is None          # tool=None sorts first (key "" < "claude")
    assert kit_ref in proj and tool_ref in proj
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/installer && uv run pytest tests/unit/test_profiles.py::test_resolve_sorts_tool_none_kit_ref_without_crash -v`
Expected: FAIL — `resolve()`'s final sort at `profiles.py:447` reads `r.tool.value`, raising `AttributeError: 'NoneType' object has no attribute 'value'` on the kit ref.

- [ ] **Step 3: Make the change**

In `src/installer/core/profiles.py`, change the `UniverseRef` dataclass field:

```python
@dataclass(frozen=True, slots=True)
class UniverseRef:
    tool: Tool | None   # None ⇒ tool-agnostic kit ref; materializes at the project root
    dest_relpath: Path
```

And change the `resolve()` final sort key (currently at ~:447):

```python
    final_included = {
        scope: tuple(
            sorted(
                refs,
                key=lambda r: (r.tool.value if r.tool is not None else "", r.dest_relpath.as_posix()),
            )
        )
        for scope, refs in included.items()
    }
```

- [ ] **Step 4: Run test + full profiles suite to verify pass + no regression**

Run: `cd packages/installer && uv run pytest tests/unit/test_profiles.py -v`
Expected: PASS (including the existing golden/anti-drift tests — the sort change is a no-op for tool refs).

- [ ] **Step 5: Commit**

```bash
git add src/installer/core/profiles.py tests/unit/test_profiles.py
git commit -m "feat(installer): allow tool-agnostic UniverseRef (nullable tool) for kits"
```

---

### Task 2: Manifest — `kits/** = project` scope + `beads-kit` profile + coverage guard

**Files:**
- Modify: `profiles.toml` (repo root)
- Test: `tests/unit/test_profiles.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_profiles.py
from installer.core import namespaces

def test_beads_kit_profile_exists_and_scopes_kits_to_project() -> None:
    manifest = load_manifest(Path(__file__).resolve().parents[4] / "profiles.toml")
    assert "beads-kit" in manifest.profiles
    # The kits/** scope default routes to project.
    assert any(sel == "kits/**" and scope is Scope.PROJECT for sel, scope in manifest.scopes.items())

def test_scopes_cover_universe_eligible_namespaces() -> None:
    # Guard: every STAGED namespace (TOOL_SCOPED ∪ SHARED) plus the synthetic
    # instructions/settings must have a [scopes] match, or a forced-full user run
    # crashes. formulas is plugin-routed (never a universe key) and must NOT be required.
    manifest = load_manifest(Path(__file__).resolve().parents[4] / "profiles.toml")
    eligible = set(namespaces.TOOL_SCOPED) | set(namespaces.SHARED) | {"instructions", "settings"}
    scope_selectors = list(manifest.scopes.keys())
    for ns in eligible:
        probe = ns if ns in ("instructions", "settings") else f"{ns}/probe"
        matched = any(_selector_matches_public(sel, probe) for sel in scope_selectors)
        assert matched, f"namespace {ns!r} has no [scopes] entry"
    assert "formulas" not in {s.split("/")[0] for s in scope_selectors}
```

Note: `_selector_matches_public` — if `_selector_matches` is private, import it as `from installer.core.profiles import _selector_matches as _selector_matches_public`. (Reusing the resolver's own matcher keeps the guard faithful.)

- [ ] **Step 2: Run to verify fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_profiles.py::test_beads_kit_profile_exists_and_scopes_kits_to_project -v`
Expected: FAIL — `beads-kit` not in profiles; no `kits/**` scope.

- [ ] **Step 3: Edit `profiles.toml`**

Add to the `[scopes]` table:

```toml
"kits/**"      = "project"
```

Add a new profile:

```toml
# The beads project kit (PRIME.md → <project>/.beads/PRIME.md). Project-scoped.
[profiles.beads-kit]
include = ["kits/beads/**"]
```

- [ ] **Step 4: Run to verify pass + re-pin the parity golden**

Run: `cd packages/installer && uv run pytest tests/unit/test_profiles.py -v`
Expected: PASS, including `test_golden_full_profile_is_byte_identical_to_todays_install` and `test_shipped_profiles_resolve_against_real_universe` — both build a **tool-only** universe (`project_universe(build_plan(...))`, no kit staging) and never select `beads-kit`, and `_assign_scope` is called only for matched result keys, so no `kits/...` key ever enters those resolves. The manifest additions are therefore inert for those tests; they stay green unchanged (no golden re-pin needed). If either *does* fail, stop — it means the additions leaked into the tool universe, which is a real regression, not an expected re-pin.

- [ ] **Step 5: Commit**

```bash
git add profiles.toml tests/unit/test_profiles.py
git commit -m "feat(installer): add kits/** project scope and beads-kit profile"
```

---

### Task 3: `project_namespaces()` capability on `ToolAdapter` + all adapters

**Files:**
- Modify: `src/installer/tools/base.py`, `tools/claude.py`, `tools/codex.py`, `tools/gemini.py`, `tools/opencode.py`
- Test: `tests/unit/test_tools.py` (or the existing per-adapter test file; create `tests/unit/test_project_namespaces.py` if none fits)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_project_namespaces.py
from installer.tools.registry import get_adapter
from installer.core.model import Tool

def test_project_namespaces_matrix() -> None:
    assert get_adapter(Tool.CLAUDE).project_namespaces() == ("skills", "agents", "commands")
    assert get_adapter(Tool.CODEX).project_namespaces() == ()
    assert get_adapter(Tool.GEMINI).project_namespaces() == ()
    assert get_adapter(Tool.OPENCODE).project_namespaces() == ()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_project_namespaces.py -v`
Expected: FAIL — `AttributeError: 'ClaudeAdapter' object has no attribute 'project_namespaces'`.

- [ ] **Step 3: Add the Protocol method + implementations**

In `tools/base.py`, add to the `ToolAdapter` Protocol (keep the load-bearing pragma):

```python
    def project_namespaces(self) -> tuple[str, ...]: ...  # pragma: no cover
```

In `tools/claude.py` `ClaudeAdapter`:

```python
    def project_namespaces(self) -> tuple[str, ...]:
        return ("skills", "agents", "commands")
```

In `tools/codex.py`, `tools/gemini.py`, `tools/opencode.py`, add to each adapter:

```python
    def project_namespaces(self) -> tuple[str, ...]:
        return ()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_project_namespaces.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/installer/tools/ tests/unit/test_project_namespaces.py
git commit -m "feat(installer): declare per-tool project_namespaces() capability matrix"
```

---

## Phase 1 — Tracer bullet (kit end-to-end via the project fork)

### Task 4: Author the beads kit content

**Files:**
- Create: `src/kits/beads/.beads/PRIME.md`

- [ ] **Step 1: Create the kit file**

Copy this repo's curated `.beads/PRIME.md` as the seed, generalizing repo-specific lines (it is currently "verified 1:1 for this repo"). The v1 kit is exactly this one file. Content is prose (no frontmatter — `bd prime` consumes it verbatim). Keep it ruthlessly minimal per the beads `PRIME.md` editing conventions.

- [ ] **Step 2: Verify tree shape**

Run: `ls -la src/kits/beads/.beads/PRIME.md`
Expected: file exists at exactly `src/kits/beads/.beads/PRIME.md` (tree-mirror: this maps to `<project>/.beads/PRIME.md`).

- [ ] **Step 3: Commit**

```bash
git add src/kits/beads/.beads/PRIME.md
git commit -m "feat(installer): add beads project kit (PRIME.md)"
```

---

### Task 5: `stage_kits` + `kit_universe` + `kit_name_of`

**Files:**
- Create: `src/installer/core/kits.py`
- Test: `tests/unit/test_kits.py`

- [ ] **Step 1: Write the failing test** (against the final `StagedKitRef` contract — one red-green pass, no mid-task contract change)

```python
# tests/unit/test_kits.py
from pathlib import Path
from installer.core.kits import stage_kits, kit_universe, kit_name_of, StagedKitRef

def _seed(root: Path) -> Path:
    kits = root / "kits"
    (kits / "beads" / ".beads").mkdir(parents=True)
    (kits / "beads" / ".beads" / "PRIME.md").write_bytes(b"beads prime\n")
    return kits

def test_stage_kits_tree_mirror_and_selector_key(tmp_path: Path) -> None:
    kits = _seed(tmp_path)
    staged = stage_kits(kits)
    assert len(staged) == 1
    sk = staged[0]
    assert sk.selector_key == "kits/beads/.beads/PRIME.md"   # source-relative selector key
    assert sk.ref.tool is None
    assert sk.ref.dest_relpath == Path(".beads/PRIME.md")    # verbatim tree-mirror, no .md strip
    universe = kit_universe(staged)
    assert universe["kits/beads/.beads/PRIME.md"] == [sk.ref]

def test_stage_kits_missing_root_is_empty(tmp_path: Path) -> None:
    assert stage_kits(tmp_path / "nope") == []

def test_kit_name_of_is_first_segment_under_kits() -> None:
    assert kit_name_of("kits/beads/.beads/PRIME.md") == "beads"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_kits.py -v`
Expected: FAIL — `ModuleNotFoundError: installer.core.kits`.

- [ ] **Step 3: Implement `core/kits.py`** (final contract; `StagedKitRef` carries the selector key the resolver universe needs)

```python
# src/installer/core/kits.py
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from installer.core.profiles import UniverseRef

def kit_name_of(selector_key: str) -> str:
    """The kit name is the segment directly under ``kits/`` — the single source of
    identity shared by the selector side and the receipt/prune owner (``kit:<name>``)."""
    parts = selector_key.split("/")
    if len(parts) < 2 or parts[0] != "kits":
        raise ValueError(f"not a kit selector key: {selector_key!r}")
    return parts[1]

@dataclass(frozen=True, slots=True)
class StagedKitRef:
    selector_key: str          # kits/<kit>/<subpath> — for the resolver universe
    ref: UniverseRef           # tool=None, dest_relpath=<subpath> (verbatim tree-mirror)

def stage_kits(kits_root: Path) -> list[StagedKitRef]:
    """Walk ``src/kits/<kit>/**``; one StagedKitRef per file. dest_relpath is verbatim
    (no suffix strip); selector_key is source-relative (``kits/<kit>/<subpath>``)."""
    if not kits_root.is_dir():
        return []
    out: list[StagedKitRef] = []
    for kit_dir in sorted(p for p in kits_root.iterdir() if p.is_dir()):
        name = kit_dir.name
        for f in sorted(p for p in kit_dir.rglob("*") if p.is_file()):
            dest_relpath = f.relative_to(kit_dir)
            selector = f"kits/{name}/{dest_relpath.as_posix()}"
            out.append(StagedKitRef(selector_key=selector, ref=UniverseRef(tool=None, dest_relpath=dest_relpath)))
    return out

def kit_universe(staged: Iterable[StagedKitRef]) -> dict[str, list[UniverseRef]]:
    universe: dict[str, list[UniverseRef]] = {}
    for sk in staged:
        universe.setdefault(sk.selector_key, []).append(sk.ref)
    return universe
```

- [ ] **Step 4: Run to verify pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_kits.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/installer/core/kits.py tests/unit/test_kits.py
git commit -m "feat(installer): stage_kits + kit_universe + kit_name_of"
```

---

### Task 6: `kit_routes` + `_KitRouteAdapter` (plugin-route wrapper)

**Files:**
- Modify: `src/installer/core/kits.py`
- Test: `tests/unit/test_kits.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_kits.py
from installer.plugins.base import PluginRoute, PluginAdapter
from installer.core.kits import kit_routes, kit_adapters

def test_kit_routes_grouped_by_dir_and_execbit(tmp_path: Path) -> None:
    kits = _seed(tmp_path)                      # kits/beads/.beads/PRIME.md (0o644)
    project = tmp_path / "proj"
    routes_by_kit = kit_routes(kits, project)
    assert set(routes_by_kit) == {"beads"}
    routes = routes_by_kit["beads"]
    assert len(routes) == 1
    r = routes[0]
    assert r.dest_dir == project / ".beads"
    assert r.source_dir == kits / "beads" / ".beads"
    assert r.executable is False

def test_kit_adapters_conform_to_plugin_adapter(tmp_path: Path) -> None:
    kits = _seed(tmp_path)
    project = tmp_path / "proj"
    adapters = kit_adapters(kits, project, selected={"beads"})
    assert len(adapters) == 1
    a = adapters[0]
    assert isinstance(a, PluginAdapter)          # runtime_checkable Protocol
    assert a.name == "kit:beads"
    assert a.routes(project) == tuple(kit_routes(kits, project)["beads"])
```

- [ ] **Step 2: Run to verify fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_kits.py -k kit_routes or kit_adapters -v`
Expected: FAIL — `kit_routes` / `kit_adapters` undefined.

- [ ] **Step 3: Implement**

```python
# src/installer/core/kits.py (append)
import os
from installer.plugins.base import PluginRoute

def kit_routes(kits_root: Path, project_root: Path) -> dict[str, list[PluginRoute]]:
    """Per kit, one PluginRoute per (destination directory × exec-bit). Mirrors
    PluginAdapter.routes(home) but grouped by kit name for per-kit owners."""
    result: dict[str, list[PluginRoute]] = {}
    if not kits_root.is_dir():
        return result
    for kit_dir in sorted(p for p in kits_root.iterdir() if p.is_dir()):
        groups: dict[tuple[Path, bool], list[str]] = {}
        for f in sorted(p for p in kit_dir.rglob("*") if p.is_file()):
            rel = f.relative_to(kit_dir)
            execbit = bool(f.stat().st_mode & 0o111)
            groups.setdefault((rel.parent, execbit), []).append(rel.suffix)
        routes: list[PluginRoute] = []
        for (destdir, execbit), _suffixes in groups.items():
            routes.append(
                PluginRoute(
                    source_dir=kit_dir / destdir,
                    dest_dir=project_root / destdir,
                    glob="*",
                    executable=execbit,
                )
            )
        result[kit_dir.name] = routes
    return result

@dataclass(frozen=True, slots=True)
class _KitRouteAdapter:
    """A selected kit presented as a PluginAdapter so it rides the existing
    install_plugin_routes / prune_pipeline / receipt machinery unchanged."""
    _name: str                       # "kit:<name>"
    _source_path: Path               # the kit source dir
    _routes: tuple[PluginRoute, ...]

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_path(self) -> Path:
        return self._source_path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002 — always active (explicitly selected)
        return True

    def routes(self, home: Path) -> tuple[PluginRoute, ...]:  # noqa: ARG002 — dest baked in
        return self._routes

def kit_adapters(kits_root: Path, project_root: Path, *, selected: set[str]) -> list[_KitRouteAdapter]:
    routes_by_kit = kit_routes(kits_root, project_root)
    return [
        _KitRouteAdapter(_name=f"kit:{name}", _source_path=kits_root / name, _routes=tuple(routes))
        for name, routes in routes_by_kit.items()
        if name in selected
    ]
```

Note: the `glob="*"` groups match every file in the dest dir; because a kit dir is grouped per (dir × exec-bit), all files in one route share the exec bit. If two kits ever produce the same dest file, that is a fatal collision — add the guard in Task 8's integration (or here if trivial).

- [ ] **Step 4: Run to verify pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_kits.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/installer/core/kits.py tests/unit/test_kits.py
git commit -m "feat(installer): kit_routes + PluginAdapter-conforming kit wrapper"
```

---

### Task 7: `--project` / `--profiles` flags + project-path validation

**Files:**
- Modify: `src/installer/cli.py` (`_build_parser` after `--plugins`, ~:73; a path guard after `resolved_repo_root`, ~:148)
- Test: `tests/unit/test_cli_project.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cli_project.py
from pathlib import Path
from installer.cli import main
from installer.core.io_port import ScriptedIO  # adjust import to the real ScriptedIO location

def test_profiles_without_project_errors(tmp_path: Path, capsys) -> None:
    rc = main(["--profiles=beads-kit", "--yes"], home=tmp_path, io=ScriptedIO(interactive=False), repo_root=_hermetic(tmp_path))
    assert rc == 2
    assert "--profiles requires --project" in capsys.readouterr().err

def test_project_path_missing_errors(tmp_path: Path, capsys) -> None:
    rc = main(["--project", str(tmp_path / "nope"), "--profiles=beads-kit", "--yes"],
              home=tmp_path, io=ScriptedIO(interactive=False), repo_root=_hermetic(tmp_path))
    assert rc == 2
    assert "nope" in capsys.readouterr().err
```

`_hermetic(tmp_path)` mirrors `test_cli_smoke._hermetic_repo` (creates `src/user/.agents` + tool dirs + copies the real `.installignore`). Factor a shared helper or copy it into this test file.

- [ ] **Step 2: Run to verify fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_project.py -v`
Expected: FAIL — flags unknown / no guard.

- [ ] **Step 3: Add flags + guards**

In `_build_parser()`, after the `--plugins` block (cli.py:~73), before `--yes`:

```python
    parser.add_argument("--project", metavar="PATH", default=None, type=Path,
                        help="Install project-scoped content into PATH instead of user space.")
    parser.add_argument("--profiles", metavar="CSV", default=None,
                        help="Comma-separated profile names (requires --project in this version).")
```

In `_run()`, immediately after `resolved_repo_root` is set (cli.py:~148), add:

```python
    if args.profiles is not None and args.project is None:
        sys.stderr.write("installer: --profiles requires --project in this version\n")
        return 2
    if args.project is not None and not args.project.is_dir():
        sys.stderr.write(f"installer: --project path is not a directory: {args.project}\n")
        return 2
```

- [ ] **Step 4: Run to verify pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_project.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/installer/cli.py tests/unit/test_cli_project.py
git commit -m "feat(installer): --project/--profiles flags + project-path guard"
```

---

### Task 8: TRACER — project-run fork writes the kit end-to-end

**Files:**
- Modify: `src/installer/cli.py` (the fork; a `_run_project(...)` helper)
- Modify: `src/installer/core/kits.py` (fatal same-dest guard, if not already)
- Test: `tests/unit/test_cli_project.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/unit/test_cli_project.py
def test_project_beads_kit_writes_prime_and_receipt(tmp_path: Path) -> None:
    repo = _hermetic(tmp_path)
    # seed the beads kit into the hermetic repo
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()
    rc = main(["--project", str(project), "--profiles=beads-kit", "--yes"],
              home=tmp_path, io=ScriptedIO(interactive=False), repo_root=repo)
    assert rc == 0
    assert (project / ".beads" / "PRIME.md").read_bytes() == b"beads prime\n"
    receipt = project / ".agents-config" / "install-receipt.json"
    assert receipt.is_file()
    assert "kit:beads" in receipt.read_text()          # owner recorded
    # user space untouched
    assert not (tmp_path / ".beads").exists()
```

- [ ] **Step 2: Run to verify fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_project.py::test_project_beads_kit_writes_prime_and_receipt -v`
Expected: FAIL — no project fork; nothing written.

- [ ] **Step 3: Implement the fork**

In `_run()`, place the fork **immediately after the `if args.dump_stage is not None:` terminal block** (cli.py:227-236) and right before `config = Config(...)` (cli.py:238). This ordering matters: putting it after the dump block means a plain `--project` run forks here, while `--project --dump-stage` falls through to the existing user dump branch (a harmless tool-plan dump) until Task 16 replaces it with kit-aware rendering — it never routes a dump flag into `_run_project`'s real install:

```python
    # ... existing `if args.dump_stage is not None:` block (returns) ...

    if args.project is not None:
        return _run_project(
            args, plans=plans, project_root=args.project, repo_root=resolved_repo_root, io=io,
        )
    # ... existing `config = Config(...)` + user mutation section, unchanged ...
```

Add `_run_project(...)` (new function in cli.py). Tracer scope — kit tail only (tool tail + persistence + prune + validation come in Phase 2):

```python
def _run_project(args, *, plans, project_root: Path, repo_root: Path, io: IOPort) -> int:
    from installer.core.kits import stage_kits, kit_universe, kit_name_of, kit_adapters
    from installer.core.profiles import load_manifest, project_universe, resolve, Scope
    from installer.core.receipt import Receipt
    from installer.core.receipt_store import read_receipt, ReadStatus
    from installer.core.receipt_lock import receipt_lock

    kits_root = repo_root / "src" / "kits"
    staged_kits = stage_kits(kits_root)
    universe = project_universe(plans.values())
    for key, refs in kit_universe(staged_kits).items():
        universe.setdefault(key, []).extend(refs)

    manifest = load_manifest(repo_root / "profiles.toml")
    selection = tuple(p.strip() for p in args.profiles.split(",")) if args.profiles else ()
    if not selection:
        sys.stderr.write("installer: project install needs an explicit profile (no implicit full)\n")
        return 2
    resolved = resolve(manifest, selection, universe, bound_scopes=frozenset({Scope.PROJECT}))

    # which kits are selected: a kit is selected iff ≥1 of its refs' dest_relpaths landed in included[PROJECT]
    project_dests = {r.dest_relpath for r in resolved.included.get(Scope.PROJECT, ())}
    selected_kits = {
        kit_name_of(sk.selector_key) for sk in staged_kits if sk.ref.dest_relpath in project_dests
    }
    adapters = kit_adapters(kits_root, project_root, selected=selected_kits)

    receipt_path = project_root / ".agents-config" / "install-receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    lock_cm = nullcontext() if args.dry_run else receipt_lock(receipt_path.with_suffix(".lock"))
    plugin_outcomes: dict[str, list[InstallOutcome]] = {}
    counters: dict[str, Counters] = {}
    try:
        with lock_cm:
            prior_read = read_receipt(receipt_path)
            prior = prior_read.receipt if prior_read.status is ReadStatus.OK and prior_read.receipt else Receipt()
            _merge_into(counters, install_plugin_routes(
                adapters, home=project_root, io=io, dry_run=args.dry_run, auto_yes=args.yes,
                outcomes_by_plugin=plugin_outcomes,
            ))
            if not args.dry_run:
                record_receipt(
                    receipt_path, prior=prior, dest_roots={}, home=project_root,
                    tool_outcomes={}, plugin_outcomes=plugin_outcomes,
                    pruned_paths=set(), relinquished_paths=set(),
                )
    except ReceiptLockBusy:
        io.err(f"another install holds the project receipt lock at {receipt_path}")
        return 1
    except ConsentRequiredError:
        return 1
    render_summary(counters, tools=[], plugins=sorted(plugin_outcomes), all_tools=[], all_plugins=[], verbose=args.verbose, io=io)
    return 0
```

Import `install_plugin_routes`, `record_receipt`, `InstallOutcome`, `Counters`, `ConsentRequiredError`, `ReceiptLockBusy`, `nullcontext`, `render_summary`, `_merge_into` at the top of cli.py (most are already imported for the user path).

- [ ] **Step 4: Run to verify pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_project.py -v`
Expected: PASS — `<project>/.beads/PRIME.md` written, `kit:beads` receipt recorded, user space untouched.

- [ ] **Step 5: Commit**

```bash
git add src/installer/cli.py src/installer/core/kits.py tests/unit/test_cli_project.py
git commit -m "feat(installer): project-run fork installs kit end-to-end (tracer)"
```

**TRACER COMPLETE** — the architecture spine is proven end-to-end. Phase 2 expands.

---

## Phase 2 — Expand

### Task 9: Resolver-on for user runs (parity-preserving)

**Files:**
- Modify: `src/installer/cli.py` (insert resolve+filter into the user mutation section, after `stage_and_transform`, before `install_pipeline`)
- Test: `tests/unit/test_cli_smoke.py` (parity), `tests/unit/test_profiles.py` (golden)

- [ ] **Step 1: Write the failing test** — an end-to-end parity assertion that a no-flag user install is byte-identical after resolver insertion:

```python
# tests/unit/test_cli_project.py (or test_cli_smoke.py)
def test_user_install_byte_identical_through_resolver(tmp_path: Path) -> None:
    repo = _hermetic(tmp_path)
    rc = main(["--tools=claude", "--yes"], home=tmp_path, io=ScriptedIO(interactive=False), repo_root=repo)
    assert rc == 0
    assert (tmp_path / ".claude" / "INSTRUCTIONS.md").read_bytes() == b"shared laws\n"
    # every file the pre-resolver install produced is still present and identical
```

- [ ] **Step 2: Run to verify current pass (baseline), then insert resolver and confirm still-pass.** The behavior must not change; this task guards it while wiring the resolver in.

- [ ] **Step 3: Insert resolver-on for the user path.** In the user mutation section, before `install_pipeline`, build `universe = project_universe(plans.values())`, `resolved = resolve(manifest, (), universe, bound_scopes=frozenset({Scope.USER}))` (empty selection ⇒ `full`), then narrow each tool plan with `filter_plan_to_scope(plans[tool], kept_dest_relpaths)` where `kept` = the USER-bound refs' dest_relpaths. Pass the filtered plans to `install_pipeline`. For `full`, `kept` is the whole plan, so output is byte-identical.

- [ ] **Step 4: Run parity + golden**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_smoke.py tests/unit/test_profiles.py -v`
Expected: PASS (byte-identical).

- [ ] **Step 5: Commit** `feat(installer): wire resolver into user install path (parity-preserving)`

---

### Task 10: Project selection — persisted set read + no-implicit-full errors

**Files:** Modify `cli.py` `_run_project` selection block; `core/config.py` (add `read_project_profiles(project_root) -> tuple[str, ...] | None`). Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — `--project p` with no `--profiles` and no persisted set errors "no implicit full"; with a persisted `[install] profiles=["beads-kit"]` it resolves that set.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** Add `read_project_profiles` (parse `<project>/project-config.toml` `[install].profiles` with `tomllib`; return `None` if absent). In `_run_project`, selection = `--profiles` CSV → else persisted → else the existing exit-2 error.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): project profile selection (persisted-set read, explicit-profile error)`

---

### Task 11: Tool tail for project runs + `project_namespaces()` validation pass

**Files:** Modify `cli.py` `_run_project` (add the tool tail); Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — a profile with an explicit `{select="skills/<x>", scope="project"}` override, `--project p` → writes `<p>/.claude/skills/<x>`; a `{select="commands/<y>", scope="project"}` for a tool without `commands` in `project_namespaces()` errors naming tool+namespace. (Add a fixture profile to the hermetic manifest, or use a temp manifest.)
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** In `_run_project`, for the tool refs in `included[PROJECT]`: run the validation pass (each tool ref's `dest_relpath.parts[0]` must be in `get_adapter(tool).project_namespaces()`, else exit-1 error naming tool+namespace); then `filter_plan_to_scope(plans[tool], kept)` and `sync_plan(get_adapter(tool), filtered, home=project_root, ...)`, feeding `tool_outcomes`; record via the existing `record_receipt` `tool_outcomes` + `dest_roots={adapter.name: adapter.dest_dir(project_root)}`.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): project tool tail + project_namespaces validation`

---

### Task 12: Kit-scope pre-resolve guard

**Files:** Modify `cli.py` `_run_project` (guard before `resolve`); Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — a selected profile carrying `{select="kits/beads/**", scope="user"}` (and a broad `{select="**", scope="user"}`) errors pre-resolve naming the selector.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** Before `resolve`, iterate the selected profiles' `IncludeEntry`s; for any with an explicit non-`PROJECT` `scope`, if its `selector` matches any key in the kit universe (via `_selector_matches`), exit-2 (or exit-1 per taxonomy) error naming the selector.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): pre-resolve kit-scope guard (kits are project-only)`

---

### Task 13: Project persistence (`project-config.toml [install]`)

**Files:** Modify `core/config.py` (`write_project_profiles`), `cli.py` `_run_project`; Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — round-trip: `--project p --profiles beads-kit` writes `[install] profiles=["beads-kit"]` to `<p>/project-config.toml`; a bare `--project p` re-run reads it; `--dry-run` writes no `project-config.toml`.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** Add `write_project_profiles(project_root, profiles)` (merge into an existing `project-config.toml`, preserving other tables; write the `[install] profiles` array). Call it in `_run_project` only on a successful, non-dry-run install, inside the lock, at the same point as the receipt write.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): persist chosen profiles to project-config.toml [install]`

---

### Task 14: Kit prune (deselected kit → orphan)

**Files:** Modify `cli.py` `_run_project` (wire prune via the kit adapters); Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — install `beads-kit`; re-install still-selected `beads-kit` with `--prune` does **not** delete `<p>/.beads/PRIME.md`; then a run selecting a different (empty-of-beads) project profile with `--prune` **removes** the orphaned `PRIME.md`. User receipt untouched.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** In `_run_project`, when `args.prune`/`args.prune_only`, call `prune_pipeline(adapters=<project tool adapters>, plugins=<kit adapters>, plans=<filtered project plans>, prior=prior, home=project_root, discovered_plugin_names={a.name for a in kit_adapters(kits_root, project_root, selected=all_kit_names)}, io=io, ...)`. The kit adapters feed `desired_route_keys`/`live_roots_by_owner` via the existing plugin path (they conform to `PluginAdapter`); `discovered_plugin_names` must include *all* kit owners (selected or not) so a deselected kit's prior entry is in `scope_owners` and thus prunable. Capture `pruned_paths`/`relinquished_paths` into `record_receipt`.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): prune orphaned kit files via the plugin-route prune path`

---

### Task 15: Detection-suggests-only (user runs)

**Files:** Modify `cli.py` (after the user-run summary print); Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — a user run whose cwd shows `.beads/` (or a `project-config.toml` with `[install]`) prints exactly one `io.info` suggestion line; a `--project` run prints none. (Inject cwd via a `cwd: Path` param on `_run`/`main` for testability, defaulting to `Path.cwd()`.)
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** After the user summary, if `(cwd / ".beads").is_dir()` or a `[install]` table exists in `cwd / "project-config.toml"`, `io.info("This looks like a project. To install project-scoped content here: install.sh --project .")`. No scan beyond cwd. Skip entirely on a `--project` run.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): detection-suggests-only notice on user runs`

---

### Task 16: `--dump-stage` under `--project`

**Files:** Modify `cli.py` (dump branch); Test: `test_cli_project.py`.

- [ ] **Step 1: Failing test** — `--project p --profiles beads-kit --dump-stage <dir>` lists the kit refs (dest + owner) alongside tool refs; kit content is not written to the dump.
- [ ] **Step 2: Run — fail.**
- [ ] **Step 3:** When `args.project` and `args.dump_stage`, after resolve, render the resolved project plan: tool refs via the existing `dump_plan` tree; kit refs as a listing (`kit:<name>  <dest_relpath>`). Terminal branch (return 0), like the user dump.
- [ ] **Step 4: Run — pass.**
- [ ] **Step 5: Commit** `feat(installer): --dump-stage lists kit refs on project runs`

---

### Task 17: Gate green + continuations

- [ ] **Step 1: Run the full gate**

Run: `cd packages/installer && make ci-installer`
Expected: lint, format-check, mypy --strict, coverage (branch ≥90%), pip-audit, entry-verify all green. Fix any coverage gaps on changed code (add tests, do not lower the floor).

- [ ] **Step 2: Update `docs/architecture/installer/` if an HLD artifact references the adapter contract or the receipt/prune flow** (the `project_namespaces()` addition and the project-receipt path). Keep it evergreen; amend in place.

- [ ] **Step 3: Commit** `chore(installer): S2 gate green + HLD touch-up`

- [ ] **Step 4: Continuations (on PR merge, per spec §8):** mint **S2.5 — user-scope profile selection wiring** as a child of `agents-config-uxns2.1`, `depends-on agents-config-viiud`; then release the S2 claim. Do not close `viiud` until the continuation exists.

---

## Self-review checklist (run before handing off)

- **Spec coverage:** §2 decisions 1-6 → Tasks 1,2,4,5-6,8-9 (resolver-on), 12 (kit-scope), 6 (whole-route); §5.1 fork → 8,11; §5.2 matrix → 3,11; §5.6 guard → 12; §6.1 selection/coverage/persistence/dump/flags → 7,9,10,13,16; §6.2 receipt+prune → 8,14; §6.4 detection → 15; §6.6 tests 1-13 → mapped across tasks. No orphan requirement.
- **Deviation flagged:** the plugin-channel reuse for kit receipt/prune (mechanism note) — plan-review gate must confirm it satisfies §6.2's behavior.
- **Type consistency:** `StagedKitRef.selector_key`/`.ref`, `kit_name_of`, `kit_routes -> dict[str, list[PluginRoute]]`, `_KitRouteAdapter` (name `kit:<name>`) used consistently Tasks 5,6,8,14.
- **No placeholders:** every task shows real test + impl code or an exact signature/edit.
