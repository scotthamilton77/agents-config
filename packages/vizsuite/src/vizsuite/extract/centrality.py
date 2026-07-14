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
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx

# Dependency-relation edge types the centrality axis considers; non-dependency
# relations (`contains`, `rationale_for`, ...) never contribute (item 9).
DEP_RELATIONS = frozenset({"calls", "uses", "imports_from", "inherits", "implements"})
_EXTRACTED = "EXTRACTED"  # Tier-1 determinism boundary (R3-1)


@dataclass(frozen=True)
class CentralityAxis:
    """Per-file 0-1 in-degree centrality, or unavailable with a reason.

    `scores` is `None` exactly when the axis is unavailable (optional
    dependency absent, stale, or unparseable) — distinct from an *available*
    axis whose graph happens to carry zero qualifying edges (an empty dict).
    """

    scores: dict[str, float] | None
    unavailable_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.scores is not None

    @staticmethod
    def unavailable(reason: str) -> CentralityAxis:
        return CentralityAxis(scores=None, unavailable_reason=reason)

    @staticmethod
    def from_indegree(indegree: dict[str, int]) -> CentralityAxis:
        """Normalize raw file-level in-degree counts to a 0-1 axis."""
        max_degree = max(indegree.values(), default=0)
        scores = {
            path: (degree / max_degree if max_degree > 0 else 0.0)
            for path, degree in indegree.items()
        }
        return CentralityAxis(scores=scores)


def centrality_axis(graph_path: Path, head_oid: str) -> CentralityAxis:
    """Load-bearing axis from graphify. Tier-1 determinism: `EXTRACTED` edges
    only (`INFERRED` graph edges are Tier-2, out of scope for `.2.1`). Intra-file
    edges are dropped; projected post-PR centrality via the head-graph preflight
    (no overlay — a head-built graph already contains new code's edges).
    """
    if not graph_path.exists():
        return CentralityAxis.unavailable("graphify-out absent")  # optional dep, fail soft
    try:
        raw: Any = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return CentralityAxis.unavailable("graph.json unreadable (torn mid-write?)")  # fail soft
    if not isinstance(raw, dict):
        return CentralityAxis.unavailable("graph.json malformed (not a JSON object)")
    if raw.get("built_at_commit") != head_oid:
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
    return CentralityAxis.from_indegree(dict(graph.in_degree()))  # normalized 0-1 per file
