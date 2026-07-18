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
