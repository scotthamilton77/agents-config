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
import locale as _locale_mod
import os
import shutil
import subprocess
import sys
import time
from collections import Counter, OrderedDict
from datetime import datetime


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

try:
    _locale_mod.setlocale(_locale_mod.LC_TIME, "")
except _locale_mod.Error:
    pass  # fall back to C locale formatting


def format_ts(ts_str):
    """Convert an ISO 8601 timestamp to local-timezone locale-formatted string.

    Returns the bare date (first 10 chars) on parse failure so the field is
    never empty when the raw value is non-empty."""
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%x %H:%M %Z").strip()
    except (ValueError, OSError):
        return ts_str[:10]


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


def find_stale_blockers(beads_by_id, closed_ids, known_ids=None):
    """Open (or in_progress) bead whose every live `blocks`-type blocker is
    closed.

    Ghost references (deps pointing at IDs that exist in no status — open,
    in_progress, or closed) are stripped before the all-closed evaluation
    when `known_ids` is provided. Without this filter, a bead with
    `[real-closed-blocker, ghost-blocker]` would slip past detection
    because the ghost id is not in `closed_ids`, making `all_closed` False
    and masking a legitimate finding. A bead whose blockers are *all*
    ghosts is skipped (no meaningful blocker state to report)."""
    out = []
    for bid, b in beads_by_id.items():
        if b.get("status") == "closed":
            continue
        # `dependencies` on b are the blockers OF b (b is dependent).
        blocks_deps = [d for d in (b.get("dependencies") or [])
                       if isinstance(d, dict) and d.get("dependency_type") == "blocks"]
        if not blocks_deps:
            continue
        # Strip ghost references when a known-id universe is supplied.
        if known_ids is not None:
            blocks_deps = [d for d in blocks_deps if d.get("id") in known_ids]
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


ORPHAN_WALK_MAX_DEPTH = 10  # parent-chain hop cap; project chains are <10 in practice


def _is_mol_or_wisp(bid):
    """True iff bead ID indicates a mol/wisp step-bead (substring match on
    `-mol-` or `-wisp-`). Conservative: matches both step-beads and their
    parent molecule/wisp containers, which is the intent — we want to
    surface orphans regardless of which layer of the workflow they sit in."""
    if not bid or not isinstance(bid, str):
        return False
    return ("-mol-" in bid) or ("-wisp-" in bid)


def _find_for_bead_label(labels):
    """Return the bead-ID reference from the first `for-bead-<id>` label,
    or None when no such label is present."""
    for label in labels or []:
        if isinstance(label, str) and label.startswith("for-bead-"):
            return label[len("for-bead-"):]
    return None


def _orphan_full_bead(bid, beads_by_id, lazy_cache):
    """Return the full bead record for `bid`. Reads the in-process snapshot
    first, falls back to lazy `bd show` for closed beads, caches results
    per run. Returns None for ghost beads (not in any status). Cache
    sentinel ``False`` marks a previously-failed lookup so repeated walks
    do not re-spawn the shell-out."""
    if bid in beads_by_id:
        return beads_by_id[bid]
    cached = lazy_cache.get(bid)
    if cached is False:
        return None
    if cached is not None:
        return cached
    fetched = fetch_bead_detail(bid)
    if fetched is None:
        lazy_cache[bid] = False
        return None
    lazy_cache[bid] = fetched
    return fetched


def _summarize_bead(bid, bead):
    """Reduce a full bead record to the orphan-finding forensic summary
    (id, title, status, updated_at). Returns None when `bead` is None so
    callers can propagate the ghost signal cleanly."""
    if bead is None:
        return None
    return {
        "id": bead.get("id") or bid,
        "title": bead.get("title", "") or "",
        "status": bead.get("status", "") or "",
        "updated_at": format_ts(bead.get("updated_at", "") or ""),
    }


