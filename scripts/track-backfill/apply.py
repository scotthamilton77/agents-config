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

from context import HERE, data, resolve_root, work
from reconcile import reconcile

ARTIFACT = HERE / "assignment.json"
RUNLOG = HERE / "applied.log"

EXPECTED_SCHEMA = "track-backfill-assignment-v1"



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
    """Write one track through the validated gate. Returns (ok, error_code).

    require_ok=False is load-bearing, not incidental: this is the one caller that
    must CLASSIFY a failing envelope rather than die on it. With the default the
    helper raises SystemExit before returning, making the E_NOT_FOUND recovery
    below unreachable and skipping the run-log summary on every other failure.
    """
    payload = work(root, "track", "set", item_id, track, require_ok=False)
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

    root = resolve_root(require_artifact=ARTIFACT)
    assignment = load_assignment(root)

    lint = data(root, "lint")
    require_quiescent(root, lint, assignment)
    violations = {v["id"] for v in lint["track_violations"]}

    items = data(root, "list", "--limit", "0")["items"]
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
    vanished: list[str] = []
    with RUNLOG.open("a") as log:
        for n, (i, t) in enumerate(sorted(plan.to_apply.items()), 1):
            ok, code = set_track(root, i, t)
            if ok:
                log.write(f"{i}\t{t}\n")
                log.flush()
                applied += 1
                continue
            if code == "E_NOT_FOUND":
                # The item is genuinely gone from the tracker between the sweep
                # and this write. That is the expected-drift case the design is
                # built to tolerate (§5.1), so record and continue.
                #
                # Note this is NOT the mid-run *closure* case: `work track set`
                # has no status guard, so a closed-but-present item is labelled
                # successfully and never reaches this branch.
                print(f"  VANISHED {i} (no longer in the tracker)")
                vanished.append(i)
                continue
            # Anything else — contention, an unknown track, a backend fault —
            # means the world no longer matches the plan we computed, and
            # continuing to write into that is worse than stopping. Re-running
            # is safe (design doc §5.5).
            print(f"  ABORT at {n}/{len(plan.to_apply)}: {i} -> {code}", file=sys.stderr)
            print(f"FAILED after {applied} writes; see {RUNLOG}. Fix the cause and re-run.")
            return 1

    print(
        f"OK — {applied} applied, {len(vanished)} vanished, "
        f"{len(plan.residue)} residue, log at {RUNLOG}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
