# Installer-Owned CLI Deploys (`work` + `prgroom`) Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The installer deploys `work` (packages/workcli) and `prgroom` (packages/prgroom) onto the user's PATH via `uv tool install`, idempotently, with receipt tracking, prune-side uninstall, and a PATH-reachability invariant.

**Architecture:** A closed `CliSpec` registry + source digest (pure data, `core/clis.py`); an injected `CliDeployPort` subprocess seam (`UvCliDeploy` real / `ScriptedCliDeploy` fake, same module); a `deploy_clis` stage in `core/run.py` called from `cli._run()` (user path only) inside the receipt lock; an additive `Receipt.clis` field threaded through `record_receipt` → `merge_receipt`; a `prune_clis` half bounded by the registry-history allowlist.

**Tech Stack:** Python ≥3.11, uv ≥0.10.4 (`MIN_UV_VERSION` guard), pytest + ScriptedIO/ScriptedCliDeploy fakes, mypy --strict, ruff (line-length 100), coverage ≥90% branch.

**Spec:** `docs/specs/2026-07-15-installer-cli-deploy-design.md` (§ references below). Test-plan items cited as "item N" map to spec §10.

**Worktree:** `/Users/scott/src/projects/agents-config/.claude/worktrees/wgclw-9.9-installer-cli-deploy` — run ALL commands from this root. Package commands: `cd packages/installer && uv run pytest ...`. Full gate: `make ci-installer` from the worktree root.

**House rules that bind every task:**
- Test docstrings use Given/When/Then + a `Pins:` line citing the spec section/item.
- `# pragma: no cover` on every `Protocol` method declaration (load-bearing for branch coverage).
- No module outside `io_port.py` imports rich or calls print/input; subprocess calls live ONLY in `UvCliDeploy`.
- ruff line-length 100; mypy strict (no untyped defs, no implicit Optional).
- Commit after each green task: `git add <files> && git commit -m "<semantic prefix>"`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `packages/installer/src/installer/core/clis.py` | Create | CliSpec registry, MIN_UV_VERSION, CommandResult, cli_source_digest, CliDeployPort protocol, UvCliDeploy (real), ScriptedCliDeploy (fake) |
| `packages/installer/src/installer/core/receipt.py` | Modify | CliReceiptEntry, Receipt.clis field, canonical_bytes omit-when-empty |
| `packages/installer/src/installer/core/receipt_store.py` | Modify | clis (de)serialization + fail-closed validation |
| `packages/installer/src/installer/core/receipt_build.py` | Modify | merge_clis rule; merge_receipt/record threading |
| `packages/installer/src/installer/core/run.py` | Modify | CliDeployOutcome, deploy_clis stage, CliPruneOutcome, prune_clis, record_receipt params |
| `packages/installer/src/installer/core/summary.py` | Modify | clis param on render_summary/_report_targets |
| `packages/installer/src/installer/cli.py` | Modify | cli_deploy injection, stage calls, exit-flag, receipt threading |
| `packages/installer/tests/unit/test_clis_registry.py` | Create | Task 1 tests |
| `packages/installer/tests/unit/test_clis_port.py` | Create | Tasks 2–3 tests |
| `packages/installer/tests/unit/test_receipt_clis.py` | Create | Tasks 4–5 tests |
| `packages/installer/tests/unit/test_deploy_clis.py` | Create | Tasks 6–9 tests |
| `packages/installer/tests/unit/test_prune_clis.py` | Create | Task 10 tests |
| `packages/installer/tests/unit/test_cli_deploy_wiring.py` | Create | Task 11 tests |
| `packages/installer/tests/unit/test_summary.py` | Modify | Task 12 tests |
| Docs (§9 list) | Modify | Task 13 |

---

### Task 1: Registry, CommandResult, and source digest

**Files:**
- Create: `packages/installer/src/installer/core/clis.py`
- Test: `packages/installer/tests/unit/test_clis_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the CLI-deploy registry and source digest (spec §3, §5)."""

from pathlib import Path

import pytest

from installer.core.clis import CLI_PACKAGES, RETIRED_CLIS, CliSpec, cli_source_digest


def _seed(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _package(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    _seed(pkg / "pyproject.toml", b"[project]\nname='p'\n")
    _seed(pkg / "src" / "p" / "__init__.py", b"")
    return pkg


def test_registry_is_exactly_workcli_and_prgroom() -> None:
    """
    Given the shipped registry
    When CLI_PACKAGES is consulted
    Then it contains exactly workcli->work and prgroom->prgroom, and
    RETIRED_CLIS is empty.

    Pins spec §3: closed registry; pdlc/holding-place/vizsuite must NOT
    auto-deploy.
    """
    assert [s.name for s in CLI_PACKAGES] == ["workcli", "prgroom"]
    by_name = {s.name: s for s in CLI_PACKAGES}
    assert by_name["workcli"] == CliSpec(
        "workcli", "packages/workcli", "work", ("--protocol-version",)
    )
    assert by_name["prgroom"] == CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",))
    assert RETIRED_CLIS == ()


def test_digest_missing_pyproject_raises(tmp_path: Path) -> None:
    """
    Given a directory without pyproject.toml
    When cli_source_digest runs
    Then it raises FileNotFoundError naming the dir.

    Pins spec §5 / item 15: a registry entry at a non-package is a wiring
    bug — fail fast.
    """
    with pytest.raises(FileNotFoundError):
        cli_source_digest(tmp_path)


def test_digest_missing_lock_omitted_and_later_lock_changes_digest(tmp_path: Path) -> None:
    """
    Given a package without uv.lock
    When a uv.lock is added later
    Then the digest changes (lock participates when present, is silently
    omitted when absent).

    Pins spec §5 / item 15.
    """
    pkg = _package(tmp_path)
    before = cli_source_digest(pkg)
    _seed(pkg / "uv.lock", b"lock")
    assert cli_source_digest(pkg) != before


def test_digest_ignores_tests_pycache_and_pyc(tmp_path: Path) -> None:
    """
    Given a package
    When files under tests/**, __pycache__/, or *.pyc change
    Then the digest does not change.

    Pins spec §5 / item 15: docs/tests/build churn is not a reason to
    reinstall.
    """
    pkg = _package(tmp_path)
    before = cli_source_digest(pkg)
    _seed(pkg / "tests" / "test_x.py", b"t")
    _seed(pkg / "src" / "p" / "__pycache__" / "m.cpython-311.pyc", b"c")
    _seed(pkg / "src" / "p" / "stray.pyc", b"c")
    assert cli_source_digest(pkg) == before


def test_digest_changes_on_src_change(tmp_path: Path) -> None:
    """
    Given a package
    When a file under src/** changes
    Then the digest changes.

    Pins spec §5: src/** is deployable source.
    """
    pkg = _package(tmp_path)
    before = cli_source_digest(pkg)
    _seed(pkg / "src" / "p" / "__init__.py", b"changed")
    assert cli_source_digest(pkg) != before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_clis_registry.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'installer.core.clis'`

- [ ] **Step 3: Write the minimal implementation**

```python
"""CLI-deploy registry, source digest, and subprocess port (spec: installer-cli-deploy).

The registry is CLOSED (like the Tool enum, unlike the plugins dir-scan):
packages/ contains early packages that must not auto-deploy. Uninstall
authority is bounded by CLI_PACKAGES | RETIRED_CLIS — the receipt alone never
authorizes an uninstall.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from installer.core.hashing import sha256_file

MIN_UV_VERSION: tuple[int, ...] = (0, 10, 4)


@dataclass(frozen=True, slots=True)
class CliSpec:
    """One deployable CLI package. ``name`` is the uv tool name; ``binary``
    the console-script it provides; ``smoke_args`` a cheap no-backend
    invocation proving the shim executes."""

    name: str
    package_dir: str  # repo-relative
    binary: str
    smoke_args: tuple[str, ...]


CLI_PACKAGES: tuple[CliSpec, ...] = (
    CliSpec("workcli", "packages/workcli", "work", ("--protocol-version",)),
    CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",)),
)

RETIRED_CLIS: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of one port subprocess: ``output`` is merged stdout+stderr,
    surfaced verbatim on failure."""

    ok: bool
    output: str


def cli_source_digest(package_dir: Path) -> str:
    """Deterministic ``sha256:<hex>`` over the package's deployable source.

    Inputs: pyproject.toml (required — missing means the registry points at a
    non-package: fail fast), uv.lock (omitted when absent), and src/** minus
    __pycache__/*.pyc. tests/README/AGENTS.md are deliberately excluded — a
    docs-only change must not force a reinstall (spec §5)."""
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.is_file():
        msg = f"not a deployable CLI package (no pyproject.toml): {package_dir}"
        raise FileNotFoundError(msg)
    files = [pyproject]
    lock = package_dir / "uv.lock"
    if lock.is_file():
        files.append(lock)
    src = package_dir / "src"
    if src.is_dir():
        files.extend(
            p
            for p in src.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )
    h = hashlib.sha256()
    for f in sorted(files):
        h.update(str(f.relative_to(package_dir)).encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(sha256_file(f))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_clis_registry.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/clis.py packages/installer/tests/unit/test_clis_registry.py
git commit -m "feat(installer): CLI-deploy registry + source digest (wgclw.9.9 T1)"
```

---

### Task 2: CliDeployPort protocol + ScriptedCliDeploy fake

**Files:**
- Modify: `packages/installer/src/installer/core/clis.py` (append)
- Test: `packages/installer/tests/unit/test_clis_port.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the CliDeployPort fake and real implementation (spec §4)."""

from pathlib import Path

import pytest

from installer.core.clis import CommandResult, ScriptedCliDeploy


def test_scripted_fake_pops_queues_and_records_transcript(tmp_path: Path) -> None:
    """
    Given a ScriptedCliDeploy with pre-loaded answers
    When port methods are called
    Then each pops its queue in order and the transcript records
    (method, key-arg) tuples for post-hoc assertion.

    Pins spec §4: the fake mirrors ScriptedIO (queues + transcript).
    """
    fake = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[tmp_path / "bin"],
        shims=[tmp_path / "bin" / "work"],
        tool_lists=[{"workcli": frozenset({"work"})}],
        installs=[CommandResult(ok=True, output="")],
        smokes=[CommandResult(ok=True, output="")],
        whiches=[tmp_path / "bin" / "work"],
    )
    assert fake.uv_version() == (0, 10, 4)
    assert fake.bin_dir() == tmp_path / "bin"
    assert fake.shim_path("work") == tmp_path / "bin" / "work"
    assert fake.tool_list() == {"workcli": frozenset({"work"})}
    assert fake.tool_install(tmp_path / "pkg", force=False).ok
    assert fake.smoke(tmp_path / "bin" / "work", ("--protocol-version",)).ok
    assert fake.which("work") == tmp_path / "bin" / "work"
    assert ("tool_install", str(tmp_path / "pkg"), False) in fake.transcript
    assert ("smoke", str(tmp_path / "bin" / "work")) in fake.transcript


def test_scripted_fake_exhaustion_is_loud(tmp_path: Path) -> None:
    """
    Given a fake with an empty installs queue
    When tool_install is called
    Then it raises with a message naming the exhausted queue.

    Pins spec §4: exhaustion-error self-diagnosis mirrors ScriptedIO.
    """
    fake = ScriptedCliDeploy()
    with pytest.raises(RuntimeError, match="installs"):
        fake.tool_install(tmp_path / "pkg", force=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_clis_port.py -v`
Expected: FAIL with `ImportError: cannot import name 'ScriptedCliDeploy'`

- [ ] **Step 3: Append the protocol and fake to `core/clis.py`**

Add imports at top: `from collections.abc import Mapping` and `from typing import Protocol, runtime_checkable`.