def find_orphan_step_beads(beads_by_id, known_ids, closed_ids,
                           max_depth=ORPHAN_WALK_MAX_DEPTH):
    """Open mol/wisp step-beads whose parent chain contains any closed
    ancestor — i.e. workflow artifacts left behind when the molecule that
    spawned them closed (or partially closed) mid-flight.

    Walk strategy (per candidate step-bead):
      - Starting from the step's `parent`, hop up to `max_depth` ancestors.
      - At each hop, capture a forensic summary (id, title, status,
        updated_at) and record whether the ancestor is closed.
      - The closest ancestor carrying a `for-bead-<X>` label identifies
        the molecule container; X identifies the source bead.
      - Stop on: ghost parent (id not in `known_ids`), `bd show` miss,
        cycle, depth cap, or root (no further parent).

    Classification (collect.py-emitted `classification` field):
      - ``live-work``: source bead is `in_progress` — work is still active;
        the step is most likely live, not orphaned.
      - ``safe-cleanup``: step is open/in_progress, every walked ancestor
        is closed, AND the source bead is closed. Safe to close manually.
      - ``untraceable``: no `for-bead-<X>` label resolvable anywhere in
        the chain (or the labelled source is a ghost). Manual triage
        required — no provenance trail.
      - ``needs-review``: anything else (mixed-state ancestor chain, source
        still open, etc.). Human (or interactive LLM) reads the forensic
        block to decide.

    Beads with zero closed ancestors are excluded — they are healthy
    in-flight workflow artifacts, not orphan candidates."""
    out = []
    lazy_cache = {}

    for bid, b in beads_by_id.items():
        if b.get("status") == "closed":
            continue
        if not _is_mol_or_wisp(bid):
            continue

        # Inlined (vs _summarize_bead) so the type-checker sees a concrete
        # dict rather than Optional[dict] — `b` is guaranteed non-None here
        # because it comes from beads_by_id.items() iteration.
        step_summary = {
            "id": b.get("id") or bid,
            "title": b.get("title", "") or "",
            "status": b.get("status", "") or "",
            "updated_at": format_ts(b.get("updated_at", "") or ""),
        }

        any_closed_ancestor = False
        ghost_encountered = False
        ancestor_statuses = []
        parent_mol_id = None
        source_label_ref = None
        walked_summaries = []

        cur_parent_id = b.get("parent") or ""
        depth = 0
        seen_in_walk = {bid}

        while cur_parent_id and depth < max_depth:
            if cur_parent_id in seen_in_walk:
                # Cycle guard — stop the walk rather than loop.
                break
            seen_in_walk.add(cur_parent_id)
            depth += 1

            if cur_parent_id not in known_ids:
                ghost_encountered = True
                walked_summaries.append({
                    "id": cur_parent_id,
                    "title": "",
                    "status": "ghost",
                    "updated_at": "",
                })
                break

            parent_bead = _orphan_full_bead(cur_parent_id, beads_by_id, lazy_cache)
            if parent_bead is None:
                # known_ids hit but bd show miss — treat as ghost defensively.
                ghost_encountered = True
                walked_summaries.append({
                    "id": cur_parent_id,
                    "title": "",
                    "status": "ghost",
                    "updated_at": "",
                })
                break

            summary = _summarize_bead(cur_parent_id, parent_bead)
            walked_summaries.append(summary)
            ancestor_statuses.append(summary["status"])
            if summary["status"] == "closed":
                any_closed_ancestor = True

            # First `for-bead-<X>` label wins — closest molecule container.
            if source_label_ref is None:
                ref = _find_for_bead_label(parent_bead.get("labels"))
                if ref:
                    source_label_ref = ref
                    parent_mol_id = cur_parent_id

            cur_parent_id = parent_bead.get("parent") or ""

        # Orphan criterion: at least one closed ancestor in chain.
        if not any_closed_ancestor:
            continue

        # Parent-molecule container summary: prefer the for-bead-bearing
        # ancestor; fall back to the immediate parent when no for-bead
        # label was found.
        parent_mol_summary = None
        if parent_mol_id is not None:
            for w in walked_summaries:
                if w["id"] == parent_mol_id:
                    parent_mol_summary = w
                    break
        elif walked_summaries:
            parent_mol_summary = walked_summaries[0]

        # Resolve source bead from the for-bead label, if found.
        source_summary = None
        if source_label_ref:
            resolved_id = source_label_ref
            if resolved_id not in known_ids:
                # Try suffix resolution against the in-process snapshot.
                resolved_id = _resolve_id(source_label_ref, beads_by_id) or source_label_ref
            source_bead = _orphan_full_bead(resolved_id, beads_by_id, lazy_cache)
            source_summary = _summarize_bead(resolved_id, source_bead)

        if source_summary is None:
            classification = "untraceable"
        elif source_summary.get("status") == "in_progress":
            classification = "live-work"
        elif (step_summary.get("status") in ("open", "in_progress")
              and all(s == "closed" for s in ancestor_statuses)
              and source_summary.get("status") == "closed"):
            classification = "safe-cleanup"
        else:
            classification = "needs-review"

        out.append({
            "type": "orphan_step_bead",
            "confidence": "HIGH",
            "classification": classification,
            "step": step_summary,
            "parent_mol": parent_mol_summary,
            "source_bead": source_summary,
            "ghost_encountered": ghost_encountered,
            "walk_depth": depth,
            "rationale": (
                f"Open mol/wisp step-bead {bid} has a closed ancestor in its "
                "parent chain; classified by source-bead status."
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
    full child chain. Capped at FOCUSED_BEAD_CAP.

    Returns a deterministically ordered list of bead ids:
      1. Parent chain in walk order (root first → ... → target's immediate parent)
      2. The target bead
      3. Remaining 1-hop neighbors and descendants, sorted by id

    Cap precedence when ``len(selected) > FOCUSED_BEAD_CAP``:
      - The **target** is guaranteed to survive (it is placed at the head
        and the parent chain is truncated around it if necessary).
      - The parent chain is preserved next, in walk order, truncated from
        the ROOT end first so the closest ancestors remain alongside the
        target.
      - Remaining neighborhood entries (sorted by id) fill any leftover
        slots.

    The pathological case ``len(parent_chain_ids) + 1 > FOCUSED_BEAD_CAP``
    is uncommon in practice (project parent chains are <10 deep) but is
    handled explicitly rather than relying on slice semantics: dropping
    the target would silently break every downstream consumer that pivots
    on the target id.

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
    remaining_sorted = sorted(
        s for s in selected
        if s != target_id and s not in parent_chain_set
    )
    if len(selected) > FOCUSED_BEAD_CAP:
        capped = True
        # Target is non-negotiable — it anchors the focused view. Allocate
        # the remaining (cap - 1) slots to as much of the parent chain as
        # fits (truncating from the ROOT end so the closest ancestors
        # stay), then fill any leftover with sorted neighborhood entries.
        budget = FOCUSED_BEAD_CAP - 1
        if len(parent_chain_ids) >= budget:
            # Pathological: chain alone fills (or overflows) the cap.
            # Keep the closest `budget` ancestors (tail of walk order).
            kept_chain = parent_chain_ids[-budget:] if budget > 0 else []
            ordered = kept_chain + [target_id]
        else:
            slots_left = budget - len(parent_chain_ids)
            ordered = parent_chain_ids + [target_id] + remaining_sorted[:slots_left]
    else:
        ordered = parent_chain_ids + [target_id] + remaining_sorted

    return ordered, capped


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _format_deps_text(deps):
    """Compact one-line dep list for beads.txt: 'id (type), id (type)'."""
    if not deps:
        return "(none)"
    parts = []
    for d in deps:
        if not isinstance(d, dict):
            continue
        dep_id = d.get("id", "")
        dep_type = d.get("dependency_type", "?")
        if dep_id:
            parts.append(f"{dep_id} ({dep_type})")
    return ", ".join(parts) if parts else "(none)"


def write_beads_file(detailed_by_id, path):
    """Write a flat human-readable bead inventory to *path*.

    One block per bead, separated by ``---``. Mol/wisp workflow artifacts
    are excluded. Each block starts with a ``===`` header line that packs
    the key identifying fields, making the file grep-friendly while also
    being LLM-scannable as a continuous document.

    Description and notes are capped and newlines collapsed to spaces so
    every field is a single line (preserves block structure). Acceptance
    criteria and comments are omitted — too verbose for semantic-link
    analysis and the LLM subagent does not need them.

    Sorted by bead id for deterministic output across runs."""
    DESC_CAP = 500
    NOTES_CAP = 200

    with open(path, "w", encoding="utf-8") as fh:
        for bid in sorted(detailed_by_id):
            b = detailed_by_id[bid]
            if _is_mol_or_wisp(bid):
                continue

            issue_type = b.get("issue_type", "") or ""
            priority = b.get("priority", "")
            priority_str = f"P{priority}" if priority != "" else "P?"
            status = b.get("status", "") or ""
            updated = format_ts(b.get("updated_at", "") or "")

            fh.write(f"=== {bid} | {issue_type} | {priority_str}"
                     f" | {status} | updated:{updated} ===\n")
            fh.write(f"Title: {b.get('title', '') or ''}\n")

            labels = b.get("labels") or []
            fh.write(f"Labels: {labels}\n")

            parent = b.get("parent", "") or ""
            if parent:
                fh.write(f"Parent: {parent}\n")

            fh.write(f"Deps: {_format_deps_text(b.get('dependencies') or [])}\n")

            desc = " ".join((b.get("description", "") or "").split()).strip()
            if desc:
                if len(desc) > DESC_CAP:
                    desc = desc[:DESC_CAP] + "…"
                fh.write(f"Desc: {desc}\n")

            notes = " ".join((b.get("notes", "") or "").split()).strip()
            if notes:
                if len(notes) > NOTES_CAP:
                    notes = notes[:NOTES_CAP] + "…"
                fh.write(f"Notes: {notes}\n")

            fh.write("---\n")


def write_findings_file(prefix, mode, target, bead_count, open_bead_count,
                        truncated_count, capped, findings, path):
    """Write structured findings JSON to *path*.

    Contains all findings plus run metadata. The ``beads`` array is NOT
    included here — bead content lives in the companion beads.txt file."""
    finding_counts = dict(Counter(f.get("type", "unknown") for f in findings))
    payload = {
        "project_prefix": prefix,
        "mode": mode,
        "target": target,
        "bead_count": bead_count,
        "open_bead_count": open_bead_count,
        "truncated_count": truncated_count,
        "capped": capped,
        "finding_counts": finding_counts,
        "findings": findings,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


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

    # Known-ID set: any bead that exists in any status (open, in_progress,
    # or closed). Ghost references — dep targets or parents to deleted /
    # non-existent beads — are absent from this set. Consumed by the
    # stale-blocker filter (to strip ghost blockers before all-closed
    # evaluation) and the orphan-step-bead walker (to detect ghost
    # ancestors and stop the walk cleanly).
    known_ids = closed_ids | set(
        b.get("id") for b in (open_beads + in_progress) if b.get("id")
    )

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
    findings.extend(find_stale_blockers(detailed_by_id, closed_ids,
                                        known_ids=known_ids))
    findings.extend(find_orphan_step_beads(detailed_by_id, known_ids,
                                           closed_ids))
    findings.extend(find_cycles(selected_ids=cycle_filter_ids))

    # Write two /tmp/ files: findings JSON (no bead content) and flat bead
    # text (no findings). Stdout is a small summary that fits in any context
    # window. The skill reads the findings file directly and dispatches a
    # Read-only subagent for the LLM-inferred pass against the beads file.
    ts = int(time.time())
    findings_path = f"/tmp/dep-health-{ts}-findings.json"
    beads_path = f"/tmp/dep-health-{ts}-beads.txt"

    open_bead_count = sum(
        1 for bid, b in detailed_by_id.items()
        if not _is_mol_or_wisp(bid)
        and b.get("status") in ("open", "in_progress")
    )

    write_findings_file(prefix, args.mode, args.target,
                        len(beads_list), open_bead_count,
                        truncated_count, capped, findings,
                        findings_path)
    write_beads_file(detailed_by_id, beads_path)

    summary = {
        "project_prefix": prefix,
        "mode": args.mode,
        "target": args.target,
        "bead_count": len(beads_list),
        "open_bead_count": open_bead_count,
        "finding_counts": dict(Counter(f.get("type", "unknown") for f in findings)),
        "capped": capped,
        "findings_file": findings_path,
        "beads_file": beads_path,
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
