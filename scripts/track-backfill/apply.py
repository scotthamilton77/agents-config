#!/usr/bin/env python3
"""Apply the decided track assignment to the live backlog.

Usage:
    python3 scripts/track-backfill/apply.py --dry-run
    python3 scripts/track-backfill/apply.py --apply

Refuses to run from a worktree, or against a config whose vocabulary does not
cover the artifact. Appends every successful write to a run log so a mid-run
abort leaves a reconcilable record.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tomllib

HERE = pathlib.Path(__file__).parent
ARTIFACT = HERE / "assignment.json"
RUNLOG = HERE / "applied.log"


def preflight(assignment: dict[str, str]) -> None:
    """Abort on the two constraints that silently corrupt a run."""
    if not ARTIFACT.exists():
        raise SystemExit(f"artifact missing: {ARTIFACT} — run from the merged main checkout")

    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if ".claude/worktrees/" in root:
        raise SystemExit(
            f"refusing to run from a worktree ({root}); the bd database lives in the main checkout"
        )

    config_path = pathlib.Path(root) / "project-config.toml"
    names = set(tomllib.load(open(config_path, "rb"))["tracks"]["names"])
    unknown = sorted(set(assignment.values()) - names)
    if unknown:
        raise SystemExit(
            f"config vocabulary at {config_path} is missing {unknown} — "
            "land the vocabulary change before applying"
        )


def live_violations() -> set[str]:
    """Ids currently failing lint invariant 1."""
    proc = subprocess.run(["work", "lint"], capture_output=True, text=True)
    payload = json.loads(proc.stdout)
    if not payload.get("ok"):
        raise SystemExit(f"work lint failed: {payload.get('error')}")
    return {v["id"] for v in payload["data"]["track_violations"]}


def load_assignment() -> dict[str, str]:
    doc = json.loads(ARTIFACT.read_text())
    return {i: entry["track"] for i, entry in doc["items"].items()}


def set_track(item_id: str, track: str) -> tuple[bool, str]:
    """Write one track through the validated gate. Returns (ok, error_code)."""
    proc = subprocess.run(
        ["work", "track", "set", item_id, track], capture_output=True, text=True
    )
    if proc.returncode == 0:
        return True, ""
    try:
        code = json.loads(proc.stdout)["error"]["code"]
    except (ValueError, KeyError, TypeError):
        code = proc.stderr.strip() or "UNKNOWN"
    return False, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan, mutate nothing")
    mode.add_argument("--apply", action="store_true", help="write the labels")
    args = parser.parse_args()

    assignment = load_assignment()
    preflight(assignment)
    from reconcile import reconcile

    plan = reconcile(assignment, live_violations())

    print(f"apply  : {len(plan.to_apply)}")
    print(f"skip   : {len(plan.skipped)} (closed since artifact generation)")
    print(f"residue: {len(plan.residue)} (live, unassigned — reported not guessed)")
    for i in plan.residue:
        print(f"  RESIDUE {i}")

    if args.dry_run:
        for i, t in sorted(plan.to_apply.items()):
            print(f"  WOULD SET {i} -> {t}")
        return 0

    applied = 0
    with RUNLOG.open("a") as log:
        for n, (i, t) in enumerate(sorted(plan.to_apply.items()), 1):
            ok, code = set_track(i, t)
            if ok:
                log.write(f"{i}\t{t}\n")
                log.flush()
                applied += 1
                continue
            if code == "E_NOT_FOUND":
                print(f"  VANISHED {i} (closed during run)")
                continue
            # Contention or timeout: stop rather than keep writing into a
            # contended database. Re-running is safe (design doc §5.5).
            print(f"  ABORT at {n}/{len(plan.to_apply)}: {i} -> {code}", file=sys.stderr)
            print(f"FAILED after {applied} writes; see {RUNLOG}. Fix the cause and re-run.")
            return 1

    print(f"OK — {applied} applied, {len(plan.residue)} residue, log at {RUNLOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
