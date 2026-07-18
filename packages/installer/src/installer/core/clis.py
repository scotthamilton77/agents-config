"""CLI-deploy registry, source digest, and subprocess port (spec: installer-cli-deploy).

The registry is CLOSED (like the Tool enum, unlike the plugins dir-scan):
packages/ contains early packages that must not auto-deploy. Uninstall
authority is bounded by CLI_PACKAGES | RETIRED_CLIS — the receipt alone never
authorizes an uninstall.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class CliDeployPort(Protocol):
    """Injected subprocess seam for uv-tool deploys. All installed-state
    decisions are PATH-independent (bin_dir/shim_path/tool_list); ``which``
    serves only the reachability invariant (spec §4)."""

    def uv_version(self) -> tuple[int, ...] | None: ...  # pragma: no cover
    def bin_dir(self) -> Path: ...  # pragma: no cover
    def shim_path(self, binary: str) -> Path | None: ...  # pragma: no cover
    def tool_list(self) -> Mapping[str, frozenset[str]] | None: ...  # pragma: no cover
    def tool_install(
        self, package_dir: Path, *, force: bool
    ) -> CommandResult: ...  # pragma: no cover
    def tool_uninstall(self, name: str) -> CommandResult: ...  # pragma: no cover
    def update_shell(self) -> CommandResult: ...  # pragma: no cover
    def which(self, binary: str) -> Path | None: ...  # pragma: no cover
    def smoke(self, shim: Path, args: tuple[str, ...]) -> CommandResult: ...  # pragma: no cover


class ScriptedCliDeploy:
    """Test fake for CliDeployPort.

    Idempotent queries (uv_version / bin_dir / tool_list / which) return
    STABLE configured values — they model repeatable reads, so tests never
    have to count the engine's internal call sites for them. State-bearing
    calls (shim_path, whose answer legitimately changes across an install;
    tool_install / tool_uninstall / update_shell / smoke) pop per-method
    queues; a pop on an empty queue raises naming the queue
    (self-diagnosing, mirroring ScriptedIO). shim_path queue budget per
    CLI: one decision read, plus one post-install re-read only when a
    tool_install succeeded."""

    def __init__(
        self,
        *,
        uv_version: tuple[int, ...] | None = None,
        bin_dir: Path | None = None,
        tool_list: Mapping[str, frozenset[str]] | None = None,
        which_map: Mapping[str, Path | None] | None = None,
        shims: list[Path | None] | None = None,
        installs: list[CommandResult] | None = None,
        uninstalls: list[CommandResult] | None = None,
        update_shells: list[CommandResult] | None = None,
        smokes: list[CommandResult] | None = None,
    ) -> None:
        self._uv_version = uv_version
        self._bin_dir = bin_dir
        self._tool_list = tool_list
        self._which_map = dict(which_map or {})
        self._shims = list(shims or [])
        self._installs = list(installs or [])
        self._uninstalls = list(uninstalls or [])
        self._update_shells = list(update_shells or [])
        self._smokes = list(smokes or [])
        self.transcript: list[tuple[object, ...]] = []

    # -- idempotent queries: stable values --

    def uv_version(self) -> tuple[int, ...] | None:
        self.transcript.append(("uv_version",))
        return self._uv_version

    def bin_dir(self) -> Path:
        self.transcript.append(("bin_dir",))
        if self._bin_dir is None:
            msg = "ScriptedCliDeploy bin_dir not configured"
            raise RuntimeError(msg)
        return self._bin_dir

    def tool_list(self) -> Mapping[str, frozenset[str]] | None:
        self.transcript.append(("tool_list",))
        return self._tool_list

    def which(self, binary: str) -> Path | None:
        self.transcript.append(("which", binary))
        return self._which_map.get(binary)

    # -- state-bearing calls: queues --

    def shim_path(self, binary: str) -> Path | None:
        self.transcript.append(("shim_path", binary))
        if not self._shims:
            msg = "ScriptedCliDeploy shims queue exhausted"
            raise RuntimeError(msg)
        return self._shims.pop(0)

    def tool_install(self, package_dir: Path, *, force: bool) -> CommandResult:
        self.transcript.append(("tool_install", str(package_dir), force))
        if not self._installs:
            msg = "ScriptedCliDeploy installs queue exhausted"
            raise RuntimeError(msg)
        return self._installs.pop(0)

    def tool_uninstall(self, name: str) -> CommandResult:
        self.transcript.append(("tool_uninstall", name))
        if not self._uninstalls:
            msg = "ScriptedCliDeploy uninstalls queue exhausted"
            raise RuntimeError(msg)
        return self._uninstalls.pop(0)

    def update_shell(self) -> CommandResult:
        self.transcript.append(("update_shell",))
        if not self._update_shells:
            msg = "ScriptedCliDeploy update_shells queue exhausted"
            raise RuntimeError(msg)
        return self._update_shells.pop(0)

    def smoke(
        self,
        shim: Path,
        args: tuple[str, ...],  # noqa: ARG002  # protocol parameter; fake records only shim
    ) -> CommandResult:
        self.transcript.append(("smoke", str(shim)))
        if not self._smokes:
            msg = "ScriptedCliDeploy smokes queue exhausted"
            raise RuntimeError(msg)
        return self._smokes.pop(0)


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
        if not lock.is_file():
            cmd.append(str(package_dir))
            return self._run(cmd, _INSTALL_TIMEOUT)
        # Single lock-guarded block: mypy --strict (possibly-undefined) rejects
        # binding `constraints` under one `if lock.is_file()` and reading it
        # under a second; try/finally also cleans up on every return path.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            constraints = Path(tmp.name)
        try:
            export = self._run(
                [
                    "uv",
                    "export",
                    "--frozen",
                    "--no-dev",
                    "--no-emit-project",
                    "--project",
                    str(package_dir),
                    "-o",
                    str(constraints),
                ],
                _QUERY_TIMEOUT,
            )
            if not export.ok:
                return export
            cmd.extend(["--constraints", str(constraints), str(package_dir)])
            return self._run(cmd, _INSTALL_TIMEOUT)
        finally:
            constraints.unlink(missing_ok=True)

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
