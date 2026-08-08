#!/usr/bin/env python3
"""Verify the six acceptance criteria of the track backfill migration.

Every criterion appends to `failures` — none is a bare print. Exit 1 on any.
"""

from __future__ import annotations

import collections
import json
import tomllib

from context import HERE, resolve_root, work

RUNLOG = HERE / "applied.log"


def applied_ids(runlog_text: str) -> set[str]:
    """Ids this migration has written, from the tab-separated run log."""
    return {
        line.split("\t", 1)[0]
        for line in runlog_text.splitlines()
        if line.strip() and "\t" in line
    }


def track_labels(item: dict) -> list[str]:
    """Raw `track:*` labels, not the derived track.

    `derive_track` collapses 0 and 2+ labels alike to None, so an item
    accidentally given two tracks reads as untracked. Counting the raw labels is
    what makes that case visible.
    """
    return [label for label in item["labels"] if label.startswith("track:")]


def audit_tracks(
    live: list[dict], closed: list[dict], assigned: dict[str, str], written: set[str]
) -> dict:
    """C1's sweep: did this migration produce the outcome the artifact decided?

    Three findings, each a defect on its own terms:

    `mismatched` — a live artifact item not carrying its decided track.
    `doubled` — any item carrying two track labels, whatever its status.
    `wrote_outside_artifact` — an id in the run log that exists in this database
    and the artifact does not cover, meaning the applicator wrote beyond what was
    decided and reviewed. The existence filter is load-bearing, not defensive:
    the run log is cumulative across migrations by design, so it still names
    every id written in earlier runs — including runs against a database that has
    since been retired and replaced. Those ids exist nowhere now and are evidence
    of nothing here. Without the filter the criterion fails by hundreds on a
    correct run, which is how it was found.

    Deliberately NOT a finding: an item carrying a track the artifact never
    mentions. That was the original stray check, and it measured a premise that
    has since expired. It held when the artifact was the only way a track could
    arrive; `work create --track` now threads one through the lifecycle gate at
    creation, and the enforcement flip makes that mandatory. Under that check,
    every correctly created item is a failure and the criterion gets more wrong
    every week. What the check was actually for -- proving the applicator stayed
    inside its mandate -- is the run log's job, which names writers rather than
    inferring them from end state.

    Closed items are swept for doubled labels but never compared against a target:
    reconcile skips an artifact item that closed before apply, making no write, so
    comparing its empty track against its target would fail a correct run.
    """
    mismatched, doubled, skipped_closed = [], [], []
    for item in live + closed:
        labels = track_labels(item)
        if len(labels) > 1:
            doubled.append((item["id"], labels))
        want = assigned.get(item["id"])
        if want is None:
            continue
        if item["status"] == "closed":
            skipped_closed.append(item["id"])
        elif item["track"] != want:
            mismatched.append((item["id"], want, item["track"], item["status"]))
    extant = {item["id"] for item in live + closed}
    in_scope = written & extant
    return {
        "mismatched": mismatched,
        "doubled": doubled,
        "skipped_closed": skipped_closed,
        "logged": len(written),
        "logged_in_scope": len(in_scope),
        "wrote_outside_artifact": sorted(in_scope - set(assigned)),
    }


