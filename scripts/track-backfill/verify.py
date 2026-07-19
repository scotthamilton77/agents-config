#!/usr/bin/env python3
"""Verify the six acceptance criteria of the track backfill migration.

Every criterion appends to `failures` — none is a bare print. Exit 1 on any.
"""

from __future__ import annotations

import collections
import json
import pathlib
import subprocess
import tomllib

HERE = pathlib.Path(__file__).parent

# Task 7 reparents `9v0y` (review-and-merge) under `7bk` (an epic on
# pipeline-discipline), which necessarily creates one new cross-track edge. The
# other two reparents land under milestones, and _track_mismatches skips
# milestone parents, so they add nothing. Accepted per design doc §5.4.
DELIBERATE_MISMATCH_ADDITIONS = {"agents-config-9v0y"}


def work(*argv: str, require_ok: bool = True) -> dict:
    """Run a `work` verb and return its envelope.

    Fails loud by default: a verifier that mistakes a failed backend call for a
    successful one reports assurance it never established. C6 opts out with
    require_ok=False, because there a failing envelope IS the finding.
    """
    proc = subprocess.run(["work", *argv], capture_output=True, text=True)
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

    # Closed items are excluded from `work list` by default, which would make a
    # stray write to a closed item invisible to C1 — and `work track set` has no
    # status guard, so such a write is possible. Enumerate them explicitly.
    closed = work("list", "--limit", "0", "--status", "closed")["data"]["items"]

    failures: list[str] = []

    def track_labels(item: dict) -> list[str]:
        """Raw track:* labels, not the derived track.

        derive_track() collapses 0 and 2+ labels alike to None, so an item that
        was accidentally given two tracks reads as untracked. Counting the raw
        labels is what makes that case visible.
        """
        return [x for x in item["labels"] if x.startswith("track:")]

    # C1 — outcome matches the artifact; nothing outside it was written to.
    # The groom-state bead is minted by this migration and is deliberately
    # not in the artifact, so it is carved out of the stray check.
    mismatched, stray, doubled = [], [], []
    for item in items + closed:
        labels = track_labels(item)
        if len(labels) > 1:
            doubled.append((item["id"], labels))
        want = assigned.get(item["id"])
        if want is not None:
            if item["track"] != want:
                mismatched.append((item["id"], want, item["track"], item["status"]))
        elif labels and item["id"] != groom_bead:
            stray.append((item["id"], item["type"], item["status"], labels))
    if mismatched:
        failures.append(f"C1 outcome != artifact: {mismatched[:5]} ({len(mismatched)} total)")
    if stray:
        failures.append(f"C1 track written outside the artifact: {stray[:5]} ({len(stray)} total)")
    if doubled:
        failures.append(f"C1 item carries multiple track labels: {doubled[:5]} ({len(doubled)} total)")

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

    # C5 — the cross-track parent set is EXACTLY what the migration implies.
    #
    # `work lint` keys these on "child", not "id" (report.py _track_mismatches).
    # The wrong key was invisible for as long as the list was empty: nothing is
    # labelled before the migration, so the loop body never ran. It only raises
    # once the migration materializes the mismatches — i.e. exactly when this
    # criterion is supposed to do its job.
    #
    # Checked both ways. A one-sided `actual - expected` passes when an expected
    # edge DISAPPEARS, which would mean the graph changed under us unnoticed.
    actual_mismatch = {m["child"] for m in lint["track_mismatches"]}
    expected_final = expected_mismatch | DELIBERATE_MISMATCH_ADDITIONS
    unexpected = actual_mismatch - expected_final
    missing = expected_final - actual_mismatch
    if unexpected:
        failures.append(
            f"C5 unexpected cross-track parents: {sorted(unexpected)[:5]} "
            f"({len(unexpected)} beyond the expected {len(expected_final)})"
        )
    if missing:
        failures.append(
            f"C5 expected cross-track parents absent: {sorted(missing)[:5]} "
            f"({len(missing)} missing) — the graph changed unexpectedly"
        )
    print(f"track_mismatches: {len(actual_mismatch)} (expected {len(expected_final)})")

    # C6 — groom-state bead exists, tracked ops-meta, exempt.
    if not groom_bead:
        failures.append("C6 groom-state-bead empty")
    else:
        got = work("show", groom_bead, require_ok=False)
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
    print(
        "C1-C6 PASS — criterion 7 (idempotency) is a sequenced check, run it separately"
        if not failures
        else f"{len(failures)} CRITERIA FAILED"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