```python
@runtime_checkable
class CliDeployPort(Protocol):
    """Injected subprocess seam for uv-tool deploys. All installed-state
    decisions are PATH-independent (bin_dir/shim_path/tool_list); ``which``
    serves only the reachability invariant (spec §4)."""

    def uv_version(self) -> tuple[int, ...] | None: ...  # pragma: no cover
    def bin_dir(self) -> Path: ...  # pragma: no cover
    def shim_path(self, binary: str) -> Path | None: ...  # pragma: no cover
    def tool_list(self) -> Mapping[str, frozenset[str]] | None: ...  # pragma: no cover
    def tool_install(self, package_dir: Path, *, force: bool) -> CommandResult: ...  # pragma: no cover
    def tool_uninstall(self, name: str) -> CommandResult: ...  # pragma: no cover
    def update_shell(self) -> CommandResult: ...  # pragma: no cover
    def which(self, binary: str) -> Path | None: ...  # pragma: no cover
    def smoke(self, shim: Path, args: tuple[str, ...]) -> CommandResult: ...  # pragma: no cover


class ScriptedCliDeploy:
    """Test fake: per-method answer queues + a transcript of
    ``(method, *key-args)`` tuples. A pop on an empty queue raises with the
    queue's name (self-diagnosing, mirroring ScriptedIO)."""

    def __init__(
        self,
        *,
        uv_versions: list[tuple[int, ...] | None] | None = None,
        bin_dirs: list[Path] | None = None,
        shims: list[Path | None] | None = None,
        tool_lists: list[Mapping[str, frozenset[str]] | None] | None = None,
        installs: list[CommandResult] | None = None,
        uninstalls: list[CommandResult] | None = None,
        update_shells: list[CommandResult] | None = None,
        whiches: list[Path | None] | None = None,
        smokes: list[CommandResult] | None = None,
    ) -> None:
        self._uv_versions = list(uv_versions or [])
        self._bin_dirs = list(bin_dirs or [])
        self._shims = list(shims or [])
        self._tool_lists = list(tool_lists or [])
        self._installs = list(installs or [])
        self._uninstalls = list(uninstalls or [])
        self._update_shells = list(update_shells or [])
        self._whiches = list(whiches or [])
        self._smokes = list(smokes or [])
        self.transcript: list[tuple[str, ...]] = []

    def _pop(self, queue: list, name: str):  # type: ignore[no-untyped-def]
        if not queue:
            msg = f"ScriptedCliDeploy {name} queue exhausted"
            raise RuntimeError(msg)
        return queue.pop(0)

    def uv_version(self) -> tuple[int, ...] | None:
        self.transcript.append(("uv_version",))
        return self._pop(self._uv_versions, "uv_versions")  # type: ignore[no-any-return]

    def bin_dir(self) -> Path:
        self.transcript.append(("bin_dir",))
        return self._pop(self._bin_dirs, "bin_dirs")  # type: ignore[no-any-return]

    def shim_path(self, binary: str) -> Path | None:
        self.transcript.append(("shim_path", binary))
        return self._pop(self._shims, "shims")  # type: ignore[no-any-return]

    def tool_list(self) -> Mapping[str, frozenset[str]] | None:
        self.transcript.append(("tool_list",))
        return self._pop(self._tool_lists, "tool_lists")  # type: ignore[no-any-return]

    def tool_install(self, package_dir: Path, *, force: bool) -> CommandResult:
        self.transcript.append(("tool_install", str(package_dir), force))
        return self._pop(self._installs, "installs")  # type: ignore[no-any-return]

    def tool_uninstall(self, name: str) -> CommandResult:
        self.transcript.append(("tool_uninstall", name))
        return self._pop(self._uninstalls, "uninstalls")  # type: ignore[no-any-return]

    def update_shell(self) -> CommandResult:
        self.transcript.append(("update_shell",))
        return self._pop(self._update_shells, "update_shells")  # type: ignore[no-any-return]

    def which(self, binary: str) -> Path | None:
        self.transcript.append(("which", binary))
        return self._pop(self._whiches, "whiches")  # type: ignore[no-any-return]

    def smoke(self, shim: Path, args: tuple[str, ...]) -> CommandResult:
        self.transcript.append(("smoke", str(shim)))
        return self._pop(self._smokes, "smokes")  # type: ignore[no-any-return]
```

Note for the implementer: if mypy strict rejects the `_pop` helper's untyped signature even with the ignore, inline typed pops per method (`if not self._installs: raise ...; return self._installs.pop(0)`) — ScriptedIO uses that per-method form; matching it is the safe fallback.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_clis_port.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/clis.py packages/installer/tests/unit/test_clis_port.py
git commit -m "feat(installer): CliDeployPort protocol + ScriptedCliDeploy fake (wgclw.9.9 T2)"
```

---

### Task 3: UvCliDeploy real implementation

**Files:**
- Modify: `packages/installer/src/installer/core/clis.py` (append)
- Test: `packages/installer/tests/unit/test_clis_port.py` (append)

- [ ] **Step 1: Write the failing tests (append to test_clis_port.py)**

```python
import os
import subprocess

from installer.core.clis import UvCliDeploy


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_uv_version_parses_semver(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Given `uv --version` printing 'uv 0.10.4 (Homebrew 2026-02-17)'
    When uv_version() runs
    Then it returns (0, 10, 4); an unparseable output returns None.

    Pins spec §4/§6: the MIN_UV_VERSION guard input.
    """
    port = UvCliDeploy()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(stdout="uv 0.10.4 (Homebrew)")
    )
    assert port.uv_version() == (0, 10, 4)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(stdout="garbage"))
    assert port.uv_version() is None


def test_bin_dir_fallback_chain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Given `uv tool dir --bin` failing
    When bin_dir() resolves
    Then it honors UV_TOOL_BIN_DIR, then XDG_BIN_HOME, then
    XDG_DATA_HOME/../bin, then ~/.local/bin.

    Pins spec §4 / item 17 (full documented uv precedence).
    """

    def _boom(*a: object, **k: object) -> _FakeCompleted:
        raise FileNotFoundError("uv")

    port = UvCliDeploy()
    monkeypatch.setattr(subprocess, "run", _boom)
    for var in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "uvbin"))
    assert port.bin_dir() == tmp_path / "uvbin"
    monkeypatch.delenv("UV_TOOL_BIN_DIR")
    monkeypatch.setenv("XDG_BIN_HOME", str(tmp_path / "xdgbin"))
    assert port.bin_dir() == tmp_path / "xdgbin"
    monkeypatch.delenv("XDG_BIN_HOME")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert port.bin_dir() == (tmp_path / "data" / ".." / "bin").resolve()
    monkeypatch.delenv("XDG_DATA_HOME")
    assert port.bin_dir() == Path.home() / ".local" / "bin"


