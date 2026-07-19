"""Shared execution context for the track-backfill migration scripts.

Every script here reads an artifact that sits *beside the script* and talks to a
tracker that is resolved from the *working directory*. When those two are not
the same repository, the script silently operates on a split brain: the decided
assignment from one checkout, the database from another.

So all three scripts bind to the script's own repo and run every `work`
subprocess with that root as its CWD. This module is that binding, in one place,
because three copies of a safety check is three chances to fix two of them.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent


def _git(root: pathlib.Path | None, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(root) if root else None,
    )
    return proc.stdout.strip()


def resolve_root(*, require_artifact: pathlib.Path | None = None) -> pathlib.Path:
    """The repo this script lives in — and it must be the caller's, not a worktree.

    Args:
        require_artifact: if given, abort when this path does not exist.

    Three checks, each closing a distinct way to touch the wrong database:
      * the artifact is present (you are in a checkout that has it);
      * the script's repo is not a linked worktree (the bd database lives only
        in the main checkout);
      * the caller's repo is the script's repo (invoking by absolute path from
        another clone would otherwise read the artifact here and write there).
    """
    if require_artifact is not None and not require_artifact.exists():
        raise SystemExit(
            f"artifact missing: {require_artifact} — run from the merged main checkout"
        )

    root = pathlib.Path(_git(HERE, "rev-parse", "--show-toplevel")).resolve()

    # A linked worktree's git-dir differs from its git-common-dir. Comparing
    # them catches every worktree layout, not just the `.claude/worktrees/`
    # naming convention.
    git_dir = pathlib.Path(_git(HERE, "rev-parse", "--absolute-git-dir")).resolve()
    common_dir = pathlib.Path(
        _git(HERE, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()
    if git_dir != common_dir:
        raise SystemExit(
            f"refusing to run from a linked worktree ({root}); "
            "the bd database lives in the main checkout"
        )

    caller_root = pathlib.Path(_git(None, "rev-parse", "--show-toplevel")).resolve()
    if caller_root != root:
        raise SystemExit(
            f"script repo ({root}) is not the caller's repo ({caller_root}); "
            "cd into the target checkout before running"
        )
    return root


def work(root: pathlib.Path, *argv: str, require_ok: bool = True) -> dict:
    """Run a `work` verb against `root` and return its envelope.

    Fails loud by default: a script that mistakes a failed backend call for a
    successful one reports assurance it never established. Pass
    require_ok=False where a failing envelope is itself the finding.
    """
    proc = subprocess.run(
        ["work", *argv], capture_output=True, text=True, cwd=str(root)
    )
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        raise SystemExit(
            f"`work {' '.join(argv)}` returned non-JSON (exit {proc.returncode}): "
            f"{proc.stdout[:200]!r} {proc.stderr[:200]!r}"
        )
    if require_ok and not payload.get("ok"):
        raise SystemExit(f"`work {' '.join(argv)}` failed: {payload.get('error')}")
    return payload


def data(root: pathlib.Path, *argv: str) -> dict:
    """`work(...)` unwrapped to its data payload."""
    return work(root, *argv)["data"]
