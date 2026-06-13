#!/usr/bin/env python3
"""PostToolUse hook: run ruff on a just-edited Python file.

Applies ruff's safe fixes + formatting silently; exits 2 with the residual
unfixable violations on stderr. Any internal problem (no ruff, no config,
crash, timeout, bad input) is a silent exit 0 — the hook is invisible unless
it has a real, actionable lint result.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PY_SUFFIXES = {".py", ".pyi"}
CONFIG_FILENAMES = ("ruff.toml", ".ruff.toml")
TIMEOUT_SECONDS = 10


def _read_file_path():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input") or {}
    fp = tool_input.get("file_path")
    if not fp or not isinstance(fp, str):
        return None
    return Path(fp)


def _find_config_root(start: Path):
    """Walk upward for a ruff config; return the directory that holds it."""
    for d in [start, *start.parents]:
        for name in CONFIG_FILENAMES:
            if (d / name).is_file():
                return d
        pyproject = d / "pyproject.toml"
        if pyproject.is_file():
            try:
                if "[tool.ruff" in pyproject.read_text(encoding="utf-8", errors="ignore"):
                    return d
            except OSError:
                pass
    return None


def _ruff_argv(config_root: Path):
    """Prefer the project-pinned ruff (uv, no sync); else PATH ruff."""
    if (config_root / "uv.lock").is_file() or (config_root / ".venv").is_dir():
        if shutil.which("uv"):
            return ["uv", "run", "--no-sync", "ruff"]
    if shutil.which("ruff"):
        return ["ruff"]
    return None


def _run(argv, cwd: Path):
    try:
        return subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def main() -> int:
    file_path = _read_file_path()
    if file_path is None:
        return 0
    if file_path.suffix not in PY_SUFFIXES or not file_path.is_file():
        return 0

    config_root = _find_config_root(file_path.parent)
    if config_root is None:
        return 0

    ruff = _ruff_argv(config_root)
    if ruff is None:
        return 0

    target = str(file_path)
    if _run([*ruff, "check", "--fix", "--force-exclude", target], config_root) is None:
        return 0
    if _run([*ruff, "format", "--force-exclude", target], config_root) is None:
        return 0
    final = _run([*ruff, "check", "--force-exclude", target], config_root)
    if final is None:
        return 0

    # ruff check: 0 = clean, 1 = violations remain, 2 = ruff internal error
    if final.returncode == 1:
        sys.stderr.write(
            "ruff auto-fixed what it could; the following need manual attention:\n"
            + (final.stdout or final.stderr or "")
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