def test_tool_list_parses_names_and_executables(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Given `uv tool list` output with tools and '- exe' lines
    When tool_list() runs
    Then it returns {tool: frozenset(executables)}; a failed query returns
    None.

    Pins spec §4: the provenance mapping gating promptless heal (item 19).
    """
    out = "workcli v0.1.0\n- work\nprgroom v0.1.0\n- prgroom\n"
    port = UvCliDeploy()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=out))
    assert port.tool_list() == {
        "workcli": frozenset({"work"}),
        "prgroom": frozenset({"prgroom"}),
    }
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=2))
    assert port.tool_list() is None


def test_tool_install_exports_constraints_when_lock_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Given a package dir with a uv.lock
    When tool_install runs
    Then it first runs `uv export --frozen --no-dev --no-emit-project`, then
    `uv tool install --constraints <file> <dir>`; force=True adds --force;
    a lock-less package installs unconstrained.

    Pins spec §4 / items 16, 18 (lock-respecting + non-forcing fresh).
    """
    calls: list[list[str]] = []

    def _record(cmd: list[str], **k: object) -> _FakeCompleted:
        calls.append(cmd)
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", _record)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "uv.lock").write_text("lock")
    port = UvCliDeploy()
    assert port.tool_install(pkg, force=False).ok
    assert calls[0][:2] == ["uv", "export"]
    assert "--frozen" in calls[0] and "--no-emit-project" in calls[0]
    assert calls[1][:3] == ["uv", "tool", "install"]
    assert "--constraints" in calls[1] and "--force" not in calls[1]

    calls.clear()
    lockless = tmp_path / "lockless"
    lockless.mkdir()
    assert port.tool_install(lockless, force=True).ok
    assert calls[0][:3] == ["uv", "tool", "install"]
    assert "--force" in calls[0] and "--constraints" not in calls[0]


def test_subprocess_failures_map_to_not_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Given TimeoutExpired / FileNotFoundError / non-zero exit from uv
    When tool_uninstall or smoke runs
    Then CommandResult(ok=False, output=...) is returned, never an exception.

    Pins spec §4/§8: fail loud via the result, no exception leakage.
    """
    port = UvCliDeploy()

    def _timeout(*a: object, **k: object) -> _FakeCompleted:
        raise subprocess.TimeoutExpired(cmd="uv", timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)
    assert not port.tool_uninstall("workcli").ok

    def _missing(*a: object, **k: object) -> _FakeCompleted:
        raise FileNotFoundError("no shim")

    monkeypatch.setattr(subprocess, "run", _missing)
    assert not port.smoke(tmp_path / "bin" / "work", ("--protocol-version",)).ok
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _FakeCompleted(returncode=1, stderr="boom")
    )
    result = port.tool_uninstall("workcli")
    assert not result.ok and "boom" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_clis_port.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'UvCliDeploy'`

- [ ] **Step 3: Append UvCliDeploy to `core/clis.py`**

Add imports: `import os`, `import re`, `import shutil`, `import subprocess`, `import tempfile`.

```python
_INSTALL_TIMEOUT = 300  # cold uv cache + dependency resolution can be slow
_SMOKE_TIMEOUT = 30
_QUERY_TIMEOUT = 10


class UvCliDeploy:
    """Real CliDeployPort backed by uv subprocesses. The ONLY module code
    that shells out for CLI deploys; everything above it stays pure."""

    def _run(self, cmd: list[str], timeout: int) -> CommandResult:
        try:
            proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
                cmd, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return CommandResult(ok=False, output=f"timed out after {timeout}s: {' '.join(cmd)}")
        except FileNotFoundError as exc:
            return CommandResult(ok=False, output=f"not found: {exc}")
        output = (proc.stdout or "") + (proc.stderr or "")
        return CommandResult(ok=proc.returncode == 0, output=output)

    def uv_version(self) -> tuple[int, ...] | None:
        result = self._run(["uv", "--version"], _QUERY_TIMEOUT)
        match = re.search(r"\buv (\d+)\.(\d+)\.(\d+)", result.output) if result.ok else None
        return tuple(int(g) for g in match.groups()) if match else None

    def bin_dir(self) -> Path:
        result = self._run(["uv", "tool", "dir", "--bin"], _QUERY_TIMEOUT)
        if result.ok and result.output.strip():
            return Path(result.output.strip().splitlines()[0])
        # uv's documented resolution order, in full (spec §4; item 17).
        if env := os.environ.get("UV_TOOL_BIN_DIR"):
            return Path(env)
        if env := os.environ.get("XDG_BIN_HOME"):
            return Path(env)
        if env := os.environ.get("XDG_DATA_HOME"):
            return (Path(env) / ".." / "bin").resolve()
        return Path.home() / ".local" / "bin"

    def shim_path(self, binary: str) -> Path | None:
        candidate = self.bin_dir() / binary
        return candidate if candidate.is_file() else None

    def tool_list(self) -> Mapping[str, frozenset[str]] | None:
        result = self._run(["uv", "tool", "list"], _QUERY_TIMEOUT)
        if not result.ok:
            return None
        tools: dict[str, set[str]] = {}
        current: str | None = None
        for line in result.output.splitlines():
            if line.startswith("- ") and current is not None:
                tools[current].add(line[2:].strip())
            else:
                match = re.match(r"^(\S+) v\S+", line)
                if match:
                    current = match.group(1)
                    tools[current] = set()
        return {name: frozenset(exes) for name, exes in tools.items()}

    def tool_install(self, package_dir: Path, *, force: bool) -> CommandResult:
        cmd = ["uv", "tool", "install"]
        if force:
            cmd.append("--force")
        lock = package_dir / "uv.lock"
        if lock.is_file():
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
                constraints = Path(tmp.name)
            export = self._run(
                ["uv", "export", "--frozen", "--no-dev", "--no-emit-project",
                 "--project", str(package_dir), "-o", str(constraints)],
                _QUERY_TIMEOUT,
            )
            if not export.ok:
                constraints.unlink(missing_ok=True)
                return export
            cmd.extend(["--constraints", str(constraints)])
        cmd.append(str(package_dir))
        result = self._run(cmd, _INSTALL_TIMEOUT)
        if lock.is_file():
            constraints.unlink(missing_ok=True)
        return result

    def tool_uninstall(self, name: str) -> CommandResult:
        return self._run(["uv", "tool", "uninstall", name], _QUERY_TIMEOUT)

    def update_shell(self) -> CommandResult:
        result = self._run(["uv", "tool", "update-shell"], _QUERY_TIMEOUT)
        # uv exits non-zero when the shell config already contains the PATH
        # entry; that expected steady state counts as success (spec §6 /
        # item 20 — repeat installs from an un-restarted shell stay green).
        if not result.ok and "already" in result.output.lower():
            return CommandResult(ok=True, output=result.output)
        return result

    def which(self, binary: str) -> Path | None:
        found = shutil.which(binary)
        return Path(found) if found else None

    def smoke(self, shim: Path, args: tuple[str, ...]) -> CommandResult:
        return self._run([str(shim), *args], _SMOKE_TIMEOUT)
```

Implementer note: verify the exact `uv export` flag spelling against `uv export --help` on this machine before finalizing; the flags above were verified on uv 0.10.4. If `uv tool update-shell`'s already-configured output does not contain "already", capture its real wording with a live probe and match that (the test for this classification lives in Task 9 via the fake; the real-impl match string is best-effort and documented here).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_clis_port.py -v`
Expected: 7 PASS

- [ ] **Step 5: Run lint/type gates early (this module has the trickiest types)**

Run: `cd packages/installer && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy --strict src`
Expected: clean (fix any strict-mode complaints in clis.py before committing)

- [ ] **Step 6: Commit**

```bash
git add packages/installer/src/installer/core/clis.py packages/installer/tests/unit/test_clis_port.py
git commit -m "feat(installer): UvCliDeploy real port — lock-respecting install, XDG fallback (wgclw.9.9 T3)"
```

---

### Task 4: Receipt extension (CliReceiptEntry + clis field + store)

**Files:**
- Modify: `packages/installer/src/installer/core/receipt.py`
- Modify: `packages/installer/src/installer/core/receipt_store.py`
- Test: `packages/installer/tests/unit/test_receipt_clis.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the additive Receipt.clis field (spec §7, item 11)."""

import json
from pathlib import Path

from installer.core.receipt import CliReceiptEntry, Receipt, canonical_bytes, compute_integrity
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt

_ENTRY = CliReceiptEntry(name="workcli", binary="work", digest="sha256:ab")


def test_clis_round_trip(tmp_path: Path) -> None:
    """
    Given a receipt with one clis entry
    When written and re-read
    Then status is OK and the entry survives intact.

    Pins spec §7 / item 11: receipt_store round-trips the field.
    """
    path = tmp_path / "install-receipt.json"
    write_receipt(path, Receipt(clis=(_ENTRY,)))
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None and result.receipt.clis == (_ENTRY,)


def test_legacy_receipt_without_clis_still_validates(tmp_path: Path) -> None:
    """
    Given a receipt written before the clis field existed
    When read by the new code
    Then it reads OK (integrity still validates) with clis == ().

    Pins spec §7: canonical_bytes includes "clis" only when non-empty, so a
    legacy receipt hashes byte-identically (item 11).
    """
    path = tmp_path / "install-receipt.json"
    legacy = Receipt()  # no clis
    write_receipt(path, legacy)
    raw = json.loads(path.read_text())
    assert "clis" not in raw  # emitted only when non-empty
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None and result.receipt.clis == ()


def test_empty_clis_hashes_identically_to_absent() -> None:
    """
    Given two receipts, one default and one with explicit empty clis
    When canonical_bytes runs
    Then the bytes are identical (no integrity break for legacy receipts).

    Pins spec §7 omit-when-empty.
    """
    assert canonical_bytes(Receipt()) == canonical_bytes(Receipt(clis=()))
    assert compute_integrity(Receipt()) == compute_integrity(Receipt(clis=()))


def test_malformed_clis_entry_reads_corrupt(tmp_path: Path) -> None:
    """
    Given a receipt whose clis entry has a non-string field
    When read
    Then status is CORRUPT (fail closed — a malformed entry must not drive
    deploy/prune decisions).

    Pins spec §7 validation / item 11.
    """
    path = tmp_path / "install-receipt.json"
    write_receipt(path, Receipt(clis=(_ENTRY,)))
    raw = json.loads(path.read_text())
    raw["clis"][0]["digest"] = 42
    # keep integrity in sync is impossible for the attacker without the
    # canonical form of the mutated field; a stale integrity is exactly the
    # CORRUPT trigger.
    path.write_text(json.dumps(raw))
    assert read_receipt(path).status is ReadStatus.CORRUPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_receipt_clis.py -v`
Expected: FAIL with `ImportError: cannot import name 'CliReceiptEntry'`

- [ ] **Step 3: Extend `receipt.py`**

Add after `ReceiptEntry`:

```python
@dataclass(frozen=True, slots=True)
class CliReceiptEntry:
    """One installer-deployed uv tool (spec §7). ``name`` is the registry /
    uv tool name; ``digest`` is ``cli_source_digest`` at deploy time."""

    name: str
    binary: str
    digest: str
```

Extend `Receipt` with the field (after `entries`):

```python
    clis: tuple[CliReceiptEntry, ...] = ()
```

In `canonical_bytes`, after building `payload` and before `json.dumps`, add:

```python
    # Included only when non-empty — a receipt written before this field
    # existed hashes byte-identically, so its persisted integrity still
    # validates (the dir_digest compatibility precedent, dict-key form).
    if receipt.clis:
        payload["clis"] = [
            [c.name, c.binary, c.digest] for c in sorted(receipt.clis, key=lambda c: c.name)
        ]
```

- [ ] **Step 4: Extend `receipt_store.py`**

In `to_json_obj`, before `return`-building, emit only when non-empty (add key after `"entries"`):

```python
    out: dict[str, object] = {
        "schema_version": receipt.schema_version,
        "integrity": receipt.integrity,
        "roots": [str(r) for r in receipt.roots],
        "entries": [_entry_to_json(e) for e in receipt.entries],
    }
    if receipt.clis:
        out["clis"] = [
            {"name": c.name, "binary": c.binary, "digest": c.digest} for c in receipt.clis
        ]
    return out
```

Add a parser + wire into `_receipt_from_json` (import `CliReceiptEntry` from `installer.core.receipt`):

```python
def _cli_entry_from_json(d: object) -> CliReceiptEntry:
    if not isinstance(d, dict):
        raise ValueError("cli entry is not an object")  # noqa: TRY003, TRY004  # caught -> CORRUPT
    name, binary, digest = d.get("name"), d.get("binary"), d.get("digest")
    # Non-string fields fail closed -> CORRUPT: a malformed entry must not
    # drive deploy/prune decisions (spec §7).
    if not (isinstance(name, str) and isinstance(binary, str) and isinstance(digest, str)):
        raise ValueError("cli entry name/binary/digest must be strings")  # noqa: TRY003
    return CliReceiptEntry(name=name, binary=binary, digest=digest)
```

In `_receipt_from_json`, after the roots validation, add:

```python
    clis_raw = data.get("clis", [])
    if not isinstance(clis_raw, list):
        raise ValueError("clis must be a list")  # noqa: TRY003  # caught -> CORRUPT
```

and extend the `Receipt(...)` construction with `clis=tuple(_cli_entry_from_json(c) for c in clis_raw),`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_receipt_clis.py tests/unit/test_receipt_store.py tests/unit/test_receipt.py -v`
Expected: all PASS (including the pre-existing receipt suites — the field is additive)

- [ ] **Step 6: Commit**

```bash
git add packages/installer/src/installer/core/receipt.py packages/installer/src/installer/core/receipt_store.py packages/installer/tests/unit/test_receipt_clis.py
git commit -m "feat(installer): additive Receipt.clis field, integrity-compatible (wgclw.9.9 T4)"
```

---

### Task 5: merge_clis rule + record_receipt/merge_receipt threading

**Files:**
- Modify: `packages/installer/src/installer/core/receipt_build.py`
- Modify: `packages/installer/src/installer/core/run.py` (record_receipt signature)
- Test: `packages/installer/tests/unit/test_receipt_clis.py` (append)

- [ ] **Step 1: Write the failing tests (append)**

```python
from installer.core.receipt_build import merge_clis


def _e(name: str, digest: str = "sha256:aa") -> CliReceiptEntry:
    return CliReceiptEntry(name=name, binary=name[0:4], digest=digest)


def test_merge_clis_union_rule() -> None:
    """
    Given prior entries {workcli, oldtool} and registry {workcli, prgroom}
    When this run deployed prgroom and uninstalled oldtool
    Then the merge keeps workcli's prior entry (skip retains), adds
    prgroom's new entry, and drops oldtool.

    Pins spec §7 union merge rule (registry -> new-if-deployed else
    retained; non-registry -> dropped iff uninstalled).
    """
    merged = merge_clis(
        prior_clis=(_e("workcli"), _e("oldtool")),
        registry_names=frozenset({"workcli", "prgroom"}),
        deployed={"prgroom": _e("prgroom", "sha256:new")},
        uninstalled_names={"oldtool"},
        relinquished_names=set(),
    )
    assert {c.name for c in merged} == {"workcli", "prgroom"}
    assert next(c for c in merged if c.name == "prgroom").digest == "sha256:new"


def test_merge_clis_declined_uninstall_retained_foreign_relinquished() -> None:
    """
    Given a retired entry whose uninstall was declined and a foreign entry
    When merged
    Then the declined one is retained (retried next prune) and the
    relinquished foreign one is dropped without uninstall.

    Pins spec §7 (decline retains; foreign names relinquished — item 10).
    """
    merged = merge_clis(
        prior_clis=(_e("oldtool"), _e("ruff")),
        registry_names=frozenset({"workcli"}),
        deployed={},
        uninstalled_names=set(),
        relinquished_names={"ruff"},
    )
    assert {c.name for c in merged} == {"oldtool"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_receipt_clis.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'merge_clis'`

- [ ] **Step 3: Implement in `receipt_build.py`**

Add import: `from installer.core.receipt import CliReceiptEntry` (extend the existing receipt import line). Add:

```python
def merge_clis(
    *,
    prior_clis: tuple[CliReceiptEntry, ...],
    registry_names: frozenset[str],
    deployed: dict[str, CliReceiptEntry],
    uninstalled_names: set[str],
    relinquished_names: set[str],
) -> tuple[CliReceiptEntry, ...]:
    """Union merge over registry CLIs and prior entries (spec §7).

    Registry CLI -> the new entry when this run deployed it, else the
    retained prior entry (skip/decline/failure keep the old record).
    Non-registry prior entry (retired) -> dropped iff its uninstall
    completed or it was relinquished (foreign name — never ours to
    uninstall), else retained so retirement is retried next prune."""
    prior_by_name = {c.name: c for c in prior_clis}
    out: list[CliReceiptEntry] = []
    for name in sorted(registry_names | set(prior_by_name)):
        if name in deployed:
            out.append(deployed[name])
        elif name in registry_names:
            if name in prior_by_name:
                out.append(prior_by_name[name])
        elif name not in uninstalled_names and name not in relinquished_names:
            out.append(prior_by_name[name])
    return tuple(out)
```

Extend `merge_receipt` with a keyword param `clis: tuple[CliReceiptEntry, ...] | None = None` and change its final construction to:

```python
    return Receipt(
        roots=roots,
        entries=tuple(by_path.values()),
        clis=prior.clis if clis is None else clis,
    )
```

(`None` → preserve prior unchanged: the `_run_project` path never passes it, so a project-local receipt's `clis` — none in practice — is untouched; spec §7.)

- [ ] **Step 4: Thread through `record_receipt` in `run.py`**

Change the signature (add after `relinquished_paths`):

```python
    cli_entries: tuple[CliReceiptEntry, ...] | None = None,
```

(import `CliReceiptEntry` from `installer.core.receipt` — extend the existing import) and change the `merge_receipt(...)` call to pass `clis=cli_entries`. The CALLER (`cli._run`, Task 11) computes the final tuple via `merge_clis` and passes it; `record_receipt` stays a dumb conduit.

- [ ] **Step 5: Run tests + the full receipt/run suites**

Run: `cd packages/installer && uv run pytest tests/unit/test_receipt_clis.py tests/unit/test_run_pipeline.py tests/unit/test_receipt_build.py -v` (if either named suite does not exist, run `uv run pytest tests/unit -k "receipt or run" -v`)
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add packages/installer/src/installer/core/receipt_build.py packages/installer/src/installer/core/run.py packages/installer/tests/unit/test_receipt_clis.py
git commit -m "feat(installer): merge_clis union rule + receipt threading (wgclw.9.9 T5)"
```

---

### Task 6: deploy_clis core decision engine (verify / heal / fresh)

**Files:**
- Modify: `packages/installer/src/installer/core/run.py`
- Test: `packages/installer/tests/unit/test_deploy_clis.py`

The engine processes `CLI_PACKAGES` in registry order. Signals per spec §6: "shim present" = `shim_path(binary) is not None`; "env present" = name in `tool_list()`; provenance = registered tool provides registered binary.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the deploy_clis decision engine (spec §6)."""

from pathlib import Path

from installer.core.clis import CliSpec, CommandResult, ScriptedCliDeploy
from installer.core.io_port import ScriptedIO
from installer.core.receipt import CliReceiptEntry, Receipt
from installer.core.run import deploy_clis

_SPEC = CliSpec("workcli", "packages/workcli", "work", ("--protocol-version",))
_OK = CommandResult(ok=True, output="")


def _pkg(tmp_path: Path) -> Path:
    pkg = tmp_path / "packages" / "workcli"
    (pkg / "src").mkdir(parents=True)
    (pkg / "pyproject.toml").write_bytes(b"[project]\n")
    (pkg / "src" / "m.py").write_bytes(b"pass")
    return pkg


def _prior_with_current_digest(tmp_path: Path) -> Receipt:
    from installer.core.clis import cli_source_digest

    digest = cli_source_digest(_pkg(tmp_path))
    return Receipt(clis=(CliReceiptEntry(name="workcli", binary="work", digest=digest),))


def test_verify_skip_smokes_and_skips(tmp_path: Path) -> None:
    """
    Given a receipt entry with the current digest, shim present, provenance
    proven, smoke passing
    When deploy_clis runs
    Then no install fires, the smoke ran against the absolute shim path,
    and the counter is skipped.

    Pins spec §6 verify row / item 1.
    """
    prior = _prior_with_current_digest(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[tmp_path / "bin"],
        shims=[shim],
        tool_lists=[{"workcli": frozenset({"work"})}],
        smokes=[_OK],
        whiches=[shim],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=ScriptedIO(), dry_run=False, auto_yes=True,
    )
    assert not outcome.any_failed
    assert outcome.counters["cli:workcli"].skipped == 1
    assert ("smoke", str(shim)) in deploy.transcript
    assert not any(t[0] == "tool_install" for t in deploy.transcript)


def test_verify_smoke_failure_heals_with_force(tmp_path: Path) -> None:
    """
    Given digest-equal receipt + shim present + provenance proven, but smoke
    failing
    When deploy_clis runs
    Then a force=True reinstall fires without a consent prompt, then
    re-smokes; the entry is refreshed.

    Pins spec §6 verify row heal-on-fail / item 1.
    """
    prior = _prior_with_current_digest(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[tmp_path / "bin"],
        shims=[shim, shim],  # decision read + post-install re-read
        tool_lists=[{"workcli": frozenset({"work"})}],
        smokes=[CommandResult(ok=False, output="boom"), _OK],
        installs=[_OK],
        whiches=[shim],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert not outcome.any_failed
    assert ("tool_install", str(tmp_path / "packages" / "workcli"), True) in deploy.transcript
    assert not any(e.channel == "confirm" for e in io.transcript)
    assert "workcli" in outcome.deployed


def test_heal_missing_shim_reinstalls_without_prompt(tmp_path: Path) -> None:
    """
    Given a receipt entry, shim missing, provenance showing our env provides
    the binary... or env absent entirely
    When deploy_clis runs
    Then it reinstalls without a prompt (created counter) — env absent uses
    force=False.

    Pins spec §6 heal row + provenance-absent exception / items 3, 19.
    """
    prior = _prior_with_current_digest(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[tmp_path / "bin"],
        shims=[None, shim],
        tool_lists=[{}],  # env absent entirely -> non-forcing heal
        installs=[_OK],
        smokes=[_OK],
        whiches=[shim],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].created == 1
    assert ("tool_install", str(tmp_path / "packages" / "workcli"), False) in deploy.transcript
    assert not any(e.channel == "confirm" for e in io.transcript)


def test_fresh_install_no_evidence_no_prompt(tmp_path: Path) -> None:
    """
    Given no receipt entry, no shim, tool_list proving the env absent
    When deploy_clis runs
    Then a force=False install fires with no prompt; created counter; entry
    recorded after smoke.

    Pins spec §6 fresh row / items 2, 18.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[tmp_path / "bin"],
        shims=[None, shim],
        tool_lists=[{}],
        installs=[_OK],
        smokes=[_OK],
        whiches=[shim],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=ScriptedIO(), dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].created == 1
    assert ("tool_install", str(tmp_path / "packages" / "workcli"), False) in deploy.transcript
    assert "workcli" in outcome.deployed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_deploy_clis.py -v`
Expected: FAIL with `ImportError: cannot import name 'deploy_clis'`

- [ ] **Step 3: Implement the engine skeleton in `run.py`**

Add imports: `from installer.core.clis import CliDeployPort, CliSpec, MIN_UV_VERSION, RETIRED_CLIS, cli_source_digest` and `from installer.core.consent import ConsentRequiredError, require_consent` and extend the receipt import with `CliReceiptEntry`.

```python
@dataclass(frozen=True, slots=True)
class CliDeployOutcome:
    """What the CLI deploy half did. ``deployed`` holds only this run's
    smoked-OK installs (keyed by registry name) — the merge rule retains
    prior entries for everything else. ``any_failed`` drives _run's exit
    code (spec §6 failure surfacing)."""

    deployed: dict[str, CliReceiptEntry]
    counters: dict[str, Counters]
    any_failed: bool


def deploy_clis(
    specs: tuple[CliSpec, ...],
    *,
    repo_root: Path,
    prior: Receipt,
    deploy: CliDeployPort,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
) -> CliDeployOutcome:
    """The CLI deploy half (spec §6): registry order, PATH-independent
    decision signals, consent on any unproven overwrite, reachability
    invariant per bin dir."""
    deployed: dict[str, CliReceiptEntry] = {}
    counters: dict[str, Counters] = {}
    any_failed = False

    version = deploy.uv_version()
    if version is None or version < MIN_UV_VERSION:
        need = ".".join(str(p) for p in MIN_UV_VERSION)
        got = ".".join(str(p) for p in version) if version else "unknown"
        io.err(
            f"CLI deploys need uv >= {need} (found {got}); "
            f"upgrade uv (e.g. `brew upgrade uv`) and re-run"
        )
        return CliDeployOutcome(deployed={}, counters={}, any_failed=True)

    prior_by_name = {c.name: c for c in prior.clis}
    tools = deploy.tool_list()
    reach_ok_dirs: set[Path] = set()  # memoized update-shell success per bin dir

    for spec in specs:
        target = f"cli:{spec.name}"
        counters[target] = Counters()
        package_dir = repo_root / spec.package_dir
        failed = _deploy_one(
            spec, package_dir=package_dir, prior_entry=prior_by_name.get(spec.name),
            tools=tools, deploy=deploy, io=io, dry_run=dry_run, auto_yes=auto_yes,
            deployed=deployed, c=counters[target],
        )
        any_failed = any_failed or failed
        if not dry_run and deploy.shim_path(spec.binary) is not None:
            ok = _check_reachability(
                spec.binary, deploy=deploy, io=io, auto_yes=auto_yes,
                resolved_dirs=reach_ok_dirs,
            )
            any_failed = any_failed or not ok
    return CliDeployOutcome(deployed=deployed, counters=counters, any_failed=any_failed)
```

`_deploy_one` (same module) implements the decision table for one CLI. Complete code:

```python
def _deploy_one(
    spec: CliSpec,
    *,
    package_dir: Path,
    prior_entry: CliReceiptEntry | None,
    tools: Mapping[str, frozenset[str]] | None,
    deploy: CliDeployPort,
    io: IOPort,
    dry_run: bool,
    auto_yes: bool,
    deployed: dict[str, CliReceiptEntry],
    c: Counters,
) -> bool:
    """Run the §6 decision table for one CLI. Returns True on failure."""
    digest = cli_source_digest(package_dir)
    shim = deploy.shim_path(spec.binary)
    env_present = tools is not None and spec.name in tools
    # Provenance: the registered env currently provides the registered
    # binary. Unproven (tools is None) is never provenance (spec §6).
    provenance = tools is not None and spec.binary in tools.get(spec.name, frozenset())
    evidence = shim is not None or env_present or tools is None

    if prior_entry is not None:
        if provenance or (tools is not None and not env_present and shim is None):
            # Owned per receipt AND (live provenance, or nothing there at
            # all — a user uninstall). Promptless paths.
            if shim is not None and prior_entry.digest == digest:
                if dry_run:
                    io.info(f"cli:{spec.name}: would skip (up to date)")
                    c.skipped += 1
                    return False
                smoke = deploy.smoke(shim, spec.smoke_args)
                if smoke.ok:
                    c.skipped += 1
                    return False
                io.warn(f"cli:{spec.name}: installed copy fails smoke; healing\n{smoke.output}")
                return _install(
                    spec, package_dir, digest, force=True, deploy=deploy, io=io,
                    dry_run=dry_run, deployed=deployed, c=c, counter_attr="created",
                )
            if shim is None:
                # Heal. force only when our env is provably still there.
                if dry_run:
                    io.info(f"cli:{spec.name}: would reinstall (shim missing)")
                    return False
                return _install(
                    spec, package_dir, digest, force=provenance, deploy=deploy, io=io,
                    dry_run=dry_run, deployed=deployed, c=c, counter_attr="created",
                )
            # shim present, digest differs -> upgrade (consent).
            return _consented_install(
                spec, package_dir, digest, prompt=f"Upgrade CLI '{spec.binary}' "
                f"({spec.name})?", deploy=deploy, io=io, dry_run=dry_run,
                auto_yes=auto_yes, deployed=deployed, c=c, counter_attr="updated",
                would="would upgrade",
            )
        # Receipt present but provenance mismatch (foreign env/shim) ->
        # takeover consent (spec §6 provenance precondition / item 19).
        return _consented_install(
            spec, package_dir, digest, prompt=f"Take over existing '{spec.binary}' "
            f"(not provably {spec.name}'s)?", deploy=deploy, io=io, dry_run=dry_run,
            auto_yes=auto_yes, deployed=deployed, c=c, counter_attr="updated",
            would="would take over",
        )

    if not evidence:
        # Fresh: non-forcing; an already-exists failure re-routes to
        # takeover consent (spec §6 fresh row / item 18).
        if dry_run:
            io.info(f"cli:{spec.name}: would install")
            return False
        result = deploy.tool_install(package_dir, force=False)
        if result.ok:
            return _finish_install(spec, digest, deploy=deploy, io=io, deployed=deployed,
                                   c=c, counter_attr="created")
        io.warn(f"cli:{spec.name}: install found existing state; asking to take over")
        return _consented_install(
            spec, package_dir, digest, prompt=f"Take over existing '{spec.binary}'?",
            deploy=deploy, io=io, dry_run=dry_run, auto_yes=auto_yes,
            deployed=deployed, c=c, counter_attr="updated", would="would take over",
        )
    return _consented_install(
        spec, package_dir, digest, prompt=f"Take over existing '{spec.binary}' "
        f"(manual install detected)?", deploy=deploy, io=io, dry_run=dry_run,
        auto_yes=auto_yes, deployed=deployed, c=c, counter_attr="updated",
        would="would take over",
    )
```

Shared helpers (same module — complete code):

```python
def _consented_install(
    spec: CliSpec, package_dir: Path, digest: str, *, prompt: str,
    deploy: CliDeployPort, io: IOPort, dry_run: bool, auto_yes: bool,
    deployed: dict[str, CliReceiptEntry], c: Counters, counter_attr: str, would: str,
) -> bool:
    if dry_run:
        io.info(f"cli:{spec.name}: {would}")
        return False
    require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
    if not auto_yes and not io.confirm(prompt, default=False):
        c.skipped += 1
        return False
    return _install(spec, package_dir, digest, force=True, deploy=deploy, io=io,
                    dry_run=dry_run, deployed=deployed, c=c, counter_attr=counter_attr)


def _install(
    spec: CliSpec, package_dir: Path, digest: str, *, force: bool,
    deploy: CliDeployPort, io: IOPort, dry_run: bool,
    deployed: dict[str, CliReceiptEntry], c: Counters, counter_attr: str,
) -> bool:
    result = deploy.tool_install(package_dir, force=force)
    if not result.ok:
        io.err(f"cli:{spec.name}: install failed\n{result.output}")
        return True
    return _finish_install(spec, digest, deploy=deploy, io=io, deployed=deployed,
                           c=c, counter_attr=counter_attr)


def _finish_install(
    spec: CliSpec, digest: str, *, deploy: CliDeployPort, io: IOPort,
    deployed: dict[str, CliReceiptEntry], c: Counters, counter_attr: str,
) -> bool:
    shim = deploy.shim_path(spec.binary)
    if shim is None:
        io.err(f"cli:{spec.name}: install reported ok but produced no shim")
        return True
    smoke = deploy.smoke(shim, spec.smoke_args)
    if not smoke.ok:
        io.err(f"cli:{spec.name}: smoke failed\n{smoke.output}")
        return True
    deployed[spec.name] = CliReceiptEntry(name=spec.name, binary=spec.binary, digest=digest)
    setattr(c, counter_attr, getattr(c, counter_attr) + 1)
    io.ok(f"cli:{spec.name}: deployed '{spec.binary}'")
    return False
```

`_check_reachability` is stubbed in this task (Task 9 completes it) as:

```python
def _check_reachability(
    binary: str, *, deploy: CliDeployPort, io: IOPort, auto_yes: bool,
    resolved_dirs: set[Path],
) -> bool:
    return True  # completed in Task 9 (reachability invariant)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_deploy_clis.py -v`
Expected: 4 PASS. Adjust ScriptedCliDeploy queue orders in tests if the engine's call order differs — the CONTRACT is the decision table, and the fake's queues must mirror the engine's actual read order (decision reads happen once per CLI, in table order).

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/run.py packages/installer/tests/unit/test_deploy_clis.py
git commit -m "feat(installer): deploy_clis decision engine — verify/heal/fresh (wgclw.9.9 T6)"
```

---

### Task 7: Consent paths — upgrade, takeover, TOCTOU re-route, provenance

**Files:**
- Test: `packages/installer/tests/unit/test_deploy_clis.py` (append; engine code from Task 6 already implements these paths — these tests pin them red-first if Task 6 was implemented minimally, or green-verify otherwise; if green immediately, verify each test fails when its branch is deliberately broken, then restore)

- [ ] **Step 1: Write the tests**

```python
def test_upgrade_consent_accept_and_decline(tmp_path: Path) -> None:
    """
    Given a receipt entry with a STALE digest, shim present, provenance ok
    When deploy_clis runs with an accepting (then declining) confirm
    Then accept -> force install + updated counter; decline -> skipped and
    no install.

    Pins spec §6 upgrade row / item 4.
    """
    pkg = _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    prior = Receipt(clis=(CliReceiptEntry(name="workcli", binary="work", digest="sha256:stale"),))

    def _deploy() -> ScriptedCliDeploy:
        return ScriptedCliDeploy(
            uv_versions=[(0, 10, 4)],
            bin_dirs=[tmp_path / "bin"],
            shims=[shim, shim],
            tool_lists=[{"workcli": frozenset({"work"})}],
            installs=[_OK],
            smokes=[_OK],
            whiches=[shim],
        )

    accept = _deploy()
    io = ScriptedIO(confirms=[True])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=accept,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].updated == 1
    assert ("tool_install", str(pkg), True) in accept.transcript

    decline = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"], shims=[shim],
        tool_lists=[{"workcli": frozenset({"work"})}], whiches=[shim],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=decline,
        io=ScriptedIO(confirms=[False]), dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].skipped == 1
    assert not any(t[0] == "tool_install" for t in decline.transcript)


