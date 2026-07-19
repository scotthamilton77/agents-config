#!/usr/bin/env python3
"""Resolve the nine milestone orphans: anchor three, exempt six.

Usage:
    python3 scripts/track-backfill/anchor_orphans.py --dry-run
    python3 scripts/track-backfill/anchor_orphans.py --apply

These nine decisions were made against the backlog as it stood when the
assignment artifact was generated (design doc §5.4). An item that has since
closed, or gained a different parent, must not be blindly rewritten:
`work dep add` ADDS an edge — it is not a guarded "replace parent" operation, so
issuing it against an already-parented item is a graph mutation nobody reviewed.

Every write here is therefore preceded by a current-state assertion and followed
by a verification that the intended mapping actually holds. Any drift aborts
rather than forcing the edge.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

# child -> intended parent. Each item's own description names this milestone.
ANCHORS = {
    "agents-config-ysfvl": "agents-config-t142",
    "agents-config-9v0y": "agents-config-7bk",
    "agents-config-n7q0p": "agents-config-yf2ov",
}

# `lint-exempt:no-milestone` does not cascade, so 4vn5's two children are listed
# explicitly rather than relied upon to inherit.
EXEMPT = [
    "agents-config-4vn5",
    "agents-config-acmh.2",
    "agents-config-717",
    "agents-config-bkvgz",
    "agents-config-gvt64",
    "agents-config-ulv3",
]
LABEL = "lint-exempt:no-milestone"


def work(*argv: str) -> dict:
    proc = subprocess.run(["work", *argv], capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        raise SystemExit(
            f"`work {' '.join(argv)}` returned non-JSON (exit {proc.returncode}): "
            f"{proc.stdout[:200]!r} {proc.stderr[:200]!r}"
        )
    if not payload.get("ok"):
        raise SystemExit(f"`work {' '.join(argv)}` failed: {payload.get('error')}")
    return payload["data"]


def anchor(apply: bool) -> None:
    for child, parent in ANCHORS.items():
        item = work("show", child)
        if item["status"] == "closed":
            raise SystemExit(
                f"ABORT {child}: closed since the artifact was generated — "
                "re-decide this item, do not anchor it"
            )
        if item["parent"] == parent:
            print(f"  ALREADY {child} -> {parent}")
            continue
        if item["parent"] is not None:
            raise SystemExit(
                f"ABORT {child}: already parented to {item['parent']}, not {parent} — "
                "the graph moved since the artifact was generated; re-decide"
            )
        if not apply:
            print(f"  WOULD ANCHOR {child} -> {parent}")
            continue
        work("dep", "add", child, parent, "--type", "parent-child")
        print(f"  ANCHORED {child} -> {parent}")


def exempt(apply: bool) -> None:
    for item_id in EXEMPT:
        item = work("show", item_id)
        if item["status"] == "closed":
            print(f"  SKIP {item_id}: closed since generation, no exemption needed")
            continue
        if LABEL in item["labels"]:
            print(f"  ALREADY {item_id}")
            continue
        if not apply:
            print(f"  WOULD EXEMPT {item_id}")
            continue
        work("label", "add", item_id, LABEL)
        print(f"  EXEMPTED {item_id}")


def verify() -> None:
    """Assert the exact intended mapping — printing parents is not verifying."""
    failures: list[str] = []
    for child, parent in ANCHORS.items():
        got = work("show", child)["parent"]
        if got != parent:
            failures.append(f"{child} parent is {got}, expected {parent}")
    for item_id in EXEMPT:
        item = work("show", item_id)
        if item["status"] != "closed" and LABEL not in item["labels"]:
            failures.append(f"{item_id} is live but not exempt")
    if failures:
        for f in failures:
            print("FAIL:", f, file=sys.stderr)
        raise SystemExit(f"{len(failures)} orphan resolution(s) did not take")
    print("ORPHANS_OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the plan, mutate nothing")
    mode.add_argument("--apply", action="store_true", help="write the edges and labels")
    args = parser.parse_args()

    anchor(args.apply)
    exempt(args.apply)
    if args.apply:
        verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
