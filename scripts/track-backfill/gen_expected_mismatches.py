#!/usr/bin/env python3
"""Regenerate `expected_mismatches.json` from the assignment and the live graph.

Usage:
    python3 scripts/track-backfill/gen_expected_mismatches.py

`verify.py` criterion 5 compares the cross-track parent-child edges `work lint`
reports after the migration against this file. The edge set is *derived* — it is
a function of `assignment.json` and the current parent graph — but it was
maintained by hand, so a re-decided assignment silently invalidated it and the
criterion it feeds. Deriving it removes the class.

Mirrors `_track_mismatches` in workcli's report module exactly: an edge exists
when a non-milestone child and its non-milestone parent both resolve to a track
and those tracks differ. Post-migration track means the artifact's assignment
where it covers the item, and the item's current track otherwise — which is what
makes items outside the artifact (already tracked, or deliberately excluded)
count toward the edges the migration will produce.

Run this before `verify.py`, and re-run it whenever the assignment or the parent
graph changes. Review its output rather than trusting it: an edge that appears
here is a cross-track parenting the migration is about to make real.
"""

from __future__ import annotations

import json

from context import HERE, data, resolve_root

ARTIFACT = HERE / "assignment.json"
TARGET = HERE / "expected_mismatches.json"


def post_track(item: dict, assignment: dict[str, str]) -> str | None:
    """The track this item carries once the artifact is applied."""
    return assignment.get(item["id"]) or item.get("track")


def cross_track_edges(items: list[dict], assignment: dict[str, str]) -> list[dict]:
    by_id = {item["id"]: item for item in items}
    edges = []
    for item in items:
        # Milestones are excluded on BOTH sides of the edge, matching lint, which
        # filters them out of its item list before the walk and skips them again
        # as parents. A milestone carrying a track is out of contract rather than
        # impossible -- raw label writes bypass the gate -- and an edge emitted
        # here that lint will never report is one verify.py can never reconcile.
        if item.get("type") == "milestone":
            continue
        parent_id = item.get("parent")
        if parent_id is None or parent_id not in by_id:
            continue
        parent = by_id[parent_id]
        if parent.get("type") == "milestone":
            continue
        child_track = post_track(item, assignment)
        parent_track = post_track(parent, assignment)
        if child_track and parent_track and child_track != parent_track:
            edges.append(
                {
                    "child": item["id"],
                    "child_track": child_track,
                    "parent": parent_id,
                    "parent_track": parent_track,
                }
            )
    return sorted(edges, key=lambda edge: edge["child"])


def main() -> None:
    root = resolve_root(require_artifact=ARTIFACT)
    doc = json.loads(ARTIFACT.read_text())
    assignment = {item_id: entry["track"] for item_id, entry in doc["items"].items()}
    items = data(root, "list", "--limit", "0")["items"]

    edges = cross_track_edges(items, assignment)
    TARGET.write_text(
        json.dumps(
            {
                "edges": edges,
                "count": len(edges),
                "generated_for": doc.get("generated_for"),
                "note": (
                    "Derived from assignment.json plus the live parent graph. "
                    "Regenerate with gen_expected_mismatches.py whenever either changes."
                ),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"{len(edges)} expected cross-track edge(s) -> {TARGET}")
    for edge in edges:
        print(
            f"  {edge['child']} ({edge['child_track']})"
            f" under {edge['parent']} ({edge['parent_track']})"
        )


if __name__ == "__main__":
    main()
