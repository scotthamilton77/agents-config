"""Graphify EXTRACTED-dependency centrality axis (spec §6.2, plan §3.6).

Load-bearing axis sourced from graphify's `graph.json`, restricted to
deterministic (Tier-1 `EXTRACTED`) dependency-relation edges — `INFERRED`
edges (60% of the real graph's dependency-relation edges) are Tier-2 inference
and out of scope here (R3-1); counting them would launder agent-produced
inference into a "deterministic" axis. The graph is undirected, symbol-level
node-link JSON with no stored centrality, so this module rolls symbols up to a
file-level `DiGraph` (dropping intra-file edges) and scores normalized
in-degree. `nx.node_link_graph` is deliberately never used to build that graph:
for this `directed: false` payload it returns an undirected `Graph`, which has
no `in_degree`.

graphify is an optional dependency: an absent `graphify-out/`, a stale build
(`built_at_commit != head_oid`), unparseable/torn JSON, or valid JSON of the
wrong shape (non-object payload, malformed nodes/links) all fail soft to
`CentralityAxis.unavailable(...)` — never a crash, never stale-as-fresh.

A caller may opt in to a labeled-stale path (`allow_stale=True`, spec §6.2):
a graph whose `built_at_commit` differs from `head_oid` is scored exactly like
a fresh one, with `CentralityAxis.stale_built_at_commit` set to the graph's own
build commit so the caller can render a visible staleness label. The opt-in
only bypasses the commit-identity check — an absent/unreadable/malformed graph
still fails soft to unavailable regardless of the flag.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

# Dependency-relation edge types the centrality axis considers; non-dependency
# relations (`contains`, `rationale_for`, ...) never contribute (item 9).
DEP_RELATIONS = frozenset({"calls", "uses", "imports_from", "inherits", "implements"})
_EXTRACTED = "EXTRACTED"  # Tier-1 determinism boundary (R3-1)
# The only build-commit marker shape the labeled-stale opt-in trusts: a full
# lowercase 40-hex object id (the marker reaches `git rev-list` argv downstream).
_FULL_HEX_OID_RE = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class CentralityAxis:
    """Per-file 0-1 in-degree centrality, or unavailable with a reason.

    `scores` is `None` exactly when the axis is unavailable (optional
    dependency absent, stale, or unparseable) — distinct from an *available*
    axis whose graph happens to carry zero qualifying edges (an empty dict).
    `edges` is the same file-level `DiGraph`'s EXTRACTED, intra-file-excluded
    edge list the scores were derived from (one graph build, kept together);
    it is empty whenever the axis is unavailable — never a stale edge set.
    `stale_built_at_commit` is the graph's own build commit exactly when the
    caller opted into the labeled-stale path (`allow_stale=True`) and the
    graph's `built_at_commit` differed from the target revision; it is `None`
    for a fresh graph or an unavailable axis — never a marker with no graph
    behind it.
    """

    scores: dict[str, float] | None
    unavailable_reason: str | None = None
    edges: tuple[tuple[str, str], ...] = ()
    stale_built_at_commit: str | None = None

    @property
    def is_available(self) -> bool:
        return self.scores is not None

    @staticmethod
    def unavailable(reason: str) -> CentralityAxis:
        return CentralityAxis(scores=None, unavailable_reason=reason)

    @staticmethod
    def from_indegree(
        indegree: dict[str, int],
        edges: tuple[tuple[str, str], ...] = (),
        *,
        stale_built_at_commit: str | None = None,
    ) -> CentralityAxis:
        """Normalize raw file-level in-degree counts to a 0-1 axis."""
        max_degree = max(indegree.values(), default=0)
        scores = {
            path: (degree / max_degree if max_degree > 0 else 0.0)
            for path, degree in indegree.items()
        }
        return CentralityAxis(
            scores=scores, edges=edges, stale_built_at_commit=stale_built_at_commit
        )


def centrality_axis(
    graph_path: Path, head_oid: str, *, allow_stale: bool = False
) -> CentralityAxis:
    """Load-bearing axis from graphify. Tier-1 determinism: `EXTRACTED` edges
    only (`INFERRED` graph edges are Tier-2, out of scope for `.2.1`). Intra-file
    edges are dropped; projected post-PR centrality via the head-graph preflight
    (no overlay — a head-built graph already contains new code's edges).

    `allow_stale=True` (spec §6.2 explicit opt-in) accepts a graph whose
    `built_at_commit` differs from `head_oid`, scoring it exactly like a fresh
    graph but stamping `stale_built_at_commit` with the graph's own build
    commit. The opt-in never bypasses the parse guards below it: an absent,
    unreadable, or wrong-shape graph is unavailable either way.
    """
    if not graph_path.exists():
        return CentralityAxis.unavailable("graphify-out absent")  # optional dep, fail soft
    try:
        raw: Any = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return CentralityAxis.unavailable("graph.json unreadable (torn mid-write?)")  # fail soft
    if not isinstance(raw, dict):
        return CentralityAxis.unavailable("graph.json malformed (not a JSON object)")

    built_at_commit = raw.get("built_at_commit")
    is_stale = built_at_commit != head_oid
    # A stale graph is only ever accepted when the caller opted in AND the
    # build-commit marker is a full lowercase 40-hex object id. The accepted
    # marker flows into `git rev-list <marker>..<head>` argv downstream
    # (verbs/pr.py `_commits_behind`), and no `--` placement can stop git from
    # option-parsing a leading-dash revision token — so this boundary is the
    # injection guard: anything not OID-shaped (missing, garbage, abbreviated,
    # option-shaped) stays on the loud unavailable path even with the opt-in on.
    accepted_stale = bool(
        is_stale
        and allow_stale
        and isinstance(built_at_commit, str)
        and _FULL_HEX_OID_RE.fullmatch(built_at_commit)
    )
    if is_stale and not accepted_stale:
        return CentralityAxis.unavailable("graph build-commit != PR head")  # never stale-as-fresh

    # The whole rollup + graph build is one fail-soft boundary: graphify's JSON
    # is outside-world input, so any wrong-shape payload that survived parsing
    # (non-object nodes/links entries, non-iterable containers, missing keys)
    # funnels to unavailable() rather than escaping as a raw exception.
    try:
        nodes = raw["nodes"]
        links = raw["links"]
        id_to_file = {
            n["id"]: n["source_file"] for n in nodes if n.get("id") and n.get("source_file")
        }
        graph: nx.DiGraph[str] = nx.DiGraph()
        for link in links:
            if link.get("relation") not in DEP_RELATIONS:
                continue
            if link.get("confidence") != _EXTRACTED:  # Tier-1 determinism (R3-1)
                continue
            src = id_to_file.get(link.get("source"))
            dst = id_to_file.get(link.get("target"))
            if src is None or dst is None or src == dst:  # drop intra-file edges
                continue
            graph.add_edge(src, dst)  # file-level dependency edge
    except (KeyError, TypeError, AttributeError):
        return CentralityAxis.unavailable(
            "graph.json malformed (missing or wrong-shape nodes/links)"
        )
    # Same graph, same pass: the edge list backing `scores` is just this
    # DiGraph's own (already EXTRACTED-only, intra-file-excluded) edges.
    # Ordering is left to the downstream `scene_to_json` sort — no need to
    # sort twice.
    edges = tuple(graph.edges())
    return CentralityAxis.from_indegree(
        dict(graph.in_degree()),
        edges=edges,
        stale_built_at_commit=built_at_commit if accepted_stale else None,
    )
