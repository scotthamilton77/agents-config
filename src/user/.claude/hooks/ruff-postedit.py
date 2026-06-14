#!/usr/bin/env python3
"""PostToolUse hook: run ruff on a just-edited Python file.

Applies ruff's safe fixes + formatting silently; exits 2 with the residual
unfixable violations on stderr. Any internal problem (no ruff, no config,
crash, timeout, bad input) is a silent exit 0 — the hook is invisible unless
it has a real, actionable lint result.

F401 (unused import) and F841 (unused variable) are deliberately exempted from
this per-edit hook — see TRANSIENT_CODES below. They are *transient* during
incremental multi-edit authoring: edit 1 adds ``import X``; edit 2 (the one
that uses ``X``) lands later. If the hook auto-DELETED the import between those
edits, edit 2 would fail ``F821 Undefined name``, and a lone not-yet-used
import would itself block with exit 2. So we make these two codes (1) unfixable
(never auto-deleted) and (2) non-blocking (ignored for the exit-2 decision).
This is per-edit policy only — the CI gate (``make ci-*`` -> ``ruff check`` with
no flags) remains the real enforcer of genuinely-unused imports/variables.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PY_SUFFIXES = {".py", ".pyi"}
CONFIG_FILENAMES = ("ruff.toml", ".ruff.toml")
TIMEOUT_SECONDS = 4  # 3 calls × 4s = 12s worst-case, under the 15s outer hook timeout

# Rule codes that are transient mid-authoring and must NOT be auto-deleted or
# block per-edit. --unfixable / --ignore EXTEND the project's own pyproject
# [tool.ruff.lint] config (verified against ruff 0.15.13) — they add these
# codes on top of, rather than replacing, any project unfixable/ignore lists.
TRANSIENT_CODES = "F401,F841"


def _read_file_path():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    fp = tool_input.get("file_path")
    if not fp or not isinstance(fp, str):
        return None
    try:
        return Path(fp).resolve()
    except OSError:
        return None


def _find_config_root(start: Path):
    """Walk upward for a ruff config; return the directory that holds it."""
    for d in [start, *start.parents]:
        for name in CONFIG_FILENAMES:
            if (d / name).is_file():
                return d
        pyproject = d / "pyproject.toml"
        if pyproject.is_file():
            try:
                if "[tool.ruff" in pyproject.read_text(
                    encoding="utf-8", errors="ignore"
                ):
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
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
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
    # --unfixable keeps transient codes from being auto-deleted between edits.
    fix = [*ruff, "check", "--fix", "--unfixable", TRANSIENT_CODES, "--force-exclude"]
    if _run([*fix, target], config_root) is None:
        return 0
    if _run([*ruff, "format", "--force-exclude", target], config_root) is None:
        return 0
    # --ignore keeps a just-added, not-yet-used import/var from blocking (exit 2).
    check = [*ruff, "check", "--ignore", TRANSIENT_CODES, "--force-exclude"]
    final = _run([*check, target], config_root)
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
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
