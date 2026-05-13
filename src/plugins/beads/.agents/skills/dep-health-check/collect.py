#!/usr/bin/env python3
"""
dep-health-check/collect.py

Gather the bead inventory plus deterministic dep-graph findings for the
dep-health-check skill. The LLM body consumes this JSON, classifies each
finding's confidence, and renders the report.

Usage:
    python3 collect.py --mode all
    python3 collect.py --mode focused --target <bead-id>

Exit codes:
    0 — success (JSON on stdout)
    2 — usage / unknown args (argparse default)
    3 — `bd` not on PATH
    4 — bd database not found
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import OrderedDict


# ---------------------------------------------------------------------------
# Typed sentinel exceptions
# ---------------------------------------------------------------------------

class BdMissing(Exception):
    """bd binary not found on PATH."""

class DbMissing(Exception):
    """bd binary present but no reachable beads database."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_CONTENT_CAP = 600_000     # ~150K tokens at ~4 chars/tok; leaves headroom for LLM body in sonnet[1m] context
PER_BEAD_TRUNCATE_LEN = 4_000   # hard truncation per bead when total cap is exceeded
PER_COMMENT_TRUNCATE_LEN = 1_000  # per-comment cap; comments are summed into content_chars() so large threads must also be bounded
FOCUSED_BEAD_CAP = 200          # spec R8 explicit cap; prevents runaway child-chain expansion
MAX_CHILD_DEPTH = 50            # guards against pathological cycles; child trees are <10 deep in practice

# Dep types we expand through for focused-mode 1-hop neighborhood.
NEIGHBORHOOD_TYPES = {"blocks", "discovered-from", "tracks", "relates-to"}


# ---------------------------------------------------------------------------
# bd CLI helpers
# ---------------------------------------------------------------------------

