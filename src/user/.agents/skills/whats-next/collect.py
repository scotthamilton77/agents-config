#!/usr/bin/env python3
"""
whats-next/collect.py
Helper for the whats-next skill. Queries bd CLI, filters bead sets, resolves
full parent-chain ancestry with memoized lookups (each parent fetched at most
once regardless of how many children share it), and emits JSON for the agent
to render.

Usage:
    python3 collect.py [--limit N]   # N=10 default; 0=no limit

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

    Strategy: find the longest common string prefix across all IDs, then
    trim it back to the last '-' boundary. Requires at least 2 beads and
    a prefix of at least 2 chars.
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

    Optimised: collects all unique parent IDs up-front, fetches each unknown
    parent via bd show exactly once (regardless of how many children share it),
    then builds the full chain map. No redundant CLI calls.

    Args:
        display_ids: list of bead IDs whose ancestry we need.
        known: dict of id→bead (pre-populated from bd ready / bd list output).
               Modified in-place as parents are fetched.

    Returns:
        dict of bead_id → list of ancestor IDs (root first, parent last).
    """
    # Phase 1: iteratively discover and fetch all unknown parents.
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

    # Phase 2: build root-first ancestry chain for each display bead.
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
# Filters
# ---------------------------------------------------------------------------

def is_brainstorm_candidate(bead):
    labels = bead.get("labels", [])
    return (
        "implementation-ready" not in labels
        and "merge-gate" not in labels
        and "human" not in labels
        and not re.search(r"-mol-", bead.get("id", ""))
    )


def is_impl_candidate(bead):
    return "implementation-ready" in bead.get("labels", [])


def bead_sort_key(bead):
    return (bead.get("priority", 99), bead.get("created_at", ""))


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
    args = parser.parse_args()
    limit = args.limit

    # Fetch full source sets (needed for memoized parent lookups).
    human_raw = bd_json("list", "--label", "human", "--json")
    ready_raw = bd_json("ready", "--json")

    if not human_raw and not ready_raw:
        sys.exit(1)

    def apply_limit(lst):
        return lst[:limit] if limit > 0 else lst

    # Filter and sort all three sections, compute pre-limit totals.
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

    totals = {
        "human":          len(human_sorted),
        "brainstorm":     len(brainstorm_sorted),
        "implementation": len(impl_sorted),
    }

    # Apply limit after sorting (ancestry resolved only for displayed beads).
    human_beads      = apply_limit(human_sorted)
    brainstorm_beads = apply_limit(brainstorm_sorted)
    impl_beads       = apply_limit(impl_sorted)

    # Build known map from full raw sets for efficient parent lookups.
    all_fetched = human_raw + ready_raw
    known = {b["id"]: b for b in all_fetched if b.get("id")}

    # Detect project prefix.
    prefix = detect_prefix(all_fetched)

    def shorten(bid):
        if prefix and bid.startswith(prefix + "-"):
            return bid[len(prefix) + 1:]
        return bid

    # Resolve ancestry only for the beads we'll display.
    display_ids = (
        [b["id"] for b in human_beads]
        + [b["id"] for b in brainstorm_beads]
        + [b["id"] for b in impl_beads]
    )
    ancestry_map = resolve_all_ancestry(display_ids, known)

    def enrich(beads):
        result = []
        for b in beads:
            anc = ancestry_map.get(b["id"], [])
            feature    = shorten(anc[0]) if anc else ""
            epic_chain = " → ".join(shorten(a) for a in anc[1:]) if len(anc) > 1 else ""
            result.append({
                "id":         b["id"],
                "short_id":   shorten(b["id"]),
                "priority":   b.get("priority"),
                "title":      b.get("title", ""),
                "labels":     b.get("labels", []),
                "feature":    feature,
                "epic_chain": epic_chain,
            })
        return result

    output = {
        "project_prefix": prefix,
        "limit":          limit,
        "totals":         totals,
        "human":          enrich(human_beads),
        "brainstorm":     enrich(brainstorm_beads),
        "implementation": enrich(impl_beads),
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
