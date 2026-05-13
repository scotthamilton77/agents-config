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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOTAL_CONTENT_CAP = 600_000          # chars; total content across all beads
PER_BEAD_TRUNCATE_LEN = 4000         # chars; truncate per-bead content when cap hit
FOCUSED_BEAD_CAP = 200               # focused-mode neighborhood cap

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
        # bd disappeared mid-run — treat as missing.
        raise RuntimeError("bd_missing")
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
            raise RuntimeError("db_missing:" + stderr[:200])
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
    # Normalize sparse fields.
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
    # Comments may be list of dicts.
    for c in bead.get("comments", []) or []:
        if isinstance(c, dict):
            parts.append(c.get("body", "") or c.get("text", "") or "")
        else:
            parts.append(str(c))
    return sum(len(p) for p in parts)


def truncate_bead_content(bead, limit=PER_BEAD_TRUNCATE_LEN):
    for k in ("description", "notes", "design", "acceptance_criteria"):
        v = bead.get(k, "") or ""
        if len(v) > limit:
            bead[k] = v[:limit] + "\n…[truncated]"
    bead["truncated"] = True


# ---------------------------------------------------------------------------
# Deterministic findings
# ---------------------------------------------------------------------------

def find_provenance_mismatches(beads_by_id):
    """A `produced-bead-Y` label on bead X expects a dep edge:
    `bd dep add Y X --type discovered-from`. Missing edge → finding."""
    out = []
    for x_id, x in beads_by_id.items():
        for label in x.get("labels", []) or []:
            if not isinstance(label, str):
                continue
            if not label.startswith("produced-bead-"):
                continue
            y_id_suffix = label[len("produced-bead-"):]
            if not y_id_suffix:
                continue
            # Try exact match first, then suffix match against known ids.
            y_id = None
            if y_id_suffix in beads_by_id:
                y_id = y_id_suffix
            else:
                for candidate in beads_by_id:
                    if candidate.endswith("-" + y_id_suffix):
                        y_id = candidate
                        break
            if not y_id:
                continue
            y = beads_by_id[y_id]
            # Expected edge: Y depends-on X with type discovered-from.
            has_edge = False
            for dep in y.get("dependencies", []) or []:
                if not isinstance(dep, dict):
                    continue
                if dep.get("id") == x_id and dep.get("dependency_type") == "discovered-from":
                    has_edge = True
                    break
            if not has_edge:
                out.append({
                    "type": "provenance_mismatch",
                    "confidence": "HIGH",
                    "dependent": y_id,
                    "blocker": x_id,
                    "dep_type": "discovered-from",
                    "rationale": (
                        f"Bead {x_id} carries label '{label}' but {y_id} "
                        f"has no incoming discovered-from edge from {x_id}."
                    ),
                })
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
            # Bidirectional discovered-from.
            if dep_type == "discovered-from":
                other = beads_by_id.get(dep_id)
                if not other:
                    continue
                for od in other.get("dependencies", []) or []:
                    if isinstance(od, dict) \
                       and od.get("id") == bid \
                       and od.get("dependency_type") == "discovered-from":
                        # Emit once (smaller id first).
                        a, c = sorted([bid, dep_id])
                        out.append({
                            "type": "semantic_type_conflict",
                            "subtype": "bidirectional_discovered_from",
                            "confidence": "HIGH",
                            "dependent": a,
                            "blocker": c,
                            "rationale": (
                                f"{a} and {c} both declare discovered-from "
                                "edges on each other; provenance must be acyclic."
                            ),
                        })
                        break
    # De-dup
    seen = set()
    unique = []
    for f in out:
        key = (f["type"], f.get("subtype"), f.get("dependent"), f.get("blocker"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


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


def find_cycles():
    rc, out, _err = bd_text("dep", "cycles", "--json")
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        # Fall back to plain text.
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
    if isinstance(data, list):
        return [{
            "type": "cycle",
            "confidence": "HIGH",
            "cycle": c,
            "rationale": "bd dep cycles reported a cycle in the dep graph.",
        } for c in data]
    return [{
        "type": "cycle",
        "confidence": "HIGH",
        "cycle": data,
        "rationale": "bd dep cycles reported a cycle in the dep graph.",
    }]


# ---------------------------------------------------------------------------
# Focused-mode neighborhood
# ---------------------------------------------------------------------------

def focused_neighborhood(target_id, beads_by_id):
    """Target + 1-hop neighborhood (NEIGHBORHOOD_TYPES) + full parent chain +
    full child chain. Capped at FOCUSED_BEAD_CAP."""
    selected = {target_id}
    target = beads_by_id.get(target_id)
    if not target:
        return list(selected), False

    # 1-hop via dependencies/dependents on the target.
    for dep in target.get("dependencies", []) or []:
        if isinstance(dep, dict) and dep.get("dependency_type") in NEIGHBORHOOD_TYPES:
            dep_id = dep.get("id")
            if dep_id:
                selected.add(dep_id)
    for dep in target.get("dependents", []) or []:
        if isinstance(dep, dict) and dep.get("dependency_type") in NEIGHBORHOOD_TYPES:
            dep_id = dep.get("id")
            if dep_id:
                selected.add(dep_id)

    # Parent chain (walk up).
    cur = target.get("parent") or ""
    seen = {target_id}
    while cur and cur not in seen:
        seen.add(cur)
        selected.add(cur)
        nxt_bead = beads_by_id.get(cur)
        if not nxt_bead:
            # Fetch parent on-demand so chain is complete even for closed parents.
            nxt_bead = fetch_bead_detail(cur)
            if nxt_bead:
                beads_by_id[cur] = nxt_bead
        cur = (nxt_bead or {}).get("parent") or ""

    # Child chain (walk down via beads whose parent==target, recursively).
    def walk_down(parent_id, depth=0):
        if depth > 50:
            return
        for cid, c in list(beads_by_id.items()):
            if c.get("parent") == parent_id and cid not in selected:
                selected.add(cid)
                walk_down(cid, depth + 1)

    walk_down(target_id)

    capped = False
    if len(selected) > FOCUSED_BEAD_CAP:
        # Keep target + parent chain + first (FOCUSED_BEAD_CAP - chain) others.
        ordered = [target_id] + [s for s in selected if s != target_id]
        selected = set(ordered[:FOCUSED_BEAD_CAP])
        capped = True

    return list(selected), capped


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
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith("db_missing"):
            print(f"error: {msg}", file=sys.stderr)
            sys.exit(4)
        if msg == "bd_missing":
            print("error: bd not found on PATH", file=sys.stderr)
            sys.exit(3)
        print(f"error: {msg}", file=sys.stderr)
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

    # Focused-mode: validate target exists.
    if args.mode == "focused":
        # Try bd show directly — works for any status.
        target_detail = fetch_bead_detail(args.target)
        if not target_detail:
            print(f"error: target bead '{args.target}' not found",
                  file=sys.stderr)
            sys.exit(2)
        # Ensure target is in bulk_by_id (may be closed, etc.).
        if args.target not in bulk_by_id:
            # Use the show payload; labels come from there too if present.
            bulk_by_id[args.target] = target_detail

    # Decide candidate set.
    candidate_ids = list(bulk_by_id.keys())

    # Fetch per-bead detail for every candidate. Merge labels from bulk into
    # the detailed view (labels are not part of `bd show`).
    detailed_by_id = {}
    for bid in candidate_ids:
        d = fetch_bead_detail(bid)
        if d is None:
            # Fall back to bulk record.
            d = dict(bulk_by_id[bid])
            d.setdefault("description", "")
            d.setdefault("notes", "")
            d.setdefault("parent", "")
            d.setdefault("dependencies", [])
            d.setdefault("dependents", [])
            d.setdefault("comments", [])
        # Merge labels from bulk.
        bulk_rec = bulk_by_id.get(bid, {})
        if not d.get("labels"):
            d["labels"] = bulk_rec.get("labels", []) or []
        # Ensure status is present.
        if not d.get("status"):
            d["status"] = bulk_rec.get("status", "")
        detailed_by_id[bid] = d

    # Focused-mode neighborhood selection.
    capped = False
    if args.mode == "focused":
        selected_ids, capped = focused_neighborhood(args.target, detailed_by_id)
        detailed_by_id = {bid: detailed_by_id[bid]
                          for bid in selected_ids if bid in detailed_by_id}

    # Token guard: cap total content; truncate per-bead when over.
    total = sum(content_chars(b) for b in detailed_by_id.values())
    truncated_count = 0
    if total > TOTAL_CONTENT_CAP:
        for b in detailed_by_id.values():
            if content_chars(b) > PER_BEAD_TRUNCATE_LEN:
                truncate_bead_content(b)
                truncated_count += 1

    beads_list = list(detailed_by_id.values())
    prefix = detect_prefix(beads_list) or detect_prefix(open_beads + in_progress)

    # Deterministic findings.
    findings = []
    findings.extend(find_provenance_mismatches(detailed_by_id))
    findings.extend(find_semantic_type_conflicts(detailed_by_id))
    findings.extend(find_stale_blockers(detailed_by_id, closed_ids))
    findings.extend(find_cycles())

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