def test_takeover_triggers_all_three_evidence_forms(tmp_path: Path) -> None:
    """
    Given no receipt entry, and (a) shim present, (b) env present shimless,
    (c) tool_list None
    When deploy_clis runs with declining confirms
    Then each form prompts for takeover and no install fires on decline.

    Pins spec §6 takeover row / item 5.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    cases = [
        {"shims": [shim], "tool_lists": [{}]},
        {"shims": [None], "tool_lists": [{"workcli": frozenset({"work"})}]},
        {"shims": [None], "tool_lists": [None]},
    ]
    for case in cases:
        deploy = ScriptedCliDeploy(
            uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"], **case,
        )
        io = ScriptedIO(confirms=[False])
        outcome = deploy_clis(
            (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
            io=io, dry_run=False, auto_yes=False,
        )
        assert outcome.counters["cli:workcli"].skipped == 1, case
        assert any(e.channel == "confirm" for e in io.transcript), case
        assert not any(t[0] == "tool_install" for t in deploy.transcript), case


def test_fresh_toctou_already_exists_reroutes_to_takeover(tmp_path: Path) -> None:
    """
    Given a clean fresh decision whose non-forcing install fails (tool
    appeared concurrently)
    When deploy_clis runs with an accepting confirm
    Then a takeover consent fires and the retry uses force=True.

    Pins spec §6 fresh row TOCTOU re-route / item 18.
    """
    pkg = _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[tmp_path / "bin"],
        shims=[None, shim],
        tool_lists=[{}],
        installs=[CommandResult(ok=False, output="already installed"), _OK],
        smokes=[_OK],
        whiches=[shim],
    )
    io = ScriptedIO(confirms=[True])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    installs = [t for t in deploy.transcript if t[0] == "tool_install"]
    assert installs == [("tool_install", str(pkg), False), ("tool_install", str(pkg), True)]
    assert outcome.counters["cli:workcli"].updated == 1


def test_stale_receipt_foreign_provenance_requires_takeover(tmp_path: Path) -> None:
    """
    Given a receipt entry but tool_list showing a DIFFERENT tool providing
    'work' (our env gone)
    When deploy_clis runs with a declining confirm
    Then no promptless heal fires — takeover consent, decline skips.

    Pins spec §6 provenance precondition / item 19.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    prior = _prior_with_current_digest(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"], shims=[shim],
        tool_lists=[{"other-tool": frozenset({"work"})}], whiches=[shim],
    )
    io = ScriptedIO(confirms=[False])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=prior, deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.counters["cli:workcli"].skipped == 1
    assert not any(t[0] == "tool_install" for t in deploy.transcript)
