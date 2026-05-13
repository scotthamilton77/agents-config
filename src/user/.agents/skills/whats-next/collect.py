#!/usr/bin/env python3
"""
whats-next/collect.py
Helper for the whats-next skill. Queries bd CLI, filters bead sets, resolves
full parent-chain ancestry with memoized lookups (each parent fetched at most
once regardless of how many children share it), and emits JSON for the agent
to render.

Usage:
    python3 collect.py [--limit N] [--mode MODE]

Exit codes:
    0 — success (JSON on stdout)
    1 — bd command unavailable or returned no data
"""

import argparse
import json
import re
import subprocess
import sys


# ---------------------------------------------------------------------------
# bd CLI helpers
# ---------------------------------------------------------------------------

def bd_json(*args):
    """Run a bd command and return parsed JSON list, or [] on any failure."""
    try:
        result = subprocess.run(
            ["bd"] + list(args),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, FileNotFoundError):
        return []


# ---------------------------------------------------------------------------
# Project prefix detection
# ---------------------------------------------------------------------------

def detect_prefix(beads):
    """
    Infer the common project prefix (e.g. 'agents-config') from bead IDs.
    Returns the prefix string or None if none is detectable.
    """
    ids = [b.get("id", "") for b in beads if b.get("id")]
    if len(ids) < 2:
        return None

    common = ids[0]
    for bid in ids[1:]:
        while common and not bid.startswith(common):
            common = common[:-1]
        if not common:
            return None

    last_dash = common.rfind("-")
    if last_dash <= 0:
        return None

    prefix = common[:last_dash]
    return prefix if len(prefix) >= 2 else None


# ---------------------------------------------------------------------------
# Memoized ancestry resolver
# ---------------------------------------------------------------------------

def resolve_all_ancestry(display_ids, known):
    """
    Walk parent chains for every bead in display_ids.

    Returns:
        dict of bead_id → list of ancestor IDs (root first, parent last).
    """
    frontier = set()
    for bid in display_ids:
        parent = known.get(bid, {}).get("parent", "")
        if parent and parent not in known:
            frontier.add(parent)

    fetched = set()
    while frontier:
        for pid in list(frontier):
            if pid not in known:
                data = bd_json("show", pid, "--json")
                if data:
                    known[pid] = data[0]
            fetched.add(pid)

        next_frontier = set()
        for pid in frontier:
            grandparent = known.get(pid, {}).get("parent", "")
            if grandparent and grandparent not in known and grandparent not in fetched:
                next_frontier.add(grandparent)
        frontier = next_frontier

    ancestry_map = {}
    for bid in display_ids:
        chain = []
        seen = {bid}
        current = known.get(bid, {}).get("parent", "")
        while current and current not in seen:
            seen.add(current)
            chain.append(current)
            current = known.get(current, {}).get("parent", "")
        chain.reverse()
        ancestry_map[bid] = chain

    return ancestry_map


# ---------------------------------------------------------------------------
# Container classification
# ---------------------------------------------------------------------------

CONTAINER_ALWAYS = {"milestone", "epic"}
CONTAINER_DESIGN = {"feature"}
# Container-design types are EXCLUDED from brainstorm-ready regardless of
# child count. Diverges intentionally from is_container (which uses
# CONTAINER_DESIGN + active-child probe) — see spec §"is_container vs
# CONTAINER_DESIGN_TYPES".
CONTAINER_DESIGN_TYPES = {"milestone", "epic", "feature", "decision"}

# Module-level dict; populated in main() before any is_container() call.
active_child_count = {}


