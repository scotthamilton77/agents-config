#!/usr/bin/env python3
"""Apply the decided track assignment to the live backlog.

Usage:
    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply

Preconditions, all enforced rather than documented:
  * the script's own repo is the caller's repo, and is not a linked worktree;
  * the config vocabulary covers every track the artifact uses;
  * the artifact matches its own declared integrity metadata;
  * no item is leased (the migration requires a quiescent window).

Appends every successful write to a run log so a mid-run abort leaves a
reconcilable record.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tomllib

from reconcile import reconcile

HERE = pathlib.Path(__file__).resolve().parent
ARTIFACT = HERE / "assignment.json"
RUNLOG = HERE / "applied.log"

EXPECTED_SCHEMA = "track-backfill-assignment-v1"


def _git(root: pathlib.Path | None, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(root) if root else None,
    )
    return proc.stdout.strip()


def resolve_root() -> pathlib.Path:
    """The repo this script lives in — and it must not be a linked worktree.

    Binding to the script's own location rather than the caller's cwd closes the
    case where apply.py is invoked by absolute path from a different clone: the
    artifact would come from here while every `work` subprocess resolved config
    and database from there.
    """
    if not ARTIFACT.exists():
        raise SystemExit(f"artifact missing: {ARTIFACT} — run from the merged main checkout")

    root = pathlib.Path(_git(HERE, "rev-parse", "--show-toplevel")).resolve()

    # A linked worktree has .git as a file and a git-dir under the primary
    # repo's worktrees/ directory. This catches every worktree layout, not just
    # the `.claude/worktrees/` naming convention.
    git_dir = pathlib.Path(_git(HERE, "rev-parse", "--absolute-git-dir")).resolve()
    common_dir = pathlib.Path(_git(HERE, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
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


def load_assignment(root: pathlib.Path) -> dict[str, str]:
    """Load the artifact, refusing it if it fails its own integrity metadata."""
    doc = json.loads(ARTIFACT.read_text())

    schema = doc.get("schema")
    if schema != EXPECTED_SCHEMA:
        raise SystemExit(f"artifact schema is {schema!r}, expected {EXPECTED_SCHEMA!r}")

    items = doc["items"]
    declared = doc.get("explicit_count")
    if declared != len(items):
        raise SystemExit(
            f"artifact integrity: explicit_count={declared} but it holds {len(items)} items — "
            "the artifact has been edited; restore it from git"
        )

    assignment: dict[str, str] = {}
    for item_id, entry in items.items():
        track = entry.get("track")
        if not isinstance(track, str) or not track:
            raise SystemExit(f"artifact integrity: {item_id} has no usable track ({entry!r})")
        assignment[item_id] = track

    names = set(tomllib.load(open(root / "project-config.toml", "rb"))["tracks"]["names"])
    unknown = sorted(set(assignment.values()) - names)
    if unknown:
        raise SystemExit(
            f"config vocabulary at {root / 'project-config.toml'} is missing {unknown} — "
            "land the vocabulary change before applying"
        )
    return assignment


def work(root: pathlib.Path, *argv: str) -> dict:
    """Run a `work` verb in the target repo and return its envelope."""
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
    return payload


def require_ok(payload: dict, what: str) -> dict:
    if not payload.get("ok"):
        raise SystemExit(f"{what} failed: {payload.get('error')}")
    return payload["data"]


def require_quiescent(root: pathlib.Path, lint: dict, assignment: dict[str, str]) -> None:
    """Refuse to run while any covered item is leased.

    `work track set` has no status guard and the tracker offers no compare-and-set,
    so a concurrent agent's legitimate track write would be silently overwritten.
    The migration's answer is an exclusive window, asserted here rather than
    assumed (design doc §5.5).
    """
    leased = {item["id"] for item in lint["leases"]["leases"]}
    conflicting = sorted(leased & set(assignment))
    if conflicting:
        raise SystemExit(
            f"{len(conflicting)} covered item(s) are leased (in_progress): {conflicting[:10]} — "
            "the migration needs a quiescent window. Confirm no live session owns them, "
            "release the leases, and re-run."
        )
    if leased:
        print(f"note: {len(leased)} leased item(s), none covered by the artifact — proceeding")


def set_track(root: pathlib.Path, item_id: str, track: str) -> tuple[bool, str]:
    """Write one track through the validated gate. Returns (ok, error_code)."""
    payload = work(root, "track", "set", item_id, track)
    if payload.get("ok"):
        return True, ""
    error = payload.get("error") or {}
    return False, error.get("code", "UNKNOWN")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan, mutate nothing")
    mode.add_argument("--apply", action="store_true", help="write the labels")
    args = parser.parse_args()

    root = resolve_root()
    assignment = load_assignment(root)

    lint = require_ok(work(root, "lint"), "work lint")
    require_quiescent(root, lint, assignment)
    violations = {v["id"] for v in lint["track_violations"]}

    items = require_ok(work(root, "list", "--limit", "0"), "work list")["items"]
    live_tracks = {item["id"]: item["track"] for item in items}

    plan = reconcile(assignment, live_tracks, violations)

    print(f"apply    : {len(plan.to_apply)}")
    print(f"unchanged: {len(plan.already_correct)} (already on target track)")
    print(f"skip     : {len(plan.skipped)} (closed since artifact generation)")
    print(f"residue  : {len(plan.residue)} (live, unassigned — reported not guessed)")
    for i in plan.residue:
        print(f"  RESIDUE {i}")

    if args.dry_run:
        for i, t in sorted(plan.to_apply.items()):
            print(f"  WOULD SET {i} -> {t}")
        return 0

    applied = 0
    with RUNLOG.open("a") as log:
        for n, (i, t) in enumerate(sorted(plan.to_apply.items()), 1):
            ok, code = set_track(root, i, t)
            if ok:
                log.write(f"{i}\t{t}\n")
                log.flush()
                applied += 1
                continue
            # Fail loud and stop. Every remaining failure mode — contention,
            # a vanished item, an unknown track — means the world no longer
            # matches the plan we computed, and continuing to write into that
            # is worse than stopping. Re-running is safe (design doc §5.5).
            print(f"  ABORT at {n}/{len(plan.to_apply)}: {i} -> {code}", file=sys.stderr)
            print(f"FAILED after {applied} writes; see {RUNLOG}. Fix the cause and re-run.")
            return 1

    print(f"OK — {applied} applied, {len(plan.residue)} residue, log at {RUNLOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