```

- [ ] **Step 2: Run; make green**

Run: `cd packages/installer && uv run pytest tests/unit/test_deploy_clis.py -v`
Expected: PASS if Task 6's engine is complete. For each test that passes immediately, mutate its branch (e.g. flip `force=False` to `True` in the fresh path) and re-run to confirm the test catches it; revert the mutation. Fix any behavioral gaps the tests expose (queue-order mismatches are test bugs; decision-table mismatches are engine bugs).

- [ ] **Step 3: Commit**

```bash
git add packages/installer/tests/unit/test_deploy_clis.py packages/installer/src/installer/core/run.py
git commit -m "test(installer): deploy_clis consent/TOCTOU/provenance branches (wgclw.9.9 T7)"
```

---

### Task 8: Failure paths + dry-run preview

**Files:**
- Test: `packages/installer/tests/unit/test_deploy_clis.py` (append)

- [ ] **Step 1: Write the tests**

```python
def test_smoke_failure_after_install_fails_run_no_entry(tmp_path: Path) -> None:
    """
    Given a fresh install whose post-install smoke fails
    When deploy_clis runs
    Then any_failed is True, err carries the smoke output, and no deployed
    entry is recorded (next run retries).

    Pins spec §6 failure surfacing / item 7.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"],
        shims=[None, shim], tool_lists=[{}],
        installs=[_OK], smokes=[CommandResult(ok=False, output="kaboom")],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed and "workcli" not in outcome.deployed
    assert any(e.channel == "err" and "kaboom" in e.message for e in io.transcript)


def test_install_ok_but_no_shim_is_failure(tmp_path: Path) -> None:
    """
    Given an install that reports ok but produces no shim
    When deploy_clis runs
    Then it is a failure (err), not a silent success.

    Pins spec §6 / item 7 (install-ok-but-no-shim).
    """
    _pkg(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"],
        shims=[None, None], tool_lists=[{}], installs=[_OK],
    )
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=ScriptedIO(), dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed


def test_one_broken_cli_does_not_block_the_other(tmp_path: Path) -> None:
    """
    Given two registry CLIs where the first's install fails
    When deploy_clis runs
    Then the second still processes and any_failed is True.

    Pins spec §6/§8: record-and-continue, exit 1 at the end / item 8.
    """
    pkg2 = tmp_path / "packages" / "prgroom"
    (pkg2 / "src").mkdir(parents=True)
    (pkg2 / "pyproject.toml").write_bytes(b"[project]\n")
    _pkg(tmp_path)
    spec2 = CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",))
    shim2 = tmp_path / "bin" / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"] * 2,
        shims=[None, None, shim2], tool_lists=[{}],
        installs=[CommandResult(ok=False, output="resolver exploded"),
                  CommandResult(ok=False, output="second consent decline needed"), _OK],
        smokes=[_OK], whiches=[shim2],
    )
    io = ScriptedIO(confirms=[False])
    outcome = deploy_clis(
        (_SPEC, spec2), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed
    assert "prgroom" in outcome.deployed


def test_dry_run_previews_without_subprocess(tmp_path: Path) -> None:
    """
    Given a fresh-install state under --dry-run
    When deploy_clis runs
    Then it reports would-install and never calls
    tool_install/smoke/update_shell.

    Pins spec §6 dry-run / item 6.
    """
    _pkg(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"],
        shims=[None], tool_lists=[{}],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=True, auto_yes=False,
    )
    assert not outcome.any_failed
    assert any("would install" in e.message for e in io.transcript)
    assert not any(t[0] in ("tool_install", "smoke", "update_shell") for t in deploy.transcript)
```

Note: the first-install-failure path in `test_one_broken_cli_does_not_block_the_other` triggers the TOCTOU re-route (non-forcing install failed), which prompts takeover; the declining confirm resolves it as skipped-with-failure — the queue shapes above assume that flow. If the engine's read order differs, fix the QUEUES, not the contract assertions.

- [ ] **Step 2: Run; make green (fix engine only for contract violations)**

Run: `cd packages/installer && uv run pytest tests/unit/test_deploy_clis.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add packages/installer/tests/unit/test_deploy_clis.py packages/installer/src/installer/core/run.py
git commit -m "test(installer): deploy_clis failure + dry-run branches (wgclw.9.9 T8)"
```

---

### Task 9: uv version guard + reachability invariant

**Files:**
- Modify: `packages/installer/src/installer/core/run.py` (complete `_check_reachability`)
- Test: `packages/installer/tests/unit/test_deploy_clis.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
def test_uv_version_guard_blocks_all_cli_work(tmp_path: Path) -> None:
    """
    Given uv older than MIN_UV_VERSION (or unparseable)
    When deploy_clis runs
    Then one actionable err fires, zero install/uninstall/update_shell
    calls happen, and any_failed is True.

    Pins spec §6 version guard / item 21.
    """
    for version in [(0, 9, 0), None]:
        deploy = ScriptedCliDeploy(uv_versions=[version])
        io = ScriptedIO()
        outcome = deploy_clis(
            (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
            io=io, dry_run=False, auto_yes=True,
        )
        assert outcome.any_failed
        assert any(e.channel == "err" and "uv" in e.message for e in io.transcript)
        assert not any(
            t[0] in ("tool_install", "tool_uninstall", "update_shell")
            for t in deploy.transcript
        )


def test_reachability_which_none_update_shell_consent(tmp_path: Path) -> None:
    """
    Given a deployed CLI whose binary which() cannot find
    When the invariant runs with an accepting confirm and update_shell ok
    Then the run resolves (not failed) with an info notice; decline instead
    -> err + failure.

    Pins spec §6 reachability / item 9.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"

    def _fresh_deploy(update_ok: bool) -> ScriptedCliDeploy:
        return ScriptedCliDeploy(
            uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"] * 2,
            shims=[None, shim, shim], tool_lists=[{}], installs=[_OK], smokes=[_OK],
            whiches=[None],
            update_shells=[CommandResult(ok=update_ok, output="")],
        )

    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(),
        deploy=_fresh_deploy(True), io=ScriptedIO(confirms=[True]),
        dry_run=False, auto_yes=False,
    )
    assert not outcome.any_failed

    io = ScriptedIO(confirms=[False])
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(),
        deploy=ScriptedCliDeploy(
            uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"] * 2,
            shims=[None, shim, shim], tool_lists=[{}], installs=[_OK], smokes=[_OK],
            whiches=[None],
        ),
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed
    assert any(e.channel == "err" and "PATH" in e.message for e in io.transcript)


