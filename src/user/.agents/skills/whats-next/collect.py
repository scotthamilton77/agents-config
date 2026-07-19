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
from datetime import datetime, timezone


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


# The workcli envelope's protocol MAJOR version this integration understands
# (README.md's "Consumer handshake": pin MAJOR, refuse a mismatch rather than
# risk mis-parsing). A PATH-shadowed or unrelated "work" binary can still
# exit 0 with a superficially valid {"ok": true, "data": {...}} shape, so the
# protocol field is the one thing that actually attests this came from a
# compatible workcli (Codex finding, round 5).
_COMPATIBLE_PROTOCOL_MAJOR = "1"
# The envelope contract requires semver MAJOR.MINOR exactly -- both numeric,
# no trailing/leading junk -- so a permissive split(".")[0] check would wrongly
# accept "1", "1.", or "1-shadowed" (Codex finding, round 6).
_PROTOCOL_PATTERN = re.compile(r"^(\d+)\.(\d+)$")


def work_groom_status():
    """Best-effort `work groom --status` call for the backlog-grooming nag line.

    Self-silences on ANY failure -- `work` not on PATH, a non-zero exit, an
    unparseable envelope, an incompatible/missing protocol version, or an
    `ok: false` envelope (e.g. E_NOT_CONFIGURED -- the real case in THIS repo
    today, since its own groom-state-bead is still blank pending the backfill
    migration) -- returns None rather than raising or printing, mirroring
    bd_json's discipline above. Distinct from that ceremony's own state: this
    is workcli's Backlog Grooming nag, never to be confused with CONTEXT.md's
    separate Holding-Place Grooming Nag.
    """
    try:
        result = subprocess.run(
            ["work", "groom", "--status"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # A non-zero exit is a documented self-silencing failure; parsing
            # stdout anyway risks accepting a stale/partial envelope a
            # wrapper or half-failed `work` binary wrote before exiting
            # non-zero (Codex finding).
            return None
        envelope = json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
        # OSError (a superclass of FileNotFoundError) also covers a `work`
        # that resolves on PATH but can't be executed -- lost +x bit, a
        # noexec mount -- which subprocess.run raises as PermissionError,
        # a plain FileNotFoundError catch would miss (Codex finding).
        # UnicodeDecodeError (not an OSError subclass) covers a corrupted or
        # PATH-shadowed binary writing non-UTF-8 bytes: subprocess.run's
        # text=True decoding raises it before json.loads ever runs (Codex
        # finding, round 6).
        return None
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        # Valid JSON that isn't an envelope object (e.g. a PATH-shadowed
        # `work` emitting `[]`) must self-silence too, not crash .get() with
        # AttributeError (Codex finding). `is not True` (not a truthiness
        # check) so an envelope carrying "ok": "true" (a string) or any
        # other truthy-but-wrong value doesn't slip past self-silencing.
        return None
    protocol = envelope.get("protocol")
    protocol_match = isinstance(protocol, str) and _PROTOCOL_PATTERN.match(protocol)
    if not protocol_match or protocol_match.group(1) != _COMPATIBLE_PROTOCOL_MAJOR:
        # A PATH-shadowed or incompatible "work" can still emit an
        # {"ok": true, ...} shape; only a matching protocol MAJOR actually
        # attests this came from a compatible workcli (Codex finding). The
        # envelope contract requires semver MAJOR.MINOR exactly -- a bare
        # split(".")[0] would wrongly accept "1", "1.", or "1-shadowed" as
        # long as the first segment happened to read "1" (Codex finding,
        # round 6), so the full string is matched against a strict pattern.
        return None
    data = envelope.get("data")
    return data if isinstance(data, dict) else None


def backlog_grooming_nag_line(status):
    """Render the one-line nag from a `work groom --status` data dict, or
    None when not breached (or status is None -- the call failed/unavailable).
    """
    if not status or status.get("breached") is not True:
        # `is not True`, not a truthiness check: a stale/wrong `work` build
        # emitting {"breached": "false"} (a truthy string) must self-silence,
        # not add a nag because the value happened to be non-empty (Codex
        # finding).
        return None
    days_since = status.get("days_since")
    if days_since is not None:
        return (
            f"Backlog Grooming overdue ({days_since} days since last groomed) — "
            "run 'work groom --done' after triage."
        )
    return "Backlog Grooming overdue — run 'work groom --done' after triage."


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
# Container classification
# ---------------------------------------------------------------------------
#
# A *container bead* groups related work — it does not carry executable work
# itself. The three rules below govern how containers move through the
# readiness lists; the Filter Matrix beneath them is the authoritative
# routing spec for this skill (whats-next).
#
# Container detection:
#   - milestone / epic         — always a container, regardless of children.
#   - feature with ≥1 non-closed children — container.
#   - feature with no children — NOT a container (it's either a planning-
#                                ready placeholder or, if it carries
#                                `implementation-ready`, the leaf impl bead
#                                produced by brainstorm-bead finalize).
#   - decision                 — informational; excluded from all ready lists.
#
# The three rules (governing convention, enforced structurally where noted):
#   Rule A — No executable work (convention). A container's acceptance
#     criteria should reduce to "all children/named-children closed."
#     Verification not automatic from child closure lives in a leaf child.
#   Rule B — Never surfaces in brainstorm or implementation ready lists
#     (STRUCTURAL — enforced here by is_brainstorm_candidate /
#     is_impl_candidate). Planning-ready intentionally surfaces childless
#     container beads — that is its purpose.
#   Rule C — No readiness labels (convention). Containers must not carry
#     `implementation-ready`, `implementation-readied-session-*`,
#     `brainstormed`, or `human`. brainstorm-bead finalize's Step 0
#     container gate prevents future stamping; migrations strip violators.
#     This filter prevents surfacing even when labels exist (defence in
#     depth).
#
# Filter Matrix (routing by type × non-closed-children × labels):
#
#   Read this matrix top-down: the human-attention row applies FIRST. For
#   every other row, treat the `human` column as implicitly `no` — a bead
#   carrying `human` routes to human-attention only, period.
#
#   | Type        | Children | impl-ready | human | Routing                        |
#   |-------------|----------|------------|-------|--------------------------------|
#   | any         | any      | any        | yes   | human-attention only           |
#   | milestone   | 0        | no         | no    | planning-ready                 |
#   | milestone   | 0        | yes        | no    | planning-ready (Rule C noise)  |
#   | milestone   | ≥1       | any        | no    | hidden                         |
#   | epic        | 0        | no         | no    | planning-ready                 |
#   | epic        | 0        | yes        | no    | planning-ready (Rule C noise)  |
#   | epic        | ≥1       | any        | no    | hidden                         |
#   | feature     | 0        | no         | no    | planning-ready                 |
#   | feature     | 0        | yes        | no    | impl-ready (leaf impl bead)    |
#   | feature     | ≥1       | any        | no    | hidden (active container)      |
#   | decision    | any      | any        | no    | nowhere                        |
#   | task / bug /| any      | no         | no    | brainstorm-ready               |
#   | chore /     |          |            |       |                                |
#   | story / spike| any     | yes        | no    | impl-ready                     |

CONTAINER_ALWAYS = {"milestone", "epic"}
CONTAINER_DESIGN = {"feature"}
# Types EXCLUDED from brainstorm-ready regardless of child count.
# Diverges intentionally from is_container (which uses CONTAINER_DESIGN +
# active-child probe): `decision` is informational, never brainstormed;
# the three container-design types are spec-prohibited from brainstorm
# routing whether or not they currently have children.
BRAINSTORM_EXCLUDED_TYPES = {"milestone", "epic", "feature", "decision"}

# Module-level dict; populated in main() before any is_container() call.
active_child_count = {}


def is_container(bead_id, bead_type):
    """True when bead should be hidden from brainstorm/impl lists.

    milestone / epic — always containers, regardless of children.
    feature         — container only when it has ≥1 non-closed children
                      that are NOT formula-gate children. The
                      active_child_count index below excludes children
                      labeled `merge-gate` or `human` (without
                      `hep-pause`) so feature-Y impl beads (which always
                      carry a merge-gate child via brainstorm finalize
                      step 5b) don't get misclassified as containers.
                      `human + hep-pause` children ARE counted — those
                      are live HEP escalations under container sources
                      and keep the parent classified as a container
                      while human input is pending.
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
        btype not in BRAINSTORM_EXCLUDED_TYPES  # never brainstorm-ready
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
# In-flight (claimed) beads
# ---------------------------------------------------------------------------
#
# `bd ready` (the source for every section above) only ever returns
# `status: open` beads, so a bead left `in_progress` by a dead or abandoned
# session is invisible to every list above it. This section surfaces every
# in_progress bead directly, oldest claim first, so a stale claim gets
# caught instead of silently blocking whoever would otherwise pick up the
# work it's still holding.
#
# Authoritative rationale for the section's independence: in_flight is a
# cross-cutting audit list, not a mode-selected work queue — it is never
# gated by --mode, never truncated by --limit, and never filtered by
# --label. The whole point is to surface EVERY stale claim, not a top-N
# or per-queue sample of them.

PR_URL_RE = re.compile(r"https://github\.com/\S+/pull/\d+")


def parse_bd_timestamp(ts):
    """Parse a bd ISO-8601 UTC timestamp (e.g. '2026-07-04T17:58:57Z') to a
    timezone-aware datetime. Returns None on missing/non-string/unparseable
    input so callers degrade gracefully instead of raising.

    An offsetless ISO string (no trailing 'Z' or explicit offset) parses to a
    naive datetime; it is coerced to UTC so every non-None return is aware.
    This keeps downstream arithmetic against `datetime.now(timezone.utc)`
    (claim_age_days) and comparison against an aware `datetime.max`
    (build_in_flight's sort key) from raising TypeError on naive/aware mixes.
    """
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def claim_age_days(started_at):
    """Whole days elapsed since a bead's `started_at` timestamp.

    `started_at` is the field used here, not `updated_at`: bd stamps
    `started_at` once, at the moment a bead's status transitions to
    in_progress, and it does not move on later edits. `updated_at` does
    move on any field edit (e.g. a notes update), so a bead claimed weeks
    ago with a recent notes edit would understate its claim age under
    `updated_at`.

    Returns None when unparseable, so the caller can render a dash rather
    than a bogus age.
    """
    ts = parse_bd_timestamp(started_at)
    if ts is None:
        return None
    return max(0, (datetime.now(timezone.utc) - ts).days)


def build_in_flight(all_active, shorten):
    """Build the 'In flight (claimed)' section: every bead with status
    in_progress, sorted oldest claim first.

    Flags beads whose notes carry a GitHub PR URL (recorded per interim
    protocol 9.3) as candidates for retroactive delivery — the work may
    already be done and merged, with the claim simply never closed out.

    `all_active` (bd list --status open,in_progress) already carries
    `notes` — bd list --json includes it by default, no --long needed —
    so no extra `bd show` calls are required here.
    """
    in_flight = [b for b in all_active if b.get("status") == "in_progress"]

    def sort_key(bead):
        # Unparseable/missing timestamps can't be placed by age — push
        # them to the end rather than guessing they're the oldest.
        return parse_bd_timestamp(bead.get("started_at")) or datetime.max.replace(
            tzinfo=timezone.utc
        )

    in_flight.sort(key=sort_key)

    result = []
    for b in in_flight:
        result.append({
            "id": b["id"],
            "short_id": shorten(b["id"]),
            "title": b.get("title", ""),
            "assignee": b.get("assignee") or "",
            "claim_age_days": claim_age_days(b.get("started_at")),
            "pr_flagged": bool(PR_URL_RE.search(b.get("notes") or "")),
        })
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def select_section_beads(mode, human_beads, planning_beads, brainstorm_beads, impl_beads):
    """Canonical mode->sections mapping.

    Parallel implementation: the output-emission if/elif in main()
    encodes the same mapping. Keep them in sync.
    """
    if mode == "all":
        return human_beads + planning_beads + brainstorm_beads + impl_beads
    if mode == "human":
        return human_beads
    if mode == "brainstorm":
        return brainstorm_beads
    if mode == "implementation":
        return impl_beads
    if mode == "planning":
        return planning_beads
    return []  # unreachable under argparse choices=


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
        choices=["all", "brainstorm", "implementation", "planning", "human"],
        default="all",
        help="Which section(s) to emit (all: human + planning_ready + brainstorm + implementation)",
    )
    parser.add_argument(
        "--label", default=None, metavar="LABEL",
        help="Restrict every mode-selected queue (human/planning/brainstorm/"
             "implementation) to beads whose own labels include LABEL "
             "(case-insensitive exact match). Does NOT filter `in_flight` — "
             "that section is an unscoped stale-claim audit and always shows "
             "every in_progress bead regardless of --label. The caller is "
             "responsible for reducing a natural-language qualifier to its "
             "canonical label (e.g. installer/installation -> install).",
    )
    args = parser.parse_args()
    limit = args.limit
    mode = args.mode
    label_filter = args.label.lower() if args.label else None

    def has_label(bead):
        if label_filter is None:
            return True
        return label_filter in {str(x).lower() for x in (bead.get("labels") or [])}

    # Fetch full source sets.
    # NOTE: pass `--limit 0` on every `bd list` call so the unbounded
    # inventory is returned. `bd list` defaults to a 50-row page; without
    # `--limit 0`, the active-child-count index below can drop children
    # for any parent whose children fall past row 50, which then
    # misclassifies feature-with-children containers as childless leaves.
    human_raw = bd_json("list", "--label", "human", "--limit", "0", "--json")
    # `--limit 0` so the full ready set is returned. `bd ready` defaults to a
    # 100-row page; without this, brainstorm/implementation sections (and their
    # totals) silently drop any candidate past row 100.
    ready_raw = bd_json("ready", "--limit", "0", "--json")
    all_active = bd_json("list", "--status", "open,in_progress", "--limit", "0", "--json")

    # Build the active-child-count index in one O(N) pass.
    # IMPORTANT: this index is safety-critical for feature-container
    # detection. The inventory above is fetched with `--limit 0`; if the
    # query were to silently degrade to an empty list (e.g. via a bd
    # failure swallowed upstream) while `bd ready` succeeded, features
    # with active children would be misclassified as childless and leak
    # into the implementation queue. Fail closed when the inventory is
    # empty but `bd ready` returned non-container leaf beads — that is
    # the inconsistency signal.
    if not all_active and ready_raw:
        print(
            "ERROR: bd list --status open,in_progress --limit 0 returned empty while "
            "bd ready returned beads — active-child index would be unsafe; aborting.",
            file=sys.stderr,
        )
        sys.exit(1)
    global active_child_count
    active_child_count = {}
    for b in all_active:
        parent = b.get("parent", "")
        if not parent:
            continue
        labels = b.get("labels", []) or []
        # Exclude formula-gate / verify-follow-up children from the count.
        # brainstorm-bead finalize step 5b creates `merge-gate` and (when
        # AC has [h] lines) `human`-labeled `[Human verify]` children
        # under feature-Y impl beads. These don't make Y a container.
        # IMPORTANT: bare `human` children are formula-gate artifacts and
        # are excluded, BUT `human` children that also carry `hep-pause`
        # are live HEP escalations (created by the HEP procedure under
        # container sources) — those MUST count so the container stays
        # classified while human input is pending.
        if "merge-gate" in labels or ("human" in labels and "hep-pause" not in labels):
            continue
        active_child_count[parent] = active_child_count.get(parent, 0) + 1

    # Planning-ready: three separate --type queries (comma-separated --type
    # is not supported by the CLI). --ready gates on dep-unblocked.
    # `--limit 0` for the same unbounded-inventory reason as above.
    planning_raw = (
        bd_json("list", "--type", "milestone", "--ready", "--limit", "0", "--json")
        + bd_json("list", "--type", "epic", "--ready", "--limit", "0", "--json")
        + bd_json("list", "--type", "feature", "--ready", "--limit", "0", "--json")
    )

    def apply_limit(lst):
        return lst[:limit] if limit > 0 else lst

    # Filter and sort sections.
    human_sorted = sorted(
        [b for b in human_raw if b.get("status") != "closed" and has_label(b)],
        key=bead_sort_key,
    )
    brainstorm_sorted = sorted(
        [b for b in ready_raw if is_brainstorm_candidate(b) and has_label(b)],
        key=bead_sort_key,
    )
    impl_sorted = sorted(
        [b for b in ready_raw if is_impl_candidate(b) and has_label(b)],
        key=bead_sort_key,
    )

    # Planning-ready: childless container beads with no human label.
    # Per the Filter Matrix in this module's docstring above (the
    # canonical home of the routing spec), the `implementation-ready`
    # label is treated as Rule C noise for `milestone` and `epic` (still
    # routed to planning-ready), and only acts as an exclusion for
    # `feature` — where `implementation-ready` means the bead is a leaf
    # impl bead produced by brainstorm-bead and belongs in the
    # implementation-ready section instead.
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
        [b for b in planning_raw if in_planning(b) and has_label(b)],
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

    display_ids = [b["id"] for b in select_section_beads(mode, human_beads, planning_beads, brainstorm_beads, impl_beads)]
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

    # Never gated by --mode/--limit/--label — see the "In-flight (claimed)
    # beads" section comment above build_in_flight for the rationale.
    in_flight_beads = build_in_flight(all_active, shorten)
    totals["in_flight"] = len(in_flight_beads)

    output = {
        "mode": mode,
        "project_prefix": prefix,
        "limit": limit,
        "totals": totals,
    }

    # Per spec §"--mode contract": absent sections are ABSENT from JSON,
    # not empty arrays. Exception: `in_flight` (and `totals.in_flight`) is
    # mode-independent and ALWAYS present — see the in-flight section comment.
    if mode == "all":
        output["human"] = enrich(human_beads)
        output["planning_ready"] = enrich(planning_beads)
        output["brainstorm"] = enrich(brainstorm_beads)
        output["implementation"] = enrich(impl_beads)
    elif mode == "brainstorm":
        output["brainstorm"] = enrich(brainstorm_beads)
    elif mode == "implementation":
        output["implementation"] = enrich(impl_beads)
    elif mode == "planning":
        output["planning_ready"] = enrich(planning_beads)
    elif mode == "human":
        output["human"] = enrich(human_beads)

    # Mode-independent, like `totals` (see the in-flight section comment).
    output["in_flight"] = in_flight_beads

    # Best-effort, self-silencing (see work_groom_status docstring): key is
    # present only when breached, absent otherwise -- same absent-not-empty
    # convention as the mode-gated sections above.
    nag_line = backlog_grooming_nag_line(work_groom_status())
    if nag_line is not None:
        output["backlog_grooming_nag"] = nag_line

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
