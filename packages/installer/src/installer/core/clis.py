"""CLI-deploy registry, source digest, and subprocess port (spec: installer-cli-deploy).

The registry is CLOSED (like the Tool enum, unlike the plugins dir-scan):
packages/ contains early packages that must not auto-deploy. Uninstall
authority is bounded by CLI_PACKAGES | RETIRED_CLIS — the receipt alone never
authorizes an uninstall.
"""

from __future__ import annotations

import hashlib
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