def main() -> int:
    # Bind to the script's own repo, not the caller's cwd. Without this, running
    # verify.py by absolute path from another clone reads the artifact from here
    # while every `work` call reports on a different backlog — passing C1-C6 for
    # a database the migration never touched.
    root = resolve_root(require_artifact=HERE / "assignment.json")
    config = tomllib.load(open(root / "project-config.toml", "rb"))
    organizing_only = set(config["tracks"]["organizing-only"])
    cap = config["extraction"]["pressure"]["max-track-backlog"]
    operating = config["operating-model"]
    # Same precedence as the facade: the current key wins whenever present,
    # the superseded spelling is read only in its absence.
    groom_item = operating.get("groom-state-item", operating.get("groom-state-bead", ""))

    assigned = {
        i: e["track"]
        for i, e in json.loads((HERE / "assignment.json").read_text())["items"].items()
    }
    # Generated, never committed: it is a function of the assignment and the live
    # parent graph, so a checked-in copy is stale as soon as either moves. Absence
    # is a skipped step, not a missing dependency — say which step.
    expected_path = HERE / "expected_mismatches.json"
    if not expected_path.exists():
        raise SystemExit(
            f"{expected_path.name} is missing — run gen_expected_mismatches.py first "
            "and review the edges it lists before verifying against them"
        )
    expected_mismatch = json.loads(expected_path.read_text())["edges"]

    lint = work(root, "lint")["data"]
    violations = {v["id"] for v in lint["track_violations"]}
    # C1 audits live and closed items on different terms, so the two views are
    # derived here rather than taken from whatever `work list` happens to
    # return. That default MOVED: protocol 1.13 widened a bare `work list` to
    # carry every status, where earlier versions omitted closed. This script
    # runs against whichever `work` is on PATH, which is not necessarily the
    # one in this checkout, so it must be correct under both — filtering a
    # superset costs nothing and reading the default costs correctness.
    listed = work(root, "list", "--limit", "0")["data"]["items"]
    items = [item for item in listed if item["status"] != "closed"]

    # Closed items are asked for explicitly, and still must be: a stray write to
    # a closed item would otherwise be invisible to C1, and `work track set` has
    # no status guard, so such a write is possible.
    closed = work(root, "list", "--limit", "0", "--status", "closed")["data"]["items"]

    failures: list[str] = []

    # C1 — the outcome matches the artifact, and the applicator stayed inside it.
    written = applied_ids(RUNLOG.read_text()) if RUNLOG.exists() else set()
    audit = audit_tracks(items, closed, assigned, written)
    if audit["mismatched"]:
        failures.append(
            f"C1 outcome != artifact: {audit['mismatched'][:5]} "
            f"({len(audit['mismatched'])} total)"
        )
    if audit["wrote_outside_artifact"]:
        failures.append(
            f"C1 run log records writes the artifact does not cover: "
            f"{audit['wrote_outside_artifact'][:5]} "
            f"({len(audit['wrote_outside_artifact'])} total)"
        )
    if audit["doubled"]:
        failures.append(
            f"C1 item carries multiple track labels: {audit['doubled'][:5]} "
            f"({len(audit['doubled'])} total)"
        )
    print(
        f"C1: {len(assigned) - len(audit['skipped_closed'])} live assigned item(s) compared; "
        f"{len(audit['skipped_closed'])} closed since the artifact was generated (not compared); "
        f"{audit['logged']} write(s) in the run log across all runs, "
        f"{audit['logged_in_scope']} of them naming items in this database"
    )

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
    # Compared as whole (child, parent, track) EDGES, not bare child ids. A child
    # reparented to a different non-milestone parent on a different track still
    # reports the same child id, so an id-only comparison would pass while the
    # reviewed edge silently changed.
    #
    # `work lint` keys these on "child", not "id" (report.py _track_mismatches).
    # The wrong key was invisible for as long as the list was empty: nothing is
    # labelled before the migration, so the loop body never ran. It only raised
    # once the migration materialized the mismatches — i.e. exactly when this
    # criterion is supposed to do its job.
    #
    # Checked both ways. A one-sided `actual - expected` passes when an expected
    # edge DISAPPEARS, which would mean the graph changed under us unnoticed.
    def edge(m: dict) -> tuple:
        return (m["child"], m["child_track"], m["parent"], m["parent_track"])

    # The expected set is filtered to edges whose BOTH endpoints are still live.
    # `work lint` omits closed items, so it cannot emit an edge whose child or
    # parent has closed since the artifact was generated — and `reconcile()`
    # correctly skipped that assignment. Retaining such an edge would report it
    # "missing" and reject an otherwise correct drift-tolerant migration. This is
    # the same false-failure shape as C1's closed-item comparison, in a second
    # criterion; both are the drift path, not a defect.
    live_ids = {item["id"] for item in items}
    actual_edges = {edge(m) for m in lint["track_mismatches"]}
    expected_edges = {
        edge(m)
        for m in expected_mismatch
        if m["child"] in live_ids and m["parent"] in live_ids
    }
    dropped = len(expected_mismatch) - len(expected_edges)
    if dropped:
        print(f"C5: {dropped} baseline edge(s) dropped — an endpoint closed since generation")
    unexpected = actual_edges - expected_edges
    missing = expected_edges - actual_edges
    if unexpected:
        failures.append(
            f"C5 unexpected cross-track edges: {sorted(unexpected)[:3]} "
            f"({len(unexpected)} beyond the expected {len(expected_edges)})"
        )
    if missing:
        failures.append(
            f"C5 expected cross-track edges absent: {sorted(missing)[:3]} "
            f"({len(missing)} missing) — the graph changed unexpectedly"
        )
    print(f"track_mismatches: {len(actual_edges)} edges (expected {len(expected_edges)})")

    # C6 — groom-state item exists, tracked ops-meta, exempt.
    if not groom_item:
        failures.append("C6 groom-state-item empty")
    else:
        got = work(root, "show", groom_item, require_ok=False)
        if not got.get("ok"):
            failures.append(f"C6 groom-state-item {groom_item} does not exist")
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
