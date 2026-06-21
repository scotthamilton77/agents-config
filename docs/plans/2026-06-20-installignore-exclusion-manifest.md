# Shared `.installignore` Exclusion Manifest — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python-only hardcoded `DEAD_MARKERS` with a single repo-root `.installignore` manifest that both installers consume at staging, killing the bash↔python exclusion divergence and closing the three RED golden-master tests.

**Architecture:** A trivial-grammar manifest (exact basenames + `name/` directories; no globs) is loaded once and threaded into `stage_namespace` — the single Python chokepoint for base *and* plugin staging — and into a sourceable bash matcher lib used by `install.sh`. Missing/unreadable manifest is fail-fast on both installers. The golden-master oracle's dead-marker skip is deleted (pure tree parity); a hardcoded Python invariant test + a cross-language matcher-parity test backstop correctness.

**Tech Stack:** Python 3.11+ (`uv`, `pytest`, `mypy --strict`, `ruff`), Bash 4+ (`scripts/install.sh`). Gate: `make ci-installer` from repo root.

**Design spec:** `docs/specs/2026-06-20-installignore-exclusion-manifest-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `.installignore` | Create | Repo-root manifest; the single source of truth for excluded dev-docs. |
| `packages/installer/src/installer/core/installignore.py` | Create | `InstallIgnore` model + `load_installignore` (fail-fast on missing). |
| `packages/installer/tests/unit/test_installignore.py` | Create | Loader/model unit tests. |
| `packages/installer/tests/unit/conftest.py` | Modify | Add a shared `ignore` fixture for staging tests. |
| `packages/installer/src/installer/core/staging.py` | Modify | Drop `DEAD_MARKERS`; thread `ignore` into `stage_namespace` + `build_plan`. |
| `packages/installer/src/installer/core/overlay.py` | Modify | Thread `ignore` into `overlay_plugins` → `stage_namespace`. |
| `packages/installer/src/installer/core/orchestrator.py` | Modify | Thread `ignore` into `stage_and_transform`. |
| `packages/installer/src/installer/cli.py` | Modify | Load manifest up-front (fail-fast → exit 2); pass `ignore` to both call sites. |
| `packages/installer/tests/unit/test_staging*.py`, `test_orchestrator.py`, `test_overlay.py`, `test_run_plugin_routes.py` | Modify | Pass the `ignore` fixture to changed call sites. |
| `scripts/lib/installignore.sh` | Create | Sourceable bash matcher: `load_installignore` + `is_installignored` (fail-fast). |
| `scripts/lib/installignore_test.sh` | Create | Bash unit test for the matcher + fail-fast. |
| `scripts/install.sh` | Modify | Source the lib; load+fail-fast early; filter in `stage_content_from_dir`. |
| `packages/installer/tests/golden_master/_diff.py` | Modify | Delete the dead-marker skip (pure parity). |
| `packages/installer/tests/golden_master/test_diff.py` | Modify | Drop/replace any test pinning the deleted skip. |
| `packages/installer/tests/unit/test_installignore_invariant.py` | Create | Hardcoded "known leakers never staged" guard against the real repo. |
| `packages/installer/tests/unit/test_installignore_parity.py` | Create | Cross-language matcher-parity (bash lib vs Python). |
| `packages/installer/tests/unit/test_cli_installignore.py` | Create | CLI fail-fast on missing manifest → exit 2. |

---

## Task 1: Create the `.installignore` manifest

**Files:**
- Create: `.installignore` (repo root)

- [ ] **Step 1: Write the manifest**

Create `/.installignore` (at the repository root, alongside `AGENTS.md`):

```
# .installignore — source files excluded from the install fileset.
#
# Consumed by BOTH installers (scripts/install.sh and packages/installer) at the
# staging step, on the DIRECT CHILDREN of each staged namespace subdir, BEFORE
# any .template suffix is stripped.
#
# Grammar (simple subset; identical in bash and Python): one entry per line;
# '#' comment lines and blank lines are ignored; an exact basename matches a
# FILE; a trailing-'/' name matches a DIRECTORY. No globs, no '**', no negation,
# no anchoring.
#
# The real tool-root instruction files are *.md.template and are NOT matched by
# these bare basenames. Live leaker today: rules/AGENTS.md. The other entries are
# class coverage (defensive; see the design spec's audit table).
AGENTS.md
CLAUDE.md
GEMINI.md
README.md
SESSION-PRIMER-README.md
# Source-only rationale directories (never installed):
rules-readmes/
```

- [ ] **Step 2: Verify it is at the repo root and not under `src/`**

Run: `ls -1 .installignore && git -C . check-ignore .installignore; echo "exit=$?"`
Expected: prints `.installignore`; `check-ignore` exits non-zero (the file itself is tracked, not git-ignored).

- [ ] **Step 3: Commit**

```bash
git add .installignore
git commit -m "feat(installer): add .installignore exclusion manifest"
```

---

## Task 2: Python loader + model (`core/installignore.py`)

**Files:**
- Create: `packages/installer/src/installer/core/installignore.py`
- Test: `packages/installer/tests/unit/test_installignore.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/installer/tests/unit/test_installignore.py`:

```python
"""Unit tests for installer.core.installignore — the shared exclusion manifest
loader. Each test pins a coded decision: basename vs directory parsing, comment
and blank-line skipping, and the fail-fast contract on a missing/unreadable file
(load-bearing policy, unlike the inert-default installer.toml loader)."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.installignore import InstallIgnore, load_installignore


def test_basename_and_directory_entries_are_partitioned(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("AGENTS.md\nrules-readmes/\nREADME.md\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"AGENTS.md", "README.md"})
    assert ignore.dirnames == frozenset({"rules-readmes"})


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("# a comment\n\nAGENTS.md\n   \n# trailing\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"AGENTS.md"})
    assert ignore.dirnames == frozenset()


def test_surrounding_whitespace_is_trimmed(tmp_path: Path) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text("  AGENTS.md  \n\trules-readmes/\t\n", encoding="utf-8")

    ignore = load_installignore(manifest)

    assert ignore.basenames == frozenset({"AGENTS.md"})
    assert ignore.dirnames == frozenset({"rules-readmes"})


def test_excludes_matches_files_against_basenames(tmp_path: Path) -> None:
    ignore = InstallIgnore(basenames=frozenset({"AGENTS.md"}), dirnames=frozenset({"rules-readmes"}))

    assert ignore.excludes("AGENTS.md", is_dir=False) is True
    assert ignore.excludes("AGENTS.md.template", is_dir=False) is False  # never the real file
    assert ignore.excludes("rules-readmes", is_dir=False) is False  # dir entry, file query


def test_excludes_matches_directories_against_dirnames(tmp_path: Path) -> None:
    ignore = InstallIgnore(basenames=frozenset({"AGENTS.md"}), dirnames=frozenset({"rules-readmes"}))

    assert ignore.excludes("rules-readmes", is_dir=True) is True
    assert ignore.excludes("AGENTS.md", is_dir=True) is False  # basename entry, dir query


def test_missing_manifest_is_fail_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"\.installignore not found"):
        load_installignore(tmp_path / ".installignore")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_installignore.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'installer.core.installignore'`.

- [ ] **Step 3: Implement the loader + model**

Create `packages/installer/src/installer/core/installignore.py`:

```python
"""Loader for ``.installignore`` — the shared source-file exclusion manifest
consumed by BOTH installers at the staging step.