def test_reachability_shadow_is_hard_error(tmp_path: Path) -> None:
    """
    Given which() resolving OUTSIDE bin_dir (foreign shadow)
    When the invariant runs
    Then err names both paths and the run fails; update_shell is never
    offered (it cannot fix PATH order).

    Pins spec §6 shadowing / item 9.
    """
    _pkg(tmp_path)
    shim = tmp_path / "bin" / "work"
    foreign = tmp_path / "other" / "work"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"] * 2,
        shims=[None, shim, shim], tool_lists=[{}], installs=[_OK], smokes=[_OK],
        whiches=[foreign],
    )
    io = ScriptedIO()
    outcome = deploy_clis(
        (_SPEC,), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert outcome.any_failed
    assert any(
        e.channel == "err" and str(foreign) in e.message and str(shim) in e.message
        for e in io.transcript
    )
    assert not any(t[0] == "update_shell" for t in deploy.transcript)


def test_reachability_memoized_per_bin_dir(tmp_path: Path) -> None:
    """
    Given two CLIs sharing one bin_dir, PATH unconfigured
    When deploy_clis runs with ONE accepting confirm
    Then update_shell runs exactly once and the second CLI reuses the
    memoized success (no second prompt, no failure).

    Pins spec §6 memoization / item 20.
    """
    pkg2 = tmp_path / "packages" / "prgroom"
    (pkg2 / "src").mkdir(parents=True)
    (pkg2 / "pyproject.toml").write_bytes(b"[project]\n")
    _pkg(tmp_path)
    spec2 = CliSpec("prgroom", "packages/prgroom", "prgroom", ("--help",))
    shim1, shim2 = tmp_path / "bin" / "work", tmp_path / "bin" / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"] * 4,
        shims=[None, shim1, shim1, None, shim2, shim2], tool_lists=[{}],
        installs=[_OK, _OK], smokes=[_OK, _OK], whiches=[None, None],
        update_shells=[CommandResult(ok=True, output="")],
    )
    io = ScriptedIO(confirms=[True])
    outcome = deploy_clis(
        (_SPEC, spec2), repo_root=tmp_path, prior=Receipt(), deploy=deploy,
        io=io, dry_run=False, auto_yes=False,
    )
    assert not outcome.any_failed
    assert sum(1 for t in deploy.transcript if t[0] == "update_shell") == 1
    assert sum(1 for e in io.transcript if e.channel == "confirm") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_deploy_clis.py -v`
Expected: new tests FAIL (reachability stub returns True; version guard exists from Task 6 — its test should already pass; if so, mutate-verify it as in Task 7)

- [ ] **Step 3: Complete `_check_reachability`**

```python
def _check_reachability(
    binary: str, *, deploy: CliDeployPort, io: IOPort, auto_yes: bool,
    resolved_dirs: set[Path],
) -> bool:
    """PATH-reachability invariant (spec §6): a property of the bin dir,
    evaluated once per dir per run; update-shell repair memoized. Returns
    False only on a genuine deployment failure."""
    bin_dir = deploy.bin_dir()
    found = deploy.which(binary)
    if found is not None:
        if found.parent == bin_dir:
            return True
        shim = bin_dir / binary
        io.err(
            f"'{binary}' on PATH resolves to {found}, shadowing the deployed {shim}; "
            "remove/rename the foreign binary or reorder PATH"
        )
        return False
    if bin_dir in resolved_dirs:
        return True
    accepted = auto_yes or (
        io.is_interactive()
        and io.confirm(f"{bin_dir} is not on PATH — run `uv tool update-shell`?", default=False)
    )
    if accepted:
        result = deploy.update_shell()
        if result.ok:
            resolved_dirs.add(bin_dir)
            io.info(f"PATH updated for new shells (restart or re-source to pick up {bin_dir})")
            return True
        io.err(f"uv tool update-shell failed:\n{result.output}")
    io.err(f'{bin_dir} is not on PATH; add it (e.g. export PATH="{bin_dir}:$PATH")')
    return False