def is_container(bead_id, bead_type):
    """True when bead should be hidden from brainstorm/impl lists.

    milestone / epic — always containers, regardless of children.
    feature         — container only when it has ≥1 non-closed children.
    """
    if bead_type in CONTAINER_ALWAYS:
        return True
    if bead_type in CONTAINER_DESIGN:
        return active_child_count.get(bead_id, 0) > 0
    return False


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def is_brainstorm_candidate(bead):
    labels = bead.get("labels", [])
    btype = bead.get("issue_type", "")
    return (
        btype not in CONTAINER_DESIGN_TYPES  # never brainstorm-ready
        and "implementation-ready" not in labels
        and "merge-gate" not in labels
        and "human" not in labels
        and not re.search(r"-mol-", bead.get("id", ""))
    )


def is_impl_candidate(bead):
    labels = bead.get("labels", [])
    btype = bead.get("issue_type", "")
    # milestone/epic are always containers; decision routes nowhere.
    # `feature` is dual-nature: a childless feature carrying
    # `implementation-ready` is the leaf impl bead produced by
    # brainstorm-bead finalize and MUST surface in the implementation
    # section. is_container() encodes that distinction.
    if btype in CONTAINER_ALWAYS or btype == "decision":
        return False
    return (
        "implementation-ready" in labels
        and "human" not in labels
        and not is_container(bead.get("id", ""), btype)
    )


def bead_sort_key(bead):
    return (bead.get("priority", 99), bead.get("created_at", ""))


# ---------------------------------------------------------------------------
# Typed ancestor extraction
# ---------------------------------------------------------------------------