def bd_json(*args, allow_fail=False):
    """Run `bd <args> --json` (caller passes --json explicitly). Return
    parsed JSON list. On failure: return [] when allow_fail=True; else raise
    a RuntimeError with stderr captured."""
    try:
        result = subprocess.run(
            ["bd"] + list(args),
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise BdMissing()
    except subprocess.TimeoutExpired:
        if allow_fail:
            return []
        raise RuntimeError("bd timed out")

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        # Heuristic: db-not-found markers.
        markers = ("database", "no such file", "not a beads", "not initialized",
                   "no beads", "could not open")
        low = stderr.lower()
        if any(m in low for m in markers):
            raise DbMissing(stderr[:200])
        if allow_fail:
            return []
        raise RuntimeError("bd failed: " + stderr[:200])

    try:
        return json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        if allow_fail:
            return []
        raise RuntimeError("bd JSON parse failed")


def bd_text(*args):
    """Run a bd command for plain-text output. Returns (rc, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["bd"] + list(args),
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (1, "", "")
    return (result.returncode, result.stdout or "", result.stderr or "")


# ---------------------------------------------------------------------------
# Project prefix detection (mirrors whats-next/collect.py)
# ---------------------------------------------------------------------------

def detect_prefix(beads):
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
# Db reachability probe
# ---------------------------------------------------------------------------

def db_reachable():
    """Return True iff bd can reach a db from cwd. Primary signal is the
    presence of a `.beads/` directory in cwd or any ancestor — this is the
    canonical location of a beads database. bd itself happily returns an
    empty list with a warning when no config is found, so we cannot rely on
    bd's exit code alone."""
    # 1. Filesystem probe: any ancestor containing .beads/ ?
    cur = os.getcwd()
    while True:
        if os.path.isdir(os.path.join(cur, ".beads")):
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    # 2. Fallback: bd probe. Even when no .beads/ exists, bd may resolve a
    # configured db elsewhere. Treat a clean bd run with stderr that does NOT
    # mention "no beads configuration found" as reachable.
    rc, _out, err = bd_text("list", "--json", "--limit", "1")
    if rc == 0:
        low = (err or "").lower()
        if "no beads configuration found" in low or "no beads configuration" in low:
            return False
        return True

    # bd failed — surface as not reachable.
    return False


# ---------------------------------------------------------------------------
# Per-bead detail with sparse-field defaults
# ---------------------------------------------------------------------------

def fetch_bead_detail(bead_id):
    """`bd show <id> --json` with safe defaults for sparse fields."""
    data = bd_json("show", bead_id, "--json", allow_fail=True)
    if not data:
        return None
    d = data[0]
    d.setdefault("description", "")
    d.setdefault("notes", "")
    d.setdefault("parent", "")
    d.setdefault("dependencies", [])
    d.setdefault("dependents", [])
    d.setdefault("comments", [])
    return d


def content_chars(bead):
    parts = [
        bead.get("title", "") or "",
        bead.get("description", "") or "",
        bead.get("notes", "") or "",
        bead.get("design", "") or "",
        bead.get("acceptance_criteria", "") or "",
    ]
    for c in bead.get("comments", []) or []:
        if isinstance(c, dict):
            parts.append(c.get("body", "") or c.get("text", "") or "")
        else:
            parts.append(str(c))
    return sum(len(p) for p in parts)


def truncate_bead_content(bead, limit=PER_BEAD_TRUNCATE_LEN,
                          comment_limit=PER_COMMENT_TRUNCATE_LEN):
    """Truncate per-field text and per-comment bodies in-place. Only flag
    ``bead["truncated"] = True`` when at least one field or comment was
    actually shortened — otherwise the marker is dishonest (it claims a
    reduction that did not occur) and disconnected from real token savings.

    Comments are included because ``content_chars()`` counts them; large
    comment threads would otherwise blow past the token guard even after
    'truncation' clipped only the top-level fields."""
    modified = False
    for k in ("description", "notes", "design", "acceptance_criteria"):
        v = bead.get(k, "") or ""
        if len(v) > limit:
            bead[k] = v[:limit] + "\n…[truncated]"
            modified = True

    comments = bead.get("comments") or []
    if isinstance(comments, list):
        for c in comments:
            if isinstance(c, dict):
                for key in ("body", "text"):
                    cv = c.get(key)
                    if isinstance(cv, str) and len(cv) > comment_limit:
                        c[key] = cv[:comment_limit] + "\n…[truncated]"
                        modified = True

    if modified:
        bead["truncated"] = True
    return modified


# ---------------------------------------------------------------------------
# Deterministic findings
# ---------------------------------------------------------------------------

def _resolve_id(suffix, beads_by_id):
    """Resolve a possibly-short bead id (e.g. '3up3') against the known
    inventory. Returns the full id, or None when the suffix is unknown OR
    matches more than one bead (ambiguous short-id — refuse rather than
    guess; under --just-fix-it a guess could auto-apply a dep edge to the
    wrong bead)."""
    if not suffix:
        return None
    if suffix in beads_by_id:
        return suffix
    matches = [c for c in beads_by_id if c.endswith("-" + suffix)]
    if len(matches) == 1:
        return matches[0]
    return None


def find_provenance_mismatches(beads_by_id):
    """Spec R7 — provenance labels on either side must have a matching
    `discovered-from` dep edge:

    - X-side: bead X carries `produced-bead-Y` → expect edge
      `bd dep add Y X --type discovered-from`.
    - Y-side: bead Y carries `produced-from-X` → expect the same edge.

    Both passes are de-duplicated by (dependent_id, blocker_id) so a bead
    pair that carries both labels is reported once."""
    out = []
    seen = set()

    def _emit(dependent, blocker, source_label, source_side):
        key = (dependent, blocker)
        if key in seen:
            return
        seen.add(key)
        # Expected edge: dependent depends-on blocker with type discovered-from.
        dep_bead = beads_by_id.get(dependent)
        has_edge = False
        for dep in (dep_bead or {}).get("dependencies", []) or []:
            if not isinstance(dep, dict):
                continue
            if dep.get("id") == blocker and dep.get("dependency_type") == "discovered-from":
                has_edge = True
                break
        if has_edge:
            return
        out.append({
            "type": "provenance_mismatch",
            "confidence": "HIGH",
            "dependent": dependent,
            "blocker": blocker,
            "dep_type": "discovered-from",
            "source_label": source_label,
            "source_side": source_side,
            "rationale": (
                f"Provenance label '{source_label}' on {source_side}-side "
                f"({blocker if source_side == 'X' else dependent}) implies "
                f"edge {dependent} --discovered-from--> {blocker}, but no "
                "such edge exists."
            ),
        })

    # X-side pass: produced-bead-Y on bead X.
    for x_id, x in beads_by_id.items():
        for label in x.get("labels", []) or []:
            if not isinstance(label, str) or not label.startswith("produced-bead-"):
                continue
            y_suffix = label[len("produced-bead-"):]
            y_id = _resolve_id(y_suffix, beads_by_id)
            if not y_id:
                continue
            _emit(dependent=y_id, blocker=x_id, source_label=label, source_side="X")

    # Y-side pass: produced-from-X on bead Y.
    for y_id, y in beads_by_id.items():
        for label in y.get("labels", []) or []:
            if not isinstance(label, str) or not label.startswith("produced-from-"):
                continue
            x_suffix = label[len("produced-from-"):]
            x_id = _resolve_id(x_suffix, beads_by_id)
            if not x_id:
                continue
            _emit(dependent=y_id, blocker=x_id, source_label=label, source_side="Y")

    return out


def find_semantic_type_conflicts(beads_by_id):
    """blocks edges between parent-child pairs; bidirectional discovered-from."""
    out = []
    for bid, b in beads_by_id.items():
        parent = b.get("parent") or ""
        for dep in b.get("dependencies", []) or []:
            if not isinstance(dep, dict):
                continue
            dep_id = dep.get("id")
            dep_type = dep.get("dependency_type")
            if not dep_id or not dep_type:
                continue
            # blocks between parent-child.
            if dep_type == "blocks":
                if parent and dep_id == parent:
                    out.append({
                        "type": "semantic_type_conflict",
                        "subtype": "blocks_on_parent",
                        "confidence": "HIGH",
                        "dependent": bid,
                        "blocker": dep_id,
                        "rationale": (
                            f"{bid} declares blocks edge on its parent {dep_id}; "
                            "parent-child relationship should not be 'blocks'."
                        ),
                    })
                # child blocks check via reverse: if dep_id's parent is bid
                other = beads_by_id.get(dep_id)
                if other and other.get("parent") == bid:
                    out.append({
                        "type": "semantic_type_conflict",
                        "subtype": "blocks_on_child",
                        "confidence": "HIGH",
                        "dependent": bid,
                        "blocker": dep_id,
                        "rationale": (
                            f"{bid} declares blocks edge on its child {dep_id}; "
                            "parent-child relationship should not be 'blocks'."
                        ),
                    })
            # Bidirectional discovered-from: only emit when bid < dep_id so
            # each symmetric pair is reported exactly once without a dedup pass.
            if dep_type == "discovered-from" and bid < dep_id:
                other = beads_by_id.get(dep_id)
                if not other:
                    continue
                for od in other.get("dependencies", []) or []:
                    if isinstance(od, dict) \
                       and od.get("id") == bid \
                       and od.get("dependency_type") == "discovered-from":
                        out.append({
                            "type": "semantic_type_conflict",
                            "subtype": "bidirectional_discovered_from",
                            "confidence": "HIGH",
                            "dependent": bid,
                            "blocker": dep_id,
                            "rationale": (
                                f"{bid} and {dep_id} both declare discovered-from "
                                "edges on each other; provenance must be acyclic."
                            ),
                        })
                        break
    return out


def find_stale_blockers(beads_by_id, closed_ids):
    """Open bead whose every `blocks`-type incoming blocker is closed."""
    out = []
    for bid, b in beads_by_id.items():
        if b.get("status") == "closed":
            continue
        # `dependencies` on b are the blockers OF b (b is dependent).
        blocks_deps = [d for d in (b.get("dependencies") or [])
                       if isinstance(d, dict) and d.get("dependency_type") == "blocks"]
        if not blocks_deps:
            continue
        all_closed = all(d.get("id") in closed_ids for d in blocks_deps)
        if all_closed:
            out.append({
                "type": "stale_blocker",
                "confidence": "HIGH",
                "dependent": bid,
                "blocker_ids": [d.get("id") for d in blocks_deps],
                "rationale": (
                    f"All blocks-type blockers of {bid} are closed; "
                    "the bead may be ready or its dep edges are stale."
                ),
            })
    return out


def _cycle_touches(cycle, selected_ids):
    """Return True iff any id in `cycle` is in `selected_ids`. Cycles can be
    lists of ids, lists of dicts with `id`/`bead_id` keys, or dicts containing
    a `nodes`/`ids` list — handle all observed shapes defensively.

    Empty-set semantics: `selected_ids is None` means "no filter — show all
    cycles" (all-mode); an explicit empty set means "filter everything out"
    (focused mode with no resolved neighborhood)."""
    if selected_ids is None:
        return True
    if not selected_ids:
        return False
    candidates = []
    if isinstance(cycle, list):
        for item in cycle:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                for k in ("id", "bead_id", "node"):
                    v = item.get(k)
                    if isinstance(v, str):
                        candidates.append(v)
    elif isinstance(cycle, dict):
        for k in ("nodes", "ids", "cycle"):
            v = cycle.get(k)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        candidates.append(item)
                    elif isinstance(item, dict):
                        cid = item.get("id") or item.get("bead_id")
                        if isinstance(cid, str):
                            candidates.append(cid)
    return any(c in selected_ids for c in candidates)


def find_cycles(selected_ids=None):
    """Run `bd dep cycles --json`. Always returns ALL cycles in the dep
    graph. In focused mode, each cycle is annotated `in_focused_scope`
    according to whether it touches `selected_ids`; we deliberately do NOT
    filter them out — cycles between the parent chain and beads outside
    the focused neighborhood are still material to the user. `selected_ids
    is None` (all-mode) omits the annotation."""
    rc, out, _err = bd_text("dep", "cycles", "--json")
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        # Fall back to plain text — no cycle structure to annotate.
        rc2, out2, _ = bd_text("dep", "cycles")
        if rc2 == 0 and out2.strip():
            return [{
                "type": "cycle",
                "confidence": "HIGH",
                "raw": out2.strip()[:2000],
                "rationale": "bd dep cycles reported a cycle in the dep graph.",
            }]
        return []
    if not data:
        return []

    def _wrap(c):
        item = {
            "type": "cycle",
            "confidence": "HIGH",
            "cycle": c,
            "rationale": "bd dep cycles reported a cycle in the dep graph.",
        }
        if selected_ids is not None:
            item["in_focused_scope"] = _cycle_touches(c, selected_ids)
        return item

    if not isinstance(data, list):
        # Non-list scalar (dict, string, etc.) — wrap into a single cycle item.
        if isinstance(data, dict):
            return [_wrap(data)]
        return []
    return [_wrap(c) for c in data]


# ---------------------------------------------------------------------------
# Focused-mode neighborhood
# ---------------------------------------------------------------------------

def focused_neighborhood(target_id, beads_by_id):
    """Target + 1-hop neighborhood (NEIGHBORHOOD_TYPES) + full parent chain +
    full child chain. Capped at FOCUSED_BEAD_CAP. Parent chain is guaranteed
    to survive the cap — neighborhood entries are dropped first.

    Returns a deterministically ordered list of bead ids:
      1. Parent chain in traversal order (root first → ... → target's immediate parent)
      2. The target bead
      3. Remaining 1-hop neighbors and descendants, sorted by id

    An OrderedDict (used as an ordered set) tracks membership while
    preserving insertion order; the final remaining-neighbor block is
    sorted by id so repeated runs produce identical output."""
    # parent_chain_ids: list, ordered root → target's immediate parent.
    parent_chain_ids = []
    # selected: OrderedDict acts as an ordered set; insertion order is
    # meaningful only for membership-tracking. Final ordering is rebuilt
    # below from (parent_chain, target, sorted-remaining).
    selected = OrderedDict()
    selected[target_id] = None

    target = beads_by_id.get(target_id)
    if not target:
        return [target_id], False

    # 1-hop via dependencies/dependents on the target.
    for dep in target.get("dependencies", []) or []:
        if isinstance(dep, dict) and dep.get("dependency_type") in NEIGHBORHOOD_TYPES:
            dep_id = dep.get("id")
            if dep_id:
                selected.setdefault(dep_id, None)
    for dep in target.get("dependents", []) or []:
        if isinstance(dep, dict) and dep.get("dependency_type") in NEIGHBORHOOD_TYPES:
            dep_id = dep.get("id")
            if dep_id:
                selected.setdefault(dep_id, None)

    # Parent chain (walk up). Collected as a list so the cap can preserve
    # the chain in root-first traversal order.
    cur = target.get("parent") or ""
    walk_seen = {target_id}
    parents_upward = []  # immediate parent first → root last
    while cur and cur not in walk_seen:
        walk_seen.add(cur)
        parents_upward.append(cur)
        selected.setdefault(cur, None)
        nxt_bead = beads_by_id.get(cur)
        if not nxt_bead:
            # Fetch parent on-demand so chain is complete even for closed parents.
            nxt_bead = fetch_bead_detail(cur)
            if nxt_bead:
                beads_by_id[cur] = nxt_bead
        cur = (nxt_bead or {}).get("parent") or ""
    # Reverse so order is root → target's immediate parent.
    parent_chain_ids = list(reversed(parents_upward))

    # Child chain (walk down via beads whose parent==target, recursively).
    # Iterate children in sorted order at each level so traversal itself
    # is deterministic, even though final ordering is re-sorted below.
    def walk_down(parent_id, depth=0):
        if depth > MAX_CHILD_DEPTH:
            return
        children = sorted(
            cid for cid, c in beads_by_id.items()
            if c.get("parent") == parent_id and cid not in selected
        )
        for cid in children:
            selected[cid] = None
            walk_down(cid, depth + 1)

    walk_down(target_id)

    parent_chain_set = set(parent_chain_ids)
    capped = False
    if len(selected) > FOCUSED_BEAD_CAP:
        # Preserve parent chain first, then fill the remaining cap with the
        # rest of the neighborhood sorted by id so cap-truncation is
        # deterministic.
        remaining_sorted = sorted(
            s for s in selected
            if s != target_id and s not in parent_chain_set
        )
        ordered = parent_chain_ids + [target_id] + remaining_sorted
        ordered = ordered[:FOCUSED_BEAD_CAP]
        capped = True
    else:
        remaining_sorted = sorted(
            s for s in selected
            if s != target_id and s not in parent_chain_set
        )
        ordered = parent_chain_ids + [target_id] + remaining_sorted

    return ordered, capped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Collect bead inventory + dep-graph findings for dep-health-check."
    )
    parser.add_argument("--mode", required=True, choices=["all", "focused"])
    parser.add_argument("--target", default=None,
                        help="Required when --mode focused.")
    args = parser.parse_args()

    # Argparse-level argcheck.
    if args.mode == "focused" and not args.target:
        print("error: --target is required when --mode focused", file=sys.stderr)
        sys.exit(2)

    # Exit 3: bd missing.
    if shutil.which("bd") is None:
        print("error: bd not found on PATH", file=sys.stderr)
        sys.exit(3)

    # Exit 4: db not reachable.
    if not db_reachable():
        print("error: bd database not found (no .beads/ in this or any parent directory)",
              file=sys.stderr)
        sys.exit(4)

    # Bulk inventory (note --limit 0 to defeat the 50-row default).
    try:
        open_beads = bd_json("list", "--status", "open", "--json", "--limit", "0")
        in_progress = bd_json("list", "--status", "in_progress", "--json", "--limit", "0")
        closed_meta = bd_json("list", "--status", "closed", "--json", "--limit", "0",
                              allow_fail=True)
    except BdMissing:
        print("error: bd not found on PATH", file=sys.stderr)
        sys.exit(3)
    except DbMissing as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(4)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    # Build closed-id set for stale-blocker detection.
    closed_ids = set(b.get("id") for b in closed_meta if b.get("id"))

    # Bulk inventory keyed by id, retaining labels (labels are only on bulk
    # output, not on `bd show`).
    bulk_by_id = {}
    for b in (open_beads + in_progress):
        bid = b.get("id")
        if not bid:
            continue
        bulk_by_id[bid] = b

    if args.mode == "focused":
        # bd show resolves any status, including closed — needed for focused audits.
        target_detail = fetch_bead_detail(args.target)
        if not target_detail:
            print(f"error: target bead '{args.target}' not found",
                  file=sys.stderr)
            sys.exit(2)
        if args.target not in bulk_by_id:
            bulk_by_id[args.target] = target_detail

    # Decide candidate set.
    candidate_ids = list(bulk_by_id.keys())

    # Fetch per-bead detail for every candidate. Merge labels from bulk into
    # the detailed view (labels are not part of `bd show`).
    detailed_by_id = {}
    for bid in candidate_ids:
        d = fetch_bead_detail(bid)
        if d is None:
            d = dict(bulk_by_id[bid])
            d.setdefault("description", "")
            d.setdefault("notes", "")
            d.setdefault("parent", "")
            d.setdefault("dependencies", [])
            d.setdefault("dependents", [])
            d.setdefault("comments", [])
        # Labels are only on bulk output, not on `bd show` — merge them in.
        bulk_rec = bulk_by_id.get(bid, {})
        if not d.get("labels"):
            d["labels"] = bulk_rec.get("labels", []) or []
        if not d.get("status"):
            d["status"] = bulk_rec.get("status", "")
        detailed_by_id[bid] = d

    # Focused-mode neighborhood selection.
    capped = False
    cycle_filter_ids = None
    if args.mode == "focused":
        selected_ids, capped = focused_neighborhood(args.target, detailed_by_id)
        # Some selected neighbors may not be in detailed_by_id yet — e.g. a
        # closed blocker that didn't appear in the open/in_progress bulk
        # inventory. Fetch them on-demand so the focused-mode result is
        # complete.
        for sid in selected_ids:
            if sid not in detailed_by_id:
                fetched = fetch_bead_detail(sid)
                if fetched is not None:
                    detailed_by_id[sid] = fetched
        detailed_by_id = {bid: detailed_by_id[bid]
                          for bid in selected_ids if bid in detailed_by_id}
        cycle_filter_ids = set(selected_ids)

    # Token guard: cap total content; truncate per-bead until total is under
    # the cap. First pass uses PER_BEAD_TRUNCATE_LEN; if the total is still
    # over the cap (e.g. many beads near the per-bead limit, or large comment
    # bodies summing past the cap), a second pass applies an aggressive
    # cap // bead_count per-bead limit so total <= TOTAL_CONTENT_CAP is
    # actually guaranteed. `>=` ensures exact-limit beads are still trimmed
    # when the second pass demands a smaller limit.
    truncated_ids = set()
    total = sum(content_chars(b) for b in detailed_by_id.values())
    if total > TOTAL_CONTENT_CAP:
        # First pass: per-bead PER_BEAD_TRUNCATE_LEN.
        for bid, b in detailed_by_id.items():
            if content_chars(b) >= PER_BEAD_TRUNCATE_LEN:
                if truncate_bead_content(b):
                    truncated_ids.add(bid)
        total = sum(content_chars(b) for b in detailed_by_id.values())

        # Second pass: aggressive cap // num_beads when still over.
        if total > TOTAL_CONTENT_CAP and detailed_by_id:
            aggressive_limit = max(256, TOTAL_CONTENT_CAP // len(detailed_by_id))
            aggressive_comment_limit = max(128, aggressive_limit // 4)
            for bid, b in detailed_by_id.items():
                if content_chars(b) >= aggressive_limit:
                    if truncate_bead_content(b, limit=aggressive_limit,
                                             comment_limit=aggressive_comment_limit):
                        truncated_ids.add(bid)
    truncated_count = len(truncated_ids)

    beads_list = list(detailed_by_id.values())
    prefix = detect_prefix(beads_list) or detect_prefix(open_beads + in_progress)

    # Deterministic findings.
    findings = []
    findings.extend(find_provenance_mismatches(detailed_by_id))
    findings.extend(find_semantic_type_conflicts(detailed_by_id))
    findings.extend(find_stale_blockers(detailed_by_id, closed_ids))
    findings.extend(find_cycles(selected_ids=cycle_filter_ids))

    output = {
        "project_prefix": prefix,
        "mode": args.mode,
        "target": args.target,
        "bead_count": len(beads_list),
        "truncated_count": truncated_count,
        "capped": capped,
        "beads": beads_list,
        "findings": findings,
    }

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