```

Note the decline path falls through to the final `io.err` + `False` — one message serves both decline and repair-failure, always naming the exact PATH line (spec §6).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_deploy_clis.py -v`
Expected: all PASS (adjust fake queue orders only, never assertions)

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/run.py packages/installer/tests/unit/test_deploy_clis.py
git commit -m "feat(installer): uv version guard + PATH-reachability invariant (wgclw.9.9 T9)"
```

---

### Task 10: prune_clis (retirement, allowlist, relinquish)

**Files:**
- Modify: `packages/installer/src/installer/core/run.py`
- Test: `packages/installer/tests/unit/test_prune_clis.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the CLI prune half (spec §7, item 10)."""

from pathlib import Path

from installer.core.clis import CommandResult, ScriptedCliDeploy
from installer.core.io_port import ScriptedIO
from installer.core.receipt import CliReceiptEntry, Receipt
from installer.core.run import prune_clis

_OK = CommandResult(ok=True, output="")


def _prior(*names: str) -> Receipt:
    return Receipt(
        clis=tuple(CliReceiptEntry(name=n, binary=n[:4], digest="sha256:aa") for n in names)
    )


def test_retired_allowlisted_cli_uninstalled_with_consent() -> None:
    """
    Given a prior entry not in the registry but in RETIRED_CLIS
    When prune_clis runs with an accepting confirm
    Then uv tool uninstall fires, pruned counter increments, and the name
    lands in uninstalled_names.

    Pins spec §7 / item 10.
    """
    deploy = ScriptedCliDeploy(uninstalls=[_OK])
    io = ScriptedIO(confirms=[True])
    outcome = prune_clis(
        _prior("oldtool"), registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}), deploy=deploy, io=io,
        dry_run=False, auto_yes=False,
    )
    assert outcome.uninstalled_names == {"oldtool"}
    assert outcome.counters["cli:oldtool"].pruned == 1
    assert ("tool_uninstall", "oldtool") in deploy.transcript


def test_declined_uninstall_retains_entry() -> None:
    """
    Given a retired allowlisted entry and a declining confirm
    When prune_clis runs
    Then no uninstall fires and the name is NOT in uninstalled_names
    (retirement retried next prune).

    Pins spec §7 decline / item 10.
    """
    deploy = ScriptedCliDeploy()
    outcome = prune_clis(
        _prior("oldtool"), registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}), deploy=deploy,
        io=ScriptedIO(confirms=[False]), dry_run=False, auto_yes=False,
    )
    assert outcome.uninstalled_names == set()
    assert not any(t[0] == "tool_uninstall" for t in deploy.transcript)


def test_foreign_name_never_uninstalled_relinquished_instead() -> None:
    """
    Given a prior entry naming a tool outside CLI_PACKAGES | RETIRED_CLIS
    (e.g. a tampered receipt naming 'ruff')
    When prune_clis runs with auto_yes
    Then NO uninstall fires even under --yes; the name is warned about and
    relinquished.

    Pins spec §7 closed uninstall authority / item 10 (tampered receipt).
    """
    deploy = ScriptedCliDeploy()
    io = ScriptedIO()
    outcome = prune_clis(
        _prior("ruff"), registry_names=frozenset({"workcli"}),
        retired=frozenset(), deploy=deploy, io=io, dry_run=False, auto_yes=True,
    )
    assert outcome.relinquished_names == {"ruff"}
    assert outcome.uninstalled_names == set()
    assert not any(t[0] == "tool_uninstall" for t in deploy.transcript)
    assert any(e.channel == "warn" and "ruff" in e.message for e in io.transcript)


def test_uninstall_of_absent_tool_counts_as_success() -> None:
    """
    Given a retired entry whose uv uninstall fails with 'not installed'
    When prune_clis runs (auto_yes)
    Then the outcome treats it as uninstalled (desired state: absent).

    Pins spec §7 / item 10.
    """
    deploy = ScriptedCliDeploy(
        uninstalls=[CommandResult(ok=False, output="`oldtool` is not installed")]
    )
    outcome = prune_clis(
        _prior("oldtool"), registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}), deploy=deploy, io=ScriptedIO(),
        dry_run=False, auto_yes=True,
    )
    assert outcome.uninstalled_names == {"oldtool"}


def test_dry_run_previews_no_uninstall() -> None:
    """
    Given a retired allowlisted entry under --dry-run
    When prune_clis runs
    Then it reports would-uninstall and calls nothing.

    Pins spec §7 dry-run / item 10.
    """
    deploy = ScriptedCliDeploy()
    io = ScriptedIO()
    outcome = prune_clis(
        _prior("oldtool"), registry_names=frozenset({"workcli"}),
        retired=frozenset({"oldtool"}), deploy=deploy, io=io,
        dry_run=True, auto_yes=False,
    )
    assert outcome.uninstalled_names == set()
    assert any("would uninstall" in e.message for e in io.transcript)
    assert not deploy.transcript or not any(
        t[0] == "tool_uninstall" for t in deploy.transcript
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_prune_clis.py -v`
Expected: FAIL with `ImportError: cannot import name 'prune_clis'`

- [ ] **Step 3: Implement in `run.py`**

```python
@dataclass(frozen=True, slots=True)
class CliPruneOutcome:
    """CLI prune half result: names whose uninstall completed (drop from the
    receipt), names relinquished (foreign — drop without uninstall), and
    per-target counters."""

    uninstalled_names: set[str]
    relinquished_names: set[str]
    counters: dict[str, Counters]


def prune_clis(
    prior: Receipt,
    *,
    registry_names: frozenset[str],
    retired: frozenset[str],
    deploy: CliDeployPort,
    io: IOPort,
    dry_run: bool = False,
    auto_yes: bool = False,
) -> CliPruneOutcome:
    """Retire prior CLI entries no longer in the registry (spec §7).

    Uninstall authority is bounded by ``registry_names | retired`` — the
    receipt's integrity digest is tamper-evidence, not authentication, so a
    foreign name is warned about and relinquished, never uninstalled."""
    uninstalled: set[str] = set()
    relinquished: set[str] = set()
    counters: dict[str, Counters] = {}
    for entry in prior.clis:
        if entry.name in registry_names:
            continue
        target = f"cli:{entry.name}"
        counters.setdefault(target, Counters())
        if entry.name not in retired:
            io.warn(
                f"receipt names CLI '{entry.name}' which this installer never shipped; "
                "dropping the record without uninstalling"
            )
            relinquished.add(entry.name)
            continue
        if dry_run:
            io.info(f"cli:{entry.name}: would uninstall (retired)")
            continue
        require_consent(io, dry_run=dry_run, auto_yes=auto_yes)
        if not auto_yes and not io.confirm(
            f"Uninstall retired CLI '{entry.name}' ({entry.binary})?", default=False
        ):
            continue
        result = deploy.tool_uninstall(entry.name)
        if result.ok or "not installed" in result.output:
            uninstalled.add(entry.name)
            counters[target].pruned += 1
        else:
            io.err(f"cli:{entry.name}: uninstall failed\n{result.output}")
    return CliPruneOutcome(
        uninstalled_names=uninstalled, relinquished_names=relinquished, counters=counters
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/installer && uv run pytest tests/unit/test_prune_clis.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/run.py packages/installer/tests/unit/test_prune_clis.py
git commit -m "feat(installer): prune_clis — allowlist-bounded retirement (wgclw.9.9 T10)"
```

---### Task 11: cli.py wiring (injection, stage calls, exit flag, receipt threading)

**Files:**
- Modify: `packages/installer/src/installer/cli.py`
- Test: `packages/installer/tests/unit/test_cli_deploy_wiring.py`

- [ ] **Step 1: Write the failing tests**

The wiring tests drive `main()` end-to-end with a hermetic repo (copy the `_hermetic_repo` helper pattern from `test_cli_smoke.py:86` — reproduce it locally in this file, do not import across test modules) plus a `packages/workcli`-shaped package dir added to the hermetic repo, `io=ScriptedIO(interactive=False)`, and `cli_deploy=ScriptedCliDeploy(...)`.

```python
"""End-to-end wiring tests: main() drives the CLI deploy stage (spec §6/§7)."""

import json
from pathlib import Path

from installer.cli import main
from installer.core.clis import CommandResult, ScriptedCliDeploy
from installer.core.io_port import ScriptedIO
from installer.core.receipt import CliReceiptEntry, Receipt
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt

_OK = CommandResult(ok=True, output="")

# _hermetic_repo(tmp_path): reproduce the builder from test_cli_smoke.py:86
# (src/user/.agents tree + .installignore + profiles.toml), then add BOTH
# registry package dirs so cli_source_digest resolves:
#   for pkg in ("workcli", "prgroom"):
#       (repo / "packages" / pkg / "src").mkdir(parents=True)
#       (repo / "packages" / pkg / "pyproject.toml").write_bytes(b"[project]\n")
#       (repo / "packages" / pkg / "src" / "m.py").write_bytes(b"pass")


def test_full_install_deploys_both_clis_and_records_receipt(tmp_path: Path) -> None:
    """
    Given a hermetic repo and a fresh home
    When main(["--tools=claude", "--yes"]) runs with a scripted deploy port
    Then exit 0, both CLIs deploy, and the receipt carries both clis
    entries.

    Pins spec §6+§7 wiring: stage runs inside the lock, entries thread
    through record_receipt/merge_receipt (item 11 second half).
    """
    repo = _hermetic_repo(tmp_path)
    bin_dir = tmp_path / "bin"
    w, p = bin_dir / "work", bin_dir / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)],
        bin_dirs=[bin_dir] * 4,
        shims=[None, w, w, None, p, p],
        tool_lists=[{}],
        installs=[_OK, _OK],
        smokes=[_OK, _OK],
        whiches=[w, p],
    )
    rc = main(
        ["--tools=claude", "--yes"], home=tmp_path / "home",
        io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=deploy,
    )
    assert rc == 0
    result = read_receipt(tmp_path / "home" / ".config" / "agents-config" / "install-receipt.json")
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    assert {c.name for c in result.receipt.clis} == {"workcli", "prgroom"}


def test_deploy_failure_exits_1_after_summary(tmp_path: Path) -> None:
    """
    Given a deploy whose install fails
    When main runs
    Then exit 1, and the summary still rendered (Done./up-to-date line in
    transcript AFTER the err).

    Pins spec §6 failure surfacing: exit flag carried out of the lock.
    """
    repo = _hermetic_repo(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"] * 2,
        shims=[None, None], tool_lists=[{}],
        installs=[CommandResult(ok=False, output="x"), CommandResult(ok=False, output="x")],
    )
    io = ScriptedIO(interactive=False)
    rc = main(
        ["--tools=claude", "--yes"], home=tmp_path / "home",
        io=io, repo_root=repo, cli_deploy=deploy,
    )
    assert rc == 1
    err_idx = next(i for i, e in enumerate(io.transcript) if e.channel == "err")
    ok_idx = next(i for i, e in enumerate(io.transcript) if e.channel == "ok")
    assert err_idx < ok_idx  # summary rendered after the failure was recorded


def test_prune_only_drops_retired_cli_through_real_receipt_path(tmp_path: Path) -> None:
    """
    Given a prior receipt with a retired-allowlisted CLI entry
    When main(["--prune-only", "--yes"]) runs
    Then the deploy half never fires, the uninstall does, and the rewritten
    receipt no longer carries the entry.

    Pins spec §7 --prune-only convergence / item 10. NOTE: requires a
    nonzero RETIRED_CLIS in the test — monkeypatch installer.core.run's
    retired source or pass through a seam; the implementer wires
    prune_clis(retired=frozenset(RETIRED_CLIS)) in cli.py, so monkeypatch
    installer.cli.RETIRED_CLIS (import it into cli.py namespace for
    patchability).
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    receipt_path = home / ".config" / "agents-config" / "install-receipt.json"
    write_receipt(
        receipt_path,
        Receipt(clis=(CliReceiptEntry(name="oldtool", binary="old", digest="sha256:aa"),)),
    )
    deploy = ScriptedCliDeploy(uv_versions=[(0, 10, 4)], uninstalls=[_OK])
    import installer.cli as cli_mod

    # simulate a future retirement
    orig = cli_mod.RETIRED_CLIS
    cli_mod.RETIRED_CLIS = ("oldtool",)
    try:
        rc = main(
            ["--tools=claude", "--prune-only", "--yes"], home=home,
            io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=deploy,
        )
    finally:
        cli_mod.RETIRED_CLIS = orig
    assert rc == 0
    result = read_receipt(receipt_path)
    assert result.receipt is not None and result.receipt.clis == ()
    assert not any(t[0] == "tool_install" for t in deploy.transcript)


def test_second_noop_run_skips_via_persisted_clis(tmp_path: Path) -> None:
    """
    Given a first successful deploy run
    When a second identical run executes
    Then the second run smokes-and-skips (no tool_install) — the clis
    entries persisted through the real path.

    Pins item 11 (second no-op run converges).
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    w, p = bin_dir / "work", bin_dir / "prgroom"

    def _first() -> ScriptedCliDeploy:
        return ScriptedCliDeploy(
            uv_versions=[(0, 10, 4)], bin_dirs=[bin_dir] * 4,
            shims=[None, w, w, None, p, p], tool_lists=[{}],
            installs=[_OK, _OK], smokes=[_OK, _OK], whiches=[w, p],
        )

    assert main(["--tools=claude", "--yes"], home=home,
                io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=_first()) == 0
    second = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[bin_dir] * 4,
        shims=[w, w, p, p],
        tool_lists=[{"workcli": frozenset({"work"}), "prgroom": frozenset({"prgroom"})}],
        smokes=[_OK, _OK], whiches=[w, p],
    )
    assert main(["--tools=claude", "--yes"], home=home,
                io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=second) == 0
    assert not any(t[0] == "tool_install" for t in second.transcript)


def test_project_run_no_deploys_and_clis_untouched(tmp_path: Path) -> None:
    """
    Given a --project run against a project dir with a persisted profile
    When main runs with a scripted deploy port loaded with NOTHING
    Then no port method is called (empty queues never pop) and a
    pre-existing project receipt's clis (synthetic) is untouched.

    Pins spec §6 --project exclusion / item 13.
    """
    repo = _hermetic_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "project-config.toml").write_text('[install]\nprofiles = ["full"]\n')
    deploy = ScriptedCliDeploy()  # any call would raise queue-exhausted
    rc = main(
        ["--project", str(project), "--yes"], home=tmp_path / "home",
        io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=deploy,
    )
    assert rc == 0
    assert deploy.transcript == []


def test_corrupt_receipt_deploy_not_persisted(tmp_path: Path) -> None:
    """
    Given a corrupt prior receipt
    When main runs and the deploy succeeds (takeover consented via --yes)
    Then the receipt file is left untouched (still corrupt) — the deploy is
    not persisted.

    Pins spec §7 corrupt-receipt consequence / item 14.
    """
    repo = _hermetic_repo(tmp_path)
    home = tmp_path / "home"
    receipt_path = home / ".config" / "agents-config" / "install-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("{not json")
    bin_dir = tmp_path / "bin"
    w, p = bin_dir / "work", bin_dir / "prgroom"
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[bin_dir] * 4,
        shims=[None, w, w, None, p, p], tool_lists=[None],  # unproven -> takeover
        installs=[_OK, _OK], smokes=[_OK, _OK], whiches=[w, p],
    )
    rc = main(["--tools=claude", "--yes"], home=home,
              io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=deploy)
    assert rc == 0
    assert receipt_path.read_text() == "{not json"
```

Also add a no-TTY test (item 12): fresh state needing takeover consent, `interactive=False`, NO `--yes` → `rc == 1` (ConsentRequiredError path).

```python
def test_no_tty_without_yes_at_cli_consent_exits_1(tmp_path: Path) -> None:
    """
    Given a takeover-consent state on a non-interactive session without
    --yes (and without --dry-run)
    When main runs
    Then exit 1 via the ConsentRequiredError convention.

    Pins spec §6 no-TTY / item 12.
    """
    repo = _hermetic_repo(tmp_path)
    deploy = ScriptedCliDeploy(
        uv_versions=[(0, 10, 4)], bin_dirs=[tmp_path / "bin"],
        shims=[tmp_path / "bin" / "work"], tool_lists=[{}],
    )
    rc = main(["--tools=claude"], home=tmp_path / "home",
              io=ScriptedIO(interactive=False), repo_root=repo, cli_deploy=deploy)
    assert rc == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/installer && uv run pytest tests/unit/test_cli_deploy_wiring.py -v`
Expected: FAIL with `TypeError: main() got an unexpected keyword argument 'cli_deploy'`

- [ ] **Step 3: Wire `cli.py`**

1. Imports: `from installer.core.clis import CLI_PACKAGES, RETIRED_CLIS, CliDeployPort` and extend the run import with `deploy_clis, prune_clis`; extend receipt_build import (new) with `from installer.core.receipt_build import merge_clis`.
2. `main()` and `_run()` gain keyword `cli_deploy: CliDeployPort | None = None`; `main` forwards it. In `_run`, after the `io` default block:

```python
    if cli_deploy is None:
        from installer.core.clis import UvCliDeploy

        cli_deploy = UvCliDeploy()
```

3. Inside the lock, extend the `if not args.prune_only:` block after `install_plugin_routes` (inside the same `try`, so `ConsentRequiredError` → `return 1` is shared):

```python
                    cli_outcome = deploy_clis(
                        CLI_PACKAGES,
                        repo_root=resolved_repo_root,
                        prior=prior,
                        deploy=cli_deploy,
                        io=io,
                        dry_run=args.dry_run,
                        auto_yes=config.auto_yes,
                    )
                    _merge_into(counters, cli_outcome.counters)
```

Declare `cli_outcome: CliDeployOutcome | None = None` before the lock (import `CliDeployOutcome` from run) and assign inside; also declare `cli_prune: CliPruneOutcome | None = None`.

4. In the prune branch (`if (args.prune or args.prune_only) and not receipt_corrupt:`), after the file `prune_pipeline` result handling and inside the same `try` (PruneAbortedError untouched), add:

```python
                cli_prune = prune_clis(
                    prior,
                    registry_names=frozenset(s.name for s in CLI_PACKAGES),
                    retired=frozenset(RETIRED_CLIS),
                    deploy=cli_deploy,
                    io=io,
                    dry_run=args.dry_run,
                    auto_yes=config.auto_yes,
                )
                _merge_into(counters, cli_prune.counters)
```

Wrap it in its own `try/except ConsentRequiredError: return 1` if it is outside the install-half try block (it is — mirror the convention).

5. Before `record_receipt`, compute the merged tuple:

```python
            if not args.dry_run and not receipt_corrupt:
                cli_entries = merge_clis(
                    prior_clis=prior.clis,
                    registry_names=frozenset(s.name for s in CLI_PACKAGES),
                    deployed=cli_outcome.deployed if cli_outcome else {},
                    uninstalled_names=cli_prune.uninstalled_names if cli_prune else set(),
                    relinquished_names=cli_prune.relinquished_names if cli_prune else set(),
                )
                record_receipt(
                    receipt_path,
                    prior=prior,
                    dest_roots=dest_roots,
                    home=resolved_home,
                    tool_outcomes=tool_outcomes,
                    plugin_outcomes=plugin_outcomes,
                    pruned_paths=pruned_paths,
                    relinquished_paths=relinquished_paths,
                    cli_entries=cli_entries,
                )
```

6. Exit flag: after the summary `render_summary(...)` call, before the project-notice block:

```python
    if cli_outcome is not None and cli_outcome.any_failed:
        return 1
```

7. `_run_project` is untouched (its `record_receipt` call omits `cli_entries` → `None` → prior preserved; it never constructs a port — the injected `cli_deploy` is simply unused on that path; `_run` forks to `_run_project` BEFORE constructing the default `UvCliDeploy`, so move the default-construction after the `--project` fork to keep the project path subprocess-free).

- [ ] **Step 4: Run the wiring tests + full unit suite**

Run: `cd packages/installer && uv run pytest tests/unit -v`
Expected: all PASS — with one required hermeticity fix first. Pre-existing cli smoke tests call `main()` without `cli_deploy`, so the lazily-constructed default `UvCliDeploy` would shell out to real uv on their full-install paths. Keep them hermetic by neutralizing the STAGE (not the port — any port stub either fails the version guard, breaking those tests with exit 1, or reaches a real `tool_install`): add an autouse fixture to `tests/unit/conftest.py` that patches `installer.cli.deploy_clis` and `installer.cli.prune_clis` to no-op outcomes, with a `cli_deploy` marker opt-out for the wiring tests:

```python
@pytest.fixture(autouse=True)
def _neutralize_cli_deploys(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Keep pre-existing full-install tests hermetic (no uv subprocesses).
    Deploy-stage tests opt out with @pytest.mark.cli_deploy."""
    if request.node.get_closest_marker("cli_deploy"):
        return
    from installer.core.run import CliDeployOutcome, CliPruneOutcome

    monkeypatch.setattr(
        "installer.cli.deploy_clis",
        lambda *a, **k: CliDeployOutcome(deployed={}, counters={}, any_failed=False),
    )
    monkeypatch.setattr(
        "installer.cli.prune_clis",
        lambda *a, **k: CliPruneOutcome(
            uninstalled_names=set(), relinquished_names=set(), counters={}
        ),
    )