def extract_typed_ancestors(bead_id, ancestry_map, known, shorten):
    """Return (milestone_col, feature_col, parent_epic_col) for one bead.

    chain[-1] = immediate parent; reverse to traverse parent-first so the
    NEAREST typed ancestor wins.
    """
    chain = ancestry_map.get(bead_id, [])
    milestone_col = next(
        (shorten(a) for a in reversed(chain)
         if known.get(a, {}).get("issue_type") == "milestone"),
        "",
    )
    feature_col = next(
        (shorten(a) for a in reversed(chain)
         if known.get(a, {}).get("issue_type") == "feature"),
        "",
    )
    parent_epic_col = shorten(chain[-1]) if chain else ""
    return milestone_col, feature_col, parent_epic_col


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch and filter beads for the whats-next skill."
    )
    parser.add_argument(
        "--limit", type=int, default=10, metavar="N",
        help="Max beads per section (0 = no limit, default 10)",
    )
    parser.add_argument(
        "--mode",
        choices=["default", "brainstorm", "implementation", "planning", "human"],
        default="default",
        help="Which section(s) to emit (default: human + planning_ready + brainstorm)",
    )
    args = parser.parse_args()
    limit = args.limit
    mode = args.mode

    # Fetch full source sets.
    human_raw = bd_json("list", "--label", "human", "--json")
    ready_raw = bd_json("ready", "--json")
    all_active = bd_json("list", "--status", "open,in_progress", "--json")

    # Build the active-child-count index in one O(N) pass.
    global active_child_count
    active_child_count = {}
    for b in all_active:
        parent = b.get("parent", "")
        if parent:
            active_child_count[parent] = active_child_count.get(parent, 0) + 1

    # Planning-ready: three separate --type queries (comma-separated --type
    # is not supported by the CLI). --ready gates on dep-unblocked.
    planning_raw = (
        bd_json("list", "--type", "milestone", "--ready", "--json")
        + bd_json("list", "--type", "epic", "--ready", "--json")
        + bd_json("list", "--type", "feature", "--ready", "--json")
    )

    def apply_limit(lst):
        return lst[:limit] if limit > 0 else lst

    # Filter and sort sections.
    human_sorted = sorted(
        [b for b in human_raw if b.get("status") != "closed"],
        key=bead_sort_key,
    )
    brainstorm_sorted = sorted(
        [b for b in ready_raw if is_brainstorm_candidate(b)],
        key=bead_sort_key,
    )
    impl_sorted = sorted(
        [b for b in ready_raw if is_impl_candidate(b)],
        key=bead_sort_key,
    )

    # Planning-ready: childless container beads with no human label.
    # Per the Filter Matrix in beads.md / epic-hygiene spec, the
    # `implementation-ready` label is treated as Rule C noise for
    # `milestone` and `epic` (still routed to planning-ready), and only
    # acts as an exclusion for `feature` — where `implementation-ready`
    # means the bead is a leaf impl bead produced by brainstorm-bead and
    # belongs in the implementation-ready section instead.
    def in_planning(b):
        if active_child_count.get(b.get("id", ""), 0) != 0:
            return False
        labels = b.get("labels", [])
        if "human" in labels:
            return False
        if b.get("issue_type") == "feature" and "implementation-ready" in labels:
            return False
        return True

    planning_sorted = sorted(
        [b for b in planning_raw if in_planning(b)],
        key=bead_sort_key,
    )

    # De-dupe planning_sorted by id (three queries may overlap if anything
    # ever satisfies more than one --type filter, defensive).
    seen_ids = set()
    planning_deduped = []
    for b in planning_sorted:
        bid = b.get("id")
        if bid and bid not in seen_ids:
            seen_ids.add(bid)
            planning_deduped.append(b)
    planning_sorted = planning_deduped

    totals = {
        "human": len(human_sorted),
        "planning_ready": len(planning_sorted),
        "brainstorm": len(brainstorm_sorted),
        "implementation": len(impl_sorted),
    }

    human_beads = apply_limit(human_sorted)
    brainstorm_beads = apply_limit(brainstorm_sorted)
    impl_beads = apply_limit(impl_sorted)
    planning_beads = apply_limit(planning_sorted)

    # Build `known` map from every fetched bead — supports typed-ancestor
    # resolution (we need each ancestor's issue_type to classify it).
    all_fetched = human_raw + ready_raw + all_active + planning_raw
    known = {}
    for b in all_fetched:
        bid = b.get("id")
        if bid:
            known[bid] = b

    prefix = detect_prefix(all_fetched)

    def shorten(bid):
        if prefix and bid.startswith(prefix + "-"):
            return bid[len(prefix) + 1:]
        return bid

    display_ids = (
        [b["id"] for b in human_beads]
        + [b["id"] for b in brainstorm_beads]
        + [b["id"] for b in impl_beads]
        + [b["id"] for b in planning_beads]
    )
    ancestry_map = resolve_all_ancestry(display_ids, known)

    def enrich(beads):
        result = []
        for b in beads:
            milestone_col, feature_col, parent_epic_col = extract_typed_ancestors(
                b["id"], ancestry_map, known, shorten,
            )
            result.append({
                "id": b["id"],
                "short_id": shorten(b["id"]),
                "priority": b.get("priority"),
                "title": b.get("title", ""),
                "labels": b.get("labels", []),
                "milestone_col": milestone_col,
                "feature_col": feature_col,
                "parent_epic_col": parent_epic_col,
                "type": b.get("issue_type", ""),
            })
        return result

    # Bail if there's nothing in any source AT ALL — preserves prior
    # "bd unavailable" exit-1 behavior. Don't bail just because one mode has
    # no data; argparse-rejection probes (test T3) tolerate exit 1.
    if not human_raw and not ready_raw and not all_active and not planning_raw:
        sys.exit(1)

    output = {
        "mode": mode,
        "project_prefix": prefix,
        "limit": limit,
        "totals": totals,
    }

    # Per spec §"--mode contract": absent sections are ABSENT from JSON,
    # not empty arrays.
    if mode == "default":
        output["human"] = enrich(human_beads)
        output["planning_ready"] = enrich(planning_beads)
        output["brainstorm"] = enrich(brainstorm_beads)
    elif mode == "brainstorm":
        output["brainstorm"] = enrich(brainstorm_beads)
    elif mode == "implementation":
        output["implementation"] = enrich(impl_beads)
    elif mode == "planning":
        output["planning_ready"] = enrich(planning_beads)
    elif mode == "human":
        output["human"] = enrich(human_beads)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