Unlike ``load_installer_toml`` (a missing file is an inert default), a missing or
unreadable ``.installignore`` is a HARD ERROR: the manifest encodes load-bearing
exclusion policy, so silently treating absence as "exclude nothing" would
re-leak namespace dev-docs identically on both installers — the shared-wrongness
case the golden-master parity oracle cannot see. Fail-fast turns every
missing/wrong-root/absent-in-fixture mode into a loud error.

Grammar (simple subset, identical to the bash matcher in
``scripts/lib/installignore.sh``): one entry per line; ``#`` comment lines and
blank lines ignored; an exact basename matches a file; a trailing-``/`` name
matches a directory. No globs, no ``**``, no negation, no anchoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InstallIgnore:
    """Parsed manifest: the set of excluded file basenames and directory names.

    ``excludes`` is the single match primitive both staging and the parity test
    consult; a file is tested against ``basenames``, a directory against
    ``dirnames``, so the same name can never accidentally cross kinds.
    """

    basenames: frozenset[str] = field(default_factory=frozenset)
    dirnames: frozenset[str] = field(default_factory=frozenset)

    def excludes(self, name: str, *, is_dir: bool) -> bool:
        return name in (self.dirnames if is_dir else self.basenames)


def load_installignore(path: Path) -> InstallIgnore:
    """Parse ``.installignore`` at ``path``; return an ``InstallIgnore``.

    Raises ``FileNotFoundError`` when the file is absent (fail-fast — see module
    docstring). A present-but-unreadable file raises naturally from ``read_text``
    (``PermissionError`` / ``OSError``). Both are surfaced cleanly by the CLI as
    exit 2.
    """
    if not path.is_file():
        msg = f".installignore not found at {path}; refusing to install with exclusions disabled"
        raise FileNotFoundError(msg)

    basenames: set[str] = set()
    dirnames: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("/"):
            dirnames.add(line[:-1])
        else:
            basenames.add(line)
    return InstallIgnore(basenames=frozenset(basenames), dirnames=frozenset(dirnames))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_installignore.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/installignore.py packages/installer/tests/unit/test_installignore.py
git commit -m "feat(installer): add .installignore loader with fail-fast on missing manifest"
```

---

## Task 3: Add the shared `ignore` test fixture

**Files:**
- Modify: `packages/installer/tests/unit/conftest.py`

- [ ] **Step 1: Add the fixture**

Append to `packages/installer/tests/unit/conftest.py` (add the import near the other imports at the top of the file):

```python
import pytest

from installer.core.installignore import InstallIgnore


