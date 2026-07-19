#!/usr/bin/env python3
"""Verify the seven acceptance criteria of the track backfill migration.

Every criterion appends to `failures` — none is a bare print. Exit 1 on any.
"""

from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import tomllib

HERE = pathlib.Path(__file__).parent


def work(*argv: str) -> dict:
    return json.loads(subprocess.run(["work", *argv], capture_output=True, text=True).stdout)


def main() -> int:
    root = pathlib.Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    config = tomllib.load(open(root / "project-config.toml", "rb"))
    organizing_only = set(config["tracks"]["organizing-only"])
    cap = config["extraction"]["pressure"]["max-track-backlog"]
    groom_bead = config["operating-model"]["groom-state-bead"]

    assigned = {
        i: e["track"]
        for i, e in json.loads((HERE / "assignment.json").read_text())["items"].items()
    }
    expected_mismatch = set(json.loads((HERE / "expected_mismatches.json").read_text()))

    lint = work("lint")["data"]
    violations = {v["id"] for v in lint["track_violations"]}
    items = work("list", "--limit", "0")["data"]["items"]
    failures: list[str] = []

    # C1 — outcome matches the artifact; nothing outside it was written to.
    # The groom-state bead is minted by this migration and is deliberately
    # not in the artifact, so it is carved out of the stray check.
    mismatched, stray = [], []
    for item in items:
        want = assigned.get(item["id"])
        if want is not None:
            if item["track"] != want:
                mismatched.append((item["id"], want, item["track"]))
        elif item["track"] is not None and item["id"] != groom_bead:
            stray.append((item["id"], item["type"], item["track"]))
    if mismatched:
        failures.append(f"C1 outcome != artifact: {mismatched[:5]} ({len(mismatched)} total)")
    if stray:
        failures.append(f"C1 track written outside the artifact: {stray[:5]} ({len(stray)} total)")

    # C2 — zero violations among covered ids; residue reported, not asserted away.
    leak = violations & set(assigned)
    residue = violations - set(assigned)
    if leak:
        failures.append(f"C2 covered ids still violating: {sorted(leak)[:5]} ({len(leak)} total)")
    print(f"residue (live, unassigned): {len(residue)} {sorted(residue)}")

    # C3 — zero milestone orphans.
    if lint["milestone_orphans"]:
        failures.append(f"C3 milestone_orphans: {lint['milestone_orphans']}")

    # C4 — no EXTRACTABLE track over the cap, measured LIVE (not from the artifact).
    live_counts = collections.Counter(
        item["track"] for item in items if item["track"] is not None
    )
    over = {t: n for t, n in live_counts.items() if t not in organizing_only and n > cap}
    if over:
        failures.append(f"C4 extractable tracks over cap {cap}: {over}")

    # C5 — no cross-track parent edge beyond the set the artifact implies.
    actual_mismatch = {m["id"] for m in lint["track_mismatches"]}
    unexpected = actual_mismatch - expected_mismatch
    if unexpected:
        failures.append(
            f"C5 unexpected cross-track parents: {sorted(unexpected)[:5]} "
            f"({len(unexpected)} beyond the {len(expected_mismatch)} baseline)"
        )
    print(f"track_mismatches: {len(actual_mismatch)} (baseline {len(expected_mismatch)})")

    # C6 — groom-state bead exists, tracked ops-meta, exempt.
    if not groom_bead:
        failures.append("C6 groom-state-bead empty")
    else:
        got = work("show", groom_bead)
        if not got.get("ok"):
            failures.append(f"C6 groom-state-bead {groom_bead} does not exist")
        else:
            it = got["data"]
            if it["track"] != "ops-meta":
                failures.append(f"C6 groom-state track is {it['track']}")
            if "lint-exempt:no-milestone" not in it["labels"]:
                failures.append("C6 groom-state missing exemption label")

    for f in failures:
        print("FAIL:", f)
    print("ALL CRITERIA PASS" if not failures else f"{len(failures)} CRITERIA FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