```

Register the marker in `packages/installer/pyproject.toml` under `[tool.pytest.ini_options]` → `markers = ["cli_deploy: exercises the real deploy stage wiring"]` (append to existing markers list if present, create otherwise), and decorate EVERY test in `test_cli_deploy_wiring.py` with `@pytest.mark.cli_deploy`.

Expected after fix: full suite PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/cli.py packages/installer/tests/unit/test_cli_deploy_wiring.py packages/installer/tests/unit/conftest.py packages/installer/pyproject.toml
git commit -m "feat(installer): wire CLI deploy stage into cli._run (wgclw.9.9 T11)"
```

---

### Task 12: Summary rendering of cli:<name> targets

**Files:**
- Modify: `packages/installer/src/installer/core/summary.py`
- Modify: `packages/installer/src/installer/cli.py` (pass the new arg)
- Test: `packages/installer/tests/unit/test_summary.py` (append; create if absent)

- [ ] **Step 1: Write the failing test**

```python
def test_cli_targets_render_as_blocks() -> None:
    """
    Given counters keyed cli:workcli with activity
    When render_summary runs with clis=("cli:workcli",)
    Then verbose renders a '-- cli:workcli --' block and quiet renders its
    change line (previously cli:* keys were silently dropped).

    Pins spec §6 summary-rendering change.
    """
    from installer.core.io_port import ScriptedIO
    from installer.core.model import Counters
    from installer.core.summary import render_summary

    counters = {"cli:workcli": Counters(created=1)}
    io = ScriptedIO()
    render_summary(
        counters, tools=[], plugins=[], all_tools=[], all_plugins=[],
        clis=["cli:workcli"], verbose=True, io=io,
    )
    assert any(e.message == "-- cli:workcli --" for e in io.transcript)
    io2 = ScriptedIO()
    render_summary(
        counters, tools=[], plugins=[], all_tools=[], all_plugins=[],
        clis=["cli:workcli"], verbose=False, io=io2,
    )
    assert any("cli:workcli: 1 installed" in e.message for e in io2.transcript)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/installer && uv run pytest tests/unit/test_summary.py -v`
Expected: FAIL with `TypeError: render_summary() got an unexpected keyword argument 'clis'`

- [ ] **Step 3: Implement**

`render_summary` gains keyword `clis: Sequence[str] = ()` and forwards to `_report_targets`; `_report_targets` gains the same param and changes its first line to `targets = [*tools, *plugins, *clis]`. In `cli.py`'s user-path `render_summary` call, pass `clis=[f"cli:{s.name}" for s in CLI_PACKAGES] if not args.prune_only else sorted(set(cli_prune.counters) if cli_prune else set())` — simplest correct form: pass every counters key starting with `cli:`:

```python
        clis=sorted(k for k in counters if k.startswith("cli:")),
```

(`_run_project`'s call omits it — default empty.)

- [ ] **Step 4: Run tests**

Run: `cd packages/installer && uv run pytest tests/unit/test_summary.py tests/unit/test_cli_deploy_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/installer/src/installer/core/summary.py packages/installer/src/installer/cli.py packages/installer/tests/unit/test_summary.py
git commit -m "feat(installer): render cli:<name> summary targets (wgclw.9.9 T12)"
```

---

### Task 13: Docs sweep (spec §9)

**Files (all Modify):**
- `AGENTS.md` (repo root): the two "Not yet installed by the installer" notes under prgroom and workcli become "Installed onto PATH by the installer (`uv tool install`, receipt-tracked, pruned on retirement)".
- `docs/guide/getting-started.md`: add one sentence to the install outcome description: "The installer also deploys the `work` and `prgroom` CLIs onto your PATH via `uv tool install` (uv ≥ 0.10.4 required for this stage)."
- `docs/guide/configuration.md`: rewrite the "Optional: the prgroom CLI" section — prgroom is now installed by the installer; manual `uv tool install ./packages/prgroom` remains documented as the no-installer fallback only.
- `packages/prgroom/AGENTS.md`: replace the "Not installed by the installer" section body: installed by the Python installer's CLI-deploy stage; manual uv-tool-install remains possible but the installer heals/upgrades receipt-owned installs.
- `packages/workcli/AGENTS.md` + `packages/workcli/README.md`: invocation docs add "installed globally as `work` by the repo installer" alongside the existing `uv --project` form.
- `docs/architecture/installer/c4-l3-engine.md`: add the CLI-deploy stage component (deploy_clis/prune_clis, CliDeployPort) to the engine diagram/description.
- `docs/architecture/installer/data-view.md`: document the receipt `clis` field (schema + omit-when-empty integrity rule + downgrade caveat).
- `docs/architecture/installer/sequences.md`: extend the install sequence with the CLI-deploy stage (after plugin routes, inside the lock) and the prune sequence with the CLI prune half.
- `docs/architecture/installer/installer-design.md`: overview paragraph naming the new stage.
- `docs/architecture/prgroom/c4-deployment.md`: mark the "installer owns uv tool install" statement as implemented (remove any 'unimplemented/retired' caveat).

- [ ] **Step 1: Make the edits** (grep each file for `workcli`, `prgroom`, `not yet installed`, `uv tool install` first — sweep ALL references per the sweep-all-refs discipline; the list above is the expected set, the grep is authoritative)

Run: `grep -rn "not yet installed\|Not installed by the installer\|uv tool install" AGENTS.md docs/guide docs/architecture packages/prgroom/AGENTS.md packages/workcli/AGENTS.md packages/workcli/README.md`

- [ ] **Step 2: Verify no stale claims remain**

Run: `grep -rn "not yet installed by the installer" AGENTS.md docs/ packages/`
Expected: no output (or only hits inside dated specs/plans, which are point-in-time and exempt)

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/guide docs/architecture packages/prgroom/AGENTS.md packages/workcli/AGENTS.md packages/workcli/README.md
git commit -m "docs: installer now deploys work + prgroom CLIs (wgclw.9.9 T13)"
```

---

### Task 14: Full gate + coverage

- [ ] **Step 1: Run the canonical gate from the WORKTREE root** (never the main tree — false-green risk)

Run: `make ci-installer`
Expected: ruff clean, format clean, mypy --strict clean, pytest green with coverage ≥90% branch, pip-audit clean, entry-verify OK.

- [ ] **Step 2: If coverage dips below 90%**, check `uv run pytest --cov --cov-report=term-missing` output for uncovered branches in `clis.py`/`run.py` — the likely gaps are UvCliDeploy error arms; cover them with monkeypatched-subprocess tests in `test_clis_port.py` (same `_FakeCompleted` pattern), never with `# pragma: no cover` on executable code.

- [ ] **Step 3: Run the whole-repo gate** (the PR gate runs `make ci`)

Run: `make ci`
Expected: green (installer + prgroom + workcli + vizsuite if wired + actionlint)

- [ ] **Step 4: Commit any gate fixes**

```bash
git add -A && git commit -m "chore(installer): gate fixes (wgclw.9.9 T14)"
```

---

## Verification (post-plan, delivery phase)

The completion gate routes HEAVY (`packages/**` + `src/**`-adjacent floors it via `.critical-paths`): run gate-triage, then `Workflow({name: "quality-gate", args: <triage JSON>})`, then `verify-checklist`. Delivery: PR via `finishing-a-development-branch`, `wait-for-pr-comments` review loop, merge per merge-guard policy, `sync-after-remote-merge`. Update bead `agents-config-wgclw.9.9` notes at delivery; closing it unblocks `agents-config-wgclw.9.4`.

**Out of scope for this plan** (spec §2): actually running the installer against the real user space — only the user runs `scripts/install.sh`, ever.