@pytest.fixture
def ignore() -> InstallIgnore:
    """The canonical .installignore content as an in-memory object, for staging
    tests that must pass an exclusion set without touching a manifest file."""
    return InstallIgnore(
        basenames=frozenset(
            {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "SESSION-PRIMER-README.md"}
        ),
        dirnames=frozenset({"rules-readmes"}),
    )
```

- [ ] **Step 2: Verify the fixture imports cleanly**

Run: `cd packages/installer && uv run python -c "import tests.unit.conftest"`
Expected: no output, exit 0. (If `conftest` is not importable as a module, instead run `uv run pytest tests/unit/test_installignore.py -q` to confirm collection still works.)

- [ ] **Step 3: Commit**

```bash
git add packages/installer/tests/unit/conftest.py
git commit -m "test(installer): add shared ignore fixture for staging tests"
```

---

## Task 4: Thread the manifest through the Python staging chain

This is the central change. `stage_namespace` gains a required `ignore` param; every caller up the chain (`build_plan`, `overlay_plugins`, `stage_and_transform`, `cli.main`) threads it. `mypy --strict` enforces that no call site is missed.

**Files:**
- Modify: `packages/installer/src/installer/core/staging.py`
- Modify: `packages/installer/src/installer/core/overlay.py`
- Modify: `packages/installer/src/installer/core/orchestrator.py`
- Modify: `packages/installer/src/installer/cli.py`
- Modify: `packages/installer/tests/unit/test_staging.py` (and other staging/overlay/orchestrator test files — Step 9)

- [ ] **Step 1: Update the `stage_namespace` dead-marker test to use the manifest, and add a directory-exclusion test**

In `packages/installer/tests/unit/test_staging.py`, replace `test_stage_namespace_filters_top_level_marker_files` (around line 120) with the manifest-driven version, and add a directory test. (The `ignore` fixture comes from conftest; add it as a parameter.)

```python
def test_stage_namespace_filters_top_level_marker_files(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """In-repo AGENTS.md/CLAUDE.md/GEMINI.md at the top of a namespace dir are
    dead files; the .installignore matcher drops them while keeping real content."""
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "AGENTS.md").write_bytes(b"dev doc")
    (skills / "real-skill").mkdir()

    items = stage_namespace(tmp_path, "skills", provenance=_prov(), ignore=ignore)

    names = {i.dest_relpath.name for i in items}
    assert names == {"real-skill"}


def test_stage_namespace_filters_excluded_directory(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """A directory whose name is a .installignore directory entry (rules-readmes)
    is dropped whole, not partially staged."""
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "rules-readmes").mkdir()
    (rules / "rules-readmes" / "foo-readme.md").write_bytes(b"rationale")
    (rules / "real-rule.md").write_bytes(b"rule")

    items = stage_namespace(tmp_path, "rules", provenance=_prov(), ignore=ignore)

    names = {i.dest_relpath.name for i in items}
    assert names == {"real-rule.md"}
```

Add `InstallIgnore` to the imports at the top of `test_staging.py`:

```python
from installer.core.installignore import InstallIgnore
```

- [ ] **Step 2: Run to verify failure**

Run: `cd packages/installer && uv run pytest tests/unit/test_staging.py -q`
Expected: FAIL — `stage_namespace() got an unexpected keyword argument 'ignore'`.

- [ ] **Step 3: Change `stage_namespace` and `build_plan` in `staging.py`**

In `packages/installer/src/installer/core/staging.py`:

(a) Add the import after the existing model import (line 21):

```python
from installer.core.installignore import InstallIgnore
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
```

(b) Delete the `DEAD_MARKERS` frozenset and its docstring (lines 60-64).

(c) Change `stage_namespace` (replace its signature and the filter line). New signature and body head:

```python
def stage_namespace(
    source_root: Path,
    namespace: str,
    *,
    provenance: Provenance,
    ignore: InstallIgnore,
) -> list[StagedItem]:
    """Stage one namespace subdir into StagedItems.

    Port of bash ``stage_content_from_dir`` (``scripts/install.sh``). Walks
    ``source_root/namespace/*`` in sorted order; each direct child whose name is
    excluded by ``ignore`` (a file basename or a directory name from
    ``.installignore``) is skipped. Surviving entries are classified, suffix-
    stripped, and turned into ``StagedItem``s. A missing namespace dir yields
    ``[]``. Matching runs on direct children pre-``.template``-strip, so the real
    tool-root ``AGENTS.md.template`` is never matched by a bare ``AGENTS.md``.
    """
    src_dir = source_root / namespace
    if not src_dir.is_dir():
        return []

    items: list[StagedItem] = []
    for entry in sorted(src_dir.iterdir()):
        if ignore.excludes(entry.name, is_dir=entry.is_dir()):
            continue
        kind = classify_file(entry, namespace)
        # ... (rest of the loop body is UNCHANGED from the current implementation)
```

Leave the remainder of the loop body (the `StagedItem(...)` construction with `kind`, `dest_name`, `is_file`, `executable`) exactly as it is today.

(d) Change `build_plan` to accept and forward `ignore`. New signature line and the two `stage_namespace` calls:

```python
def build_plan(adapter: ToolAdapter, *, repo_root: Path, ignore: InstallIgnore) -> StagingPlan:
```

Update its two `stage_namespace` calls (Phase 2 and Phase 4) to pass `ignore=ignore`:

```python
            for item in stage_namespace(shared_root, ns, provenance=prov, ignore=ignore):
```
```python
            for item in stage_namespace(tool_root, ns, provenance=prov, ignore=ignore):
```

- [ ] **Step 4: Change `overlay_plugins` in `overlay.py`**

In `packages/installer/src/installer/core/overlay.py`:

(a) Add `InstallIgnore` to the `TYPE_CHECKING` block (the file uses `from __future__ import annotations`, so a type-only import suffices):

```python
if TYPE_CHECKING:
    from collections.abc import Sequence

    from installer.core.installignore import InstallIgnore
    from installer.core.merge.registry import MergeRegistry
    from installer.core.model import StagedItem, StagingPlan
    from installer.plugins.base import PluginAdapter
    from installer.tools.base import ToolAdapter
```

(b) Add `ignore` to `overlay_plugins`' signature:

```python
def overlay_plugins(
    plan: StagingPlan,
    plugins: Sequence[PluginAdapter],
    *,
    adapter: ToolAdapter,
    registry: MergeRegistry,
    ignore: InstallIgnore,
) -> StagingPlan:
```

(c) Pass `ignore=ignore` to its two `stage_namespace` calls:

```python
                for item in stage_namespace(tool_root, ns, provenance=prov, ignore=ignore):
```
```python
                for item in stage_namespace(shared_root, ns, provenance=prov, ignore=ignore):
```

- [ ] **Step 5: Change `stage_and_transform` in `orchestrator.py`**

In `packages/installer/src/installer/core/orchestrator.py`:

(a) Add `InstallIgnore` to the `TYPE_CHECKING` block:

```python
    from installer.core.installignore import InstallIgnore
    from installer.core.io_port import IOPort
    from installer.core.model import StagingPlan, Tool
    from installer.plugins.base import PluginAdapter
```

(b) Add `ignore` to the signature and forward it to `build_plan` and `overlay_plugins`:

```python
def stage_and_transform(
    tools: Iterable[Tool],
    *,
    repo_root: Path,
    io: IOPort,
    ignore: InstallIgnore,
    plugins: Sequence[PluginAdapter] = (),
) -> dict[Tool, StagingPlan]:
```
```python
        plan = build_plan(adapter, repo_root=repo_root, ignore=ignore)
        plan = overlay_plugins(plan, plugins, adapter=adapter, registry=registry, ignore=ignore)
```

- [ ] **Step 6: Load the manifest + fail-fast in `cli.main`**

In `packages/installer/src/installer/cli.py`:

(a) Add the import near the other core imports (around line 14):

```python
from installer.core.installignore import load_installignore
```

(b) After the excluded-plugins warning block (immediately before `if args.dump_stage is not None:` near line 173), insert the up-front load with fail-fast:

```python
    # Load the shared exclusion manifest up front, mirroring the bash installer's
    # early fail-fast. Absent or unreadable .installignore is a hard error (exit 2)
    # rather than a silent empty-exclusion install — the manifest is load-bearing
    # policy, and a missing one would re-leak dead-docs identically on both
    # installers (shared wrongness the parity oracle cannot see).
    try:
        ignore = load_installignore(resolved_repo_root / ".installignore")
    except OSError as exc:
        sys.stderr.write(f"installer: {exc}\n")
        return 2
```

(c) Pass `ignore=ignore` to BOTH `stage_and_transform` call sites (lines 174 and 195):

```python
        plans = stage_and_transform(
            tools, repo_root=resolved_repo_root, io=io, ignore=ignore, plugins=plugins
        )
```

(both occurrences).

- [ ] **Step 7: Run mypy to find every remaining call site**

Run: `cd packages/installer && uv run mypy --strict src`
Expected: errors ONLY where a `stage_namespace` / `build_plan` / `overlay_plugins` / `stage_and_transform` call still lacks `ignore`. If clean, proceed; if not, fix each reported src call site by adding `ignore=ignore` (all production call sites are covered by Steps 3-6, so a clean run is expected).

- [ ] **Step 8: Run the staging test to verify Step 1 passes**

Run: `cd packages/installer && uv run pytest tests/unit/test_staging.py -q`
Expected: PASS.

- [ ] **Step 9: Update the remaining test call sites**

Enumerate every test that calls a changed function:

Run: `cd packages/installer && grep -rn -E 'stage_namespace\(|build_plan\(|overlay_plugins\(|stage_and_transform\(' tests/unit | grep -v 'def '`

For each call site: add `ignore: InstallIgnore` (the conftest fixture) to the enclosing test function's parameters, add `from installer.core.installignore import InstallIgnore` to that test module's imports if absent, and pass `ignore=ignore` into the call. Expected files (confirm against the grep): `test_staging.py`, `test_staging_build_plan.py`, `test_staging_codex.py`, `test_staging_gemini.py`, `test_staging_opencode.py`, `test_staging_shared_carrier.py`, `test_orchestrator.py`, `test_overlay.py`, `test_run_plugin_routes.py`.

Concrete example — `test_staging_build_plan.py` (its `build_plan` call, ~line 60):

```python
# before:
#   plan = build_plan(adapter, repo_root=tmp_path)
# after:
def test_build_plan_filters_namespace_dead_markers(tmp_path: Path, ignore: InstallIgnore) -> None:
    ...
    plan = build_plan(adapter, repo_root=tmp_path, ignore=ignore)
```

- [ ] **Step 10: Run the full unit suite**

Run: `cd packages/installer && uv run pytest tests/unit -q`
Expected: PASS (all unit tests green).

- [ ] **Step 11: Commit**

```bash
git add packages/installer/src/installer/core/staging.py \
        packages/installer/src/installer/core/overlay.py \
        packages/installer/src/installer/core/orchestrator.py \
        packages/installer/src/installer/cli.py \
        packages/installer/tests/unit
git commit -m "feat(installer): consume .installignore in Python staging, drop DEAD_MARKERS"
```

---

## Task 5: Bash matcher library (`scripts/lib/installignore.sh`)

**Files:**
- Create: `scripts/lib/installignore.sh`
- Test: `scripts/lib/installignore_test.sh`

- [ ] **Step 1: Write the failing bash test**

Create `scripts/lib/installignore_test.sh`:

```bash
#!/usr/bin/env bash
# Unit test for scripts/lib/installignore.sh — the bash exclusion matcher.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB="$SCRIPT_DIR/installignore.sh"
fail=0

assert() { # $1=desc  $2=expected  $3=actual
    if [[ "$2" != "$3" ]]; then echo "FAIL: $1 (expected '$2', got '$3')" >&2; fail=1
    else echo "ok: $1"; fi
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
manifest="$work/.installignore"
printf '%s\n' '# comment' '' 'AGENTS.md' 'rules-readmes/' > "$manifest"

# shellcheck source=/dev/null
source "$LIB"
load_installignore "$manifest"

is_installignored "AGENTS.md" false && r=drop || r=keep
assert "file basename excluded" "drop" "$r"
is_installignored "AGENTS.md.template" false && r=drop || r=keep
assert "template not excluded" "keep" "$r"
is_installignored "rules-readmes" true && r=drop || r=keep
assert "dir name excluded" "drop" "$r"
is_installignored "rules-readmes" false && r=drop || r=keep
assert "dir entry does not match a file query" "keep" "$r"

# Fail-fast on a missing manifest (run in a subshell so its exit does not kill us).
( source "$LIB"; load_installignore "$work/nope" ) 2>/dev/null && r=0 || r=$?
assert "missing manifest fail-fast (nonzero exit)" "1" "$r"

exit "$fail"
```

Make it executable:

```bash
chmod +x scripts/lib/installignore_test.sh
```

- [ ] **Step 2: Run to verify failure**

Run: `bash scripts/lib/installignore_test.sh; echo "exit=$?"`
Expected: FAIL — lib not found / functions undefined; non-zero exit.

- [ ] **Step 3: Implement the lib**

Create `scripts/lib/installignore.sh`:

```bash
#!/usr/bin/env bash
# Shared exclusion matcher for the install fileset — bash side of .installignore.
# Sourced by scripts/install.sh and by installignore_test.sh. Grammar matches the
# Python loader (installer.core.installignore): one entry per line; '#' comments
# and blank lines ignored; an exact basename matches a file; a trailing-'/' name
# matches a directory. No globs, no '**', no negation, no anchoring.
#
# Requires bash 4+ associative arrays (install.sh already guards the version and
# uses `declare -A`). Do NOT `set -e` here — this file only defines functions.

declare -A _INSTALLIGNORE_BASENAMES
declare -A _INSTALLIGNORE_DIRNAMES

# load_installignore <path>: populate the matcher from the manifest. A missing or
# unreadable file is a HARD ERROR (fail-fast) — mirrors the Python loader.
load_installignore() {
    local file="$1" line
    if [[ ! -r "$file" ]]; then
        echo "Error: .installignore not found at $file; refusing to install with exclusions disabled" >&2
        exit 1
    fi
    _INSTALLIGNORE_BASENAMES=()
    _INSTALLIGNORE_DIRNAMES=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"   # ltrim
        line="${line%"${line##*[![:space:]]}"}"    # rtrim
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" == */ ]]; then
            _INSTALLIGNORE_DIRNAMES["${line%/}"]=1
        else
            _INSTALLIGNORE_BASENAMES["$line"]=1
        fi
    done < "$file"
}

# is_installignored <name> <is_dir:true|false>: succeed (0) if excluded.
is_installignored() {
    if [[ "$2" == true ]]; then
        [[ -n "${_INSTALLIGNORE_DIRNAMES[$1]:-}" ]]
    else
        [[ -n "${_INSTALLIGNORE_BASENAMES[$1]:-}" ]]
    fi
}
```

- [ ] **Step 4: Run to verify pass**

Run: `bash scripts/lib/installignore_test.sh; echo "exit=$?"`
Expected: all `ok:` lines, `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/installignore.sh scripts/lib/installignore_test.sh
git commit -m "feat(installer): add sourceable bash .installignore matcher with fail-fast"
```

---

## Task 6: Wire `scripts/install.sh` to the manifest

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: Source the lib and load the manifest with fail-fast**

In `scripts/install.sh`, just after the `PROJECT_ROOT` / `SRC_*` block (after line ~205), source the lib and load the manifest (this runs at startup, before any staging, so a missing manifest aborts the whole run):

```bash
INSTALLIGNORE_FILE="$PROJECT_ROOT/.installignore"
# shellcheck source=lib/installignore.sh
source "$SCRIPT_DIR/lib/installignore.sh"
load_installignore "$INSTALLIGNORE_FILE"
```

- [ ] **Step 2: Filter excluded entries in `stage_content_from_dir`**

In `stage_content_from_dir` (lines 613-632), add the exclusion check at the top of the per-item loop. Replace:

```bash
    for item in "$src_dir"/*; do
        [[ -e "$item" ]] || continue
        item_name="$(basename "$item")"
        file_type="$(classify_file "$item" "$dir_name")"
        stage_item "$item" "$staging_dir/$item_name" "$file_type"
    done
```

with:

```bash
    for item in "$src_dir"/*; do
        [[ -e "$item" ]] || continue
        item_name="$(basename "$item")"
        if [[ -d "$item" ]]; then is_dir=true; else is_dir=false; fi
        if is_installignored "$item_name" "$is_dir"; then
            vinfo "  .installignore: skipping $dir_name/$item_name"
            continue
        fi
        file_type="$(classify_file "$item" "$dir_name")"
        stage_item "$item" "$staging_dir/$item_name" "$file_type"
    done
```

(Declare `is_dir` alongside the existing `local item_name file_type` line: `local item_name file_type is_dir`.)

- [ ] **Step 3: Smoke-check the script parses and the help path still runs**

Run: `bash -n scripts/install.sh && echo "syntax ok"`
Expected: `syntax ok`.

Run: `bash scripts/install.sh --help >/dev/null 2>&1; echo "exit=$?"`
Expected: `exit=0` (help path does not stage, but the early `load_installignore` runs — confirms the manifest is found from `PROJECT_ROOT`). If the `--help` path short-circuits before the load, this still exits 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(installer): consume .installignore in install.sh staging with fail-fast"
```

---

## Task 7: Delete the golden-master dead-marker skip

**Files:**
- Modify: `packages/installer/tests/golden_master/_diff.py`
- Modify: `packages/installer/tests/golden_master/test_diff.py`

- [ ] **Step 1: Remove the skip from `_diff.py`**

In `packages/installer/tests/golden_master/_diff.py`:

(a) Delete the `_DEAD_MARKER_NAMES` / `_NAMESPACE_DIRS` constants and their comment (lines 91-97) and the `_is_namespace_dead_marker` function (lines 100-102).

(b) In `_index_tree`, delete the skip and update the docstring. Replace:

```python
def _index_tree(root: Path) -> dict[str, Path]:
    """Map every file under ``root`` to its normalised POSIX relpath.

    Namespace-level dead markers are skipped — see ``_is_namespace_dead_marker``.
    """
    index: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = normalize_relpath(path.relative_to(root).as_posix())
            if _is_namespace_dead_marker(rel):
                continue
            if rel in index:
```

with:

```python
def _index_tree(root: Path) -> dict[str, Path]:
    """Map every file under ``root`` to its normalised POSIX relpath.

    No path is skipped: both installers now exclude .installignore dev-docs at
    staging, so neither tree contains them and a plain tree comparison is exact.
    A dead-doc reappearing on only one side is a real divergence and must surface.
    """
    index: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = normalize_relpath(path.relative_to(root).as_posix())
            if rel in index:
```

- [ ] **Step 2: Drop/replace any test that pins the deleted skip**

Run: `cd packages/installer && grep -n -E '_is_namespace_dead_marker|dead_marker|DEAD_MARKER' tests/golden_master/test_diff.py`

If a test asserts the skip behaviour (e.g. that a namespace `AGENTS.md` is ignored by `diff_trees`), delete that test — the behaviour is intentionally gone. If no such test exists, no change here.

- [ ] **Step 3: Run the diff unit tests**

Run: `cd packages/installer && uv run pytest tests/golden_master/test_diff.py -q`
Expected: PASS (with the skip-pinning test removed).

- [ ] **Step 4: Commit**

```bash
git add packages/installer/tests/golden_master/_diff.py packages/installer/tests/golden_master/test_diff.py
git commit -m "test(installer): delete golden-master dead-marker skip (pure tree parity)"
```

---

## Task 8: Python invariant test — known leakers never staged

**Files:**
- Create: `packages/installer/tests/unit/test_installignore_invariant.py`

- [ ] **Step 1: Write the test**

Create `packages/installer/tests/unit/test_installignore_invariant.py`:

```python
"""Invariant guard: the known confirmed dev-doc leakers never appear in the
Python installer's staged output, using the REAL repo-root .installignore.

The leaker paths are HARDCODED here, deliberately NOT sourced from .installignore:
a manifest-sourced check would go blind to the exact regression it must catch —
someone deleting an entry from .installignore. This test goes red on a manifest
mis-edit OR a staging-logic regression, and survives the parity gate (it tests
Python, the permanent installer, not the bash↔python comparison)."""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import load_installignore
from installer.core.model import Tool
from installer.core.staging import build_plan
from installer.tools.registry import get_adapter

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Confirmed live leakers (design spec audit table). Their relpaths must never
# survive base staging into any tool's plan.
_FORBIDDEN_RELPATHS = (
    Path("rules/AGENTS.md"),
    Path("skills/AGENTS.md"),
)
_NAMESPACE_DIRS = {"skills", "agents", "rules", "commands", "hooks"}
_MARKER_BASENAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}


def test_known_dead_docs_are_never_staged() -> None:
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    for tool in Tool:
        adapter = get_adapter(tool)
        plan = build_plan(adapter, repo_root=_REPO_ROOT, ignore=ignore)

        for forbidden in _FORBIDDEN_RELPATHS:
            assert forbidden not in plan.items, f"{forbidden} leaked into {tool} plan"
        # No namespace-level AGENTS.md/CLAUDE.md/GEMINI.md under a staged subdir.
        for dest in plan.items:
            parts = dest.parts
            if len(parts) >= 2 and parts[-1] in _MARKER_BASENAMES:
                assert parts[-2] not in _NAMESPACE_DIRS, (
                    f"namespace dead-doc {dest} leaked into {tool} plan"
                )
```

Notes for the implementer: `build_plan` is IO-free (no `ScriptedIO` needed) and stages the known leakers, which live in the shared `rules/` and `skills/` namespaces (Phase 2). `Tool` is an enum, so `for tool in Tool` iterates all adapters; a tool with no tool-specific source dir simply yields no extra items. Confirm `get_adapter` is importable from `installer.tools.registry` (it is used in `cli.py`).

- [ ] **Step 2: Run to verify it passes against the real manifest**

Run: `cd packages/installer && uv run pytest tests/unit/test_installignore_invariant.py -q`
Expected: PASS.

- [ ] **Step 3: Prove it catches a manifest mis-edit (manual red check)**

Run:
```bash
cd packages/installer
cp ../../.installignore /tmp/installignore.bak
grep -v '^AGENTS.md$' ../../.installignore > /tmp/ii && cp /tmp/ii ../../.installignore
uv run pytest tests/unit/test_installignore_invariant.py -q; echo "exit=$?"
cp /tmp/installignore.bak ../../.installignore
```
Expected: the middle pytest FAILS (a leaker reappears), then the manifest is restored. Re-run `uv run pytest tests/unit/test_installignore_invariant.py -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add packages/installer/tests/unit/test_installignore_invariant.py
git commit -m "test(installer): guard that known dead-docs never stage (real manifest)"
```

---

## Task 9: Matcher-parity test — bash lib vs Python

**Files:**
- Create: `packages/installer/tests/unit/test_installignore_parity.py`

- [ ] **Step 1: Write the test**

Create `packages/installer/tests/unit/test_installignore_parity.py`:

```python
"""Cross-language matcher parity: the bash matcher (scripts/lib/installignore.sh)
and the Python matcher (installer.core.installignore) must agree on every fixture
path. Guards the only duplicated logic in the two-installer world. Retires with
bash at the parity gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from installer.core.installignore import load_installignore

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LIB = _REPO_ROOT / "scripts" / "lib" / "installignore.sh"

# (name, is_dir, expected) — keep/drop verdicts the two matchers must share.
_CASES = [
    ("AGENTS.md", False, "drop"),
    ("CLAUDE.md", False, "drop"),
    ("GEMINI.md", False, "drop"),
    ("README.md", False, "drop"),
    ("SESSION-PRIMER-README.md", False, "drop"),
    ("AGENTS.md.template", False, "keep"),  # the real instruction file
    ("brainstorming.md", False, "keep"),  # ordinary content
    ("rules-readmes", True, "drop"),
    ("rules-readmes", False, "keep"),  # dir entry must not match a file query
    ("real-skill", True, "keep"),
]


def _bash_verdict(manifest: Path, name: str, is_dir: bool) -> str:
    flag = "true" if is_dir else "false"
    script = (
        f'source "{_LIB}"; load_installignore "{manifest}"; '
        f'if is_installignored "{name}" {flag}; then echo drop; else echo keep; fi'
    )
    out = subprocess.run(  # noqa: S603 — fixed argv, no shell injection (paths are test-local)
        ["bash", "-c", script], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


@pytest.mark.parametrize(("name", "is_dir", "expected"), _CASES)
def test_bash_and_python_matchers_agree(
    tmp_path: Path, name: str, is_dir: bool, expected: str
) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text(
        "AGENTS.md\nCLAUDE.md\nGEMINI.md\nREADME.md\nSESSION-PRIMER-README.md\nrules-readmes/\n",
        encoding="utf-8",
    )
    ignore = load_installignore(manifest)

    python_verdict = "drop" if ignore.excludes(name, is_dir=is_dir) else "keep"
    bash_verdict = _bash_verdict(manifest, name, is_dir)

    assert python_verdict == expected
    assert bash_verdict == expected
    assert python_verdict == bash_verdict
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd packages/installer && uv run pytest tests/unit/test_installignore_parity.py -q`
Expected: PASS (10 cases). If `bash` is not on PATH in CI, mark the module `pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")` — but the golden-master suite already requires bash, so it is present.

- [ ] **Step 3: Commit**

```bash
git add packages/installer/tests/unit/test_installignore_parity.py
git commit -m "test(installer): bash/python .installignore matcher parity"
```

---

## Task 10: CLI fail-fast on a missing manifest

**Files:**
- Create: `packages/installer/tests/unit/test_cli_installignore.py`

- [ ] **Step 1: Write the test**

Create `packages/installer/tests/unit/test_cli_installignore.py`:

```python
"""The CLI fails fast (exit 2, clear stderr) when .installignore is absent from
the resolved repo root, rather than silently installing with exclusions off."""

from __future__ import annotations

from pathlib import Path

from installer.cli import main


def test_missing_manifest_aborts_with_exit_2(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    # tmp_path is a repo root with NO .installignore. Point main() at it and a
    # throwaway HOME so nothing real is touched.
    home = tmp_path / "home"
    home.mkdir()

    rc = main(["--yes"], home=home, repo_root=tmp_path)

    assert rc == 2
    err = capsys.readouterr().err
    assert ".installignore not found" in err
```

Notes for the implementer: confirm `main`'s parameter names (`home`, `repo_root`) and that `--yes` is a valid flag (see `cli.py` `_build_parser`); if a different non-interactive flag is required to avoid prompting, use it. The load+fail-fast inserted in Task 4 Step 6 runs before any tool dispatch, so no tool/plugin source is needed in `tmp_path`.

- [ ] **Step 2: Run to verify it passes**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_installignore.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/installer/tests/unit/test_cli_installignore.py
git commit -m "test(installer): CLI fail-fast on missing .installignore"
```

---

## Task 11: Full gate + golden-master green

**Files:** none (verification + final confirmation)

- [ ] **Step 1: Run the golden-master parity suite**

Run: `cd packages/installer && uv run pytest tests/golden_master -q`
Expected: PASS — including `test_bare_install_codex`, `test_bare_install_gemini`, `test_bare_install_opencode` (previously RED) and `test_bare_install_single_tool` (claude).

- [ ] **Step 2: Prove the RED→GREEN transition is real (optional spot-check)**

Run: `cd packages/installer && git stash && uv run pytest tests/golden_master/test_parity.py -k 'bare_install and (codex or gemini or opencode)' -q; echo "exit=$?"; git stash pop`
Expected: the stashed (pre-change) run FAILS the three; after `git stash pop` the working tree is restored. (Skip if a partial stash would be unsafe; the design spec already documents the pre-change RED state.)

- [ ] **Step 3: Run the full installer gate**

Run (from repo root): `make ci-installer`
Expected: PASS — ruff lint, ruff format-check, mypy --strict, pytest --cov (≥90% branch), pip-audit, entry-verify all green. If coverage on `core/installignore.py` is below the floor, add the missing branch case (empty file, unreadable file) to `test_installignore.py`.

- [ ] **Step 4: Run the bash matcher test once more**

Run: `bash scripts/lib/installignore_test.sh; echo "exit=$?"`
Expected: `exit=0`.

- [ ] **Step 5: Final commit (if any gate fixups were needed)**

```bash
git add -A
git commit -m "chore(installer): gate fixups for .installignore manifest"
```

---

## Self-Review (run before handing off)

- **Spec coverage:** manifest (Task 1) ✓; grammar + bare-basename + dir entry (Tasks 1,2,5) ✓; dual consumption single-chokepoint per installer (Tasks 4,6) ✓; fail-closed/fail-fast (Tasks 2,4,5,6,10) ✓; oracle simplified to pure parity (Task 7) ✓; hardcoded invariant test (Task 8) ✓; matcher-parity test (Task 9) ✓; audit table → manifest entries (Task 1) ✓; non-editable-wheel caveat is documented in the spec (no task — it is a future risk, not current work).
- **Placeholder scan:** none — every code step carries complete code; the only "confirm X" notes point at exact call sites with the grep to find them.
- **Type consistency:** `InstallIgnore` / `load_installignore` / `excludes(name, *, is_dir)` used identically across loader, staging, overlay, orchestrator, cli, and all tests; bash `load_installignore` / `is_installignored <name> <is_dir>` consistent across lib, install.sh, and both bash/parity tests.
