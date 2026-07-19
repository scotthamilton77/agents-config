"""Graphify two-tier dependency centrality axis (spec §6.2, plan §3.6).

Fixtures use the real `directed: false` node-link shape graphify emits, with
mixed `confidence` values, so both the confidence filter and the
`Graph`-vs-`DiGraph` trap are exercised against ground truth, not a
convenience shape. The tests pin the *invariants* the spec cares about
(two-tier confidence acceptance with per-edge provenance, intra-file
exclusion, head-graph projection, fail-soft optional-dependency behavior,
relation filtering) — not a specific score.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
import pytest

from vizsuite.extract.centrality import DEP_RELATIONS, CentralityAxis, centrality_axis

HEAD_OID = "head1234"
# A full lowercase 40-hex OID — the only marker shape the labeled-stale
# opt-in trusts (it flows into `git rev-list` argv downstream).
STALE_OID = "6505d208fee1dfa6d82555437571cfe35d1778aa"


def _node(node_id: str, source_file: str) -> dict[str, Any]:
    return {"id": node_id, "source_file": source_file}


def _link(source: str, target: str, *, relation: str, confidence: str) -> dict[str, Any]:
    return {"source": source, "target": target, "relation": relation, "confidence": confidence}


def _graph_json(
    *, built_at_commit: str, nodes: list[dict[str, Any]], links: list[dict[str, Any]]
) -> dict[str, Any]:
    # The real graphify node-link shape: undirected, symbol-level.
    return {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "built_at_commit": built_at_commit,
        "nodes": nodes,
        "links": links,
    }


def _write_graph(tmp_path: Path, payload: dict[str, Any]) -> Path:
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(payload), encoding="utf-8")
    return graph_path


def test_extracted_and_inferred_dependency_edges_both_contribute_in_degree(
    tmp_path: Path,
) -> None:
    # hub.py has one incoming EXTRACTED edge and inferred_only_hub.py has one
    # incoming INFERRED edge from a different file; both tiers now count
    # toward in-degree on the load-bearing axis.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[
            _node("s1", "caller_a.py"),
            _node("s2", "hub.py"),
            _node("s3", "caller_b.py"),
            _node("s4", "inferred_only_hub.py"),
        ],
        links=[
            _link("s1", "s2", relation="calls", confidence="EXTRACTED"),
            _link("s3", "s4", relation="calls", confidence="INFERRED"),
        ],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.is_available
    assert axis.scores is not None
    assert axis.scores["hub.py"] == 1.0
    assert axis.scores["inferred_only_hub.py"] == 1.0


def test_unknown_confidence_value_does_not_contribute(tmp_path: Path) -> None:
    # Neither EXTRACTED nor INFERRED — some other/unrecognized confidence tag
    # must still be dropped, same as before the two-tier acceptance.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[_node("s1", "caller.py"), _node("s2", "quarantined.py")],
        links=[_link("s1", "s2", relation="calls", confidence="SPECULATIVE")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.scores is not None
    assert axis.scores.get("quarantined.py", 0.0) == 0.0


def test_intra_file_edges_are_excluded_and_would_flip_the_ranking(tmp_path: Path) -> None:
    # Two symbols inside the SAME file reference each other (an intra-file
    # EXTRACTED edge) — if counted, quiet.py would falsely outrank real_hub.py.
    # real_hub.py's two incoming edges originate in a genuinely different file.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[
            _node("q1", "quiet.py"),
            _node("q2", "quiet.py"),  # same file as q1
            _node("h1", "real_hub.py"),
            _node("c1", "caller.py"),
            _node("c2", "caller.py"),
        ],
        links=[
            _link("q1", "q2", relation="calls", confidence="EXTRACTED"),  # intra-file, must drop
            _link("c1", "h1", relation="calls", confidence="EXTRACTED"),
            _link("c2", "h1", relation="uses", confidence="EXTRACTED"),
        ],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.scores is not None
    assert "quiet.py" not in axis.scores  # the only edge touching it was intra-file
    assert axis.scores["real_hub.py"] == 1.0  # the genuine cross-file hub


def test_naive_node_link_graph_construction_lacks_in_degree_locking_the_trap() -> None:
    # Documents the exact defect this module avoids: nx.node_link_graph() on a
    # directed:false payload returns an undirected Graph, which has no
    # in_degree — the naive path this module must never take.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[_node("a", "a.py"), _node("b", "b.py")],
        links=[_link("a", "b", relation="calls", confidence="EXTRACTED")],
    )
    naive_graph = nx.node_link_graph(payload, edges="links")

    assert isinstance(naive_graph, nx.Graph)
    assert not isinstance(naive_graph, nx.DiGraph)
    with pytest.raises(AttributeError):
        naive_graph.in_degree()  # type: ignore[operator]


def test_edges_carry_per_edge_provenance_and_intra_file_excluded(tmp_path: Path) -> None:
    # a.py -> b.py is a genuine cross-file EXTRACTED edge (provenance "extracted").
    # c.py -> d.py is a genuine cross-file INFERRED edge (provenance "inferred").
    # e1/e2 are two symbols in the SAME file (intra-file EXTRACTED edge, excluded).
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[
            _node("a1", "a.py"),
            _node("b1", "b.py"),
            _node("c1", "c.py"),
            _node("d1", "d.py"),
            _node("e1", "e.py"),
            _node("e2", "e.py"),
        ],
        links=[
            _link("a1", "b1", relation="calls", confidence="EXTRACTED"),
            _link("c1", "d1", relation="calls", confidence="INFERRED"),
            _link("e1", "e2", relation="uses", confidence="EXTRACTED"),
        ],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.is_available
    assert axis.edges == (
        ("a.py", "b.py", "extracted"),
        ("c.py", "d.py", "inferred"),
    )


def test_same_pair_both_tiers_extracted_provenance_wins(tmp_path: Path) -> None:
    # a.py -> b.py arises from both an INFERRED link (via a different symbol
    # pair) and an EXTRACTED link — the stronger "extracted" claim must win,
    # regardless of which link is encountered first in the graph.json list.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[
            _node("a1", "a.py"),
            _node("a2", "a.py"),
            _node("b1", "b.py"),
            _node("b2", "b.py"),
        ],
        links=[
            _link("a1", "b1", relation="calls", confidence="INFERRED"),
            _link("a2", "b2", relation="uses", confidence="EXTRACTED"),
        ],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.edges == (("a.py", "b.py", "extracted"),)

    # Order reversed: EXTRACTED encountered first must not be downgraded by a
    # later INFERRED link for the same file pair.
    reversed_payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=payload["nodes"],
        links=list(reversed(payload["links"])),
    )
    reversed_graph_path = _write_graph(tmp_path / "reversed", reversed_payload)

    reversed_axis = centrality_axis(reversed_graph_path, HEAD_OID)

    assert reversed_axis.edges == (("a.py", "b.py", "extracted"),)


def test_head_built_graph_scores_a_newly_added_files_incoming_edges(tmp_path: Path) -> None:
    # A head-built graph (built_at_commit == head_oid) already contains the new
    # file's edges — no overlay step needed, just the preflight passing.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[_node("n1", "existing_caller.py"), _node("n2", "new_hub.py")],
        links=[_link("n1", "n2", relation="calls", confidence="EXTRACTED")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.scores is not None
    assert axis.scores["new_hub.py"] > 0.0


def test_absent_graphify_out_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    missing_path = tmp_path / "graphify-out" / "graph.json"

    axis = centrality_axis(missing_path, HEAD_OID)

    assert not axis.is_available
    assert axis.scores is None
    assert axis.unavailable_reason


def test_stale_build_commit_is_unavailable_never_stale_as_fresh(tmp_path: Path) -> None:
    payload = _graph_json(
        built_at_commit="some-other-commit",
        nodes=[_node("a", "a.py"), _node("b", "b.py")],
        links=[_link("a", "b", relation="calls", confidence="EXTRACTED")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert not axis.is_available
    assert axis.scores is None
    # default (flag omitted) is byte-identical to `allow_stale=False`: the
    # opt-in must never be silently on.
    assert axis.stale_built_at_commit is None


def test_allow_stale_false_with_mismatched_commit_is_still_unavailable(tmp_path: Path) -> None:
    # Explicit `allow_stale=False` regression pin: identical outcome to the
    # flag-omitted case above — the opt-in is off by default and off means off.
    payload = _graph_json(
        built_at_commit="some-other-commit",
        nodes=[_node("a", "a.py"), _node("b", "b.py")],
        links=[_link("a", "b", relation="calls", confidence="EXTRACTED")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID, allow_stale=False)

    assert not axis.is_available
    assert axis.scores is None
    assert axis.unavailable_reason == "graph build-commit != PR head"


def test_allow_stale_accepts_mismatched_commit_and_surfaces_the_build_commit(
    tmp_path: Path,
) -> None:
    payload = _graph_json(
        built_at_commit=STALE_OID,
        nodes=[_node("a", "a.py"), _node("b", "b.py")],
        links=[_link("a", "b", relation="calls", confidence="EXTRACTED")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID, allow_stale=True)

    assert axis.is_available
    assert axis.scores is not None
    assert axis.scores["b.py"] == 1.0  # scored exactly like the fresh path
    assert axis.edges == (("a.py", "b.py", "extracted"),)
    assert axis.stale_built_at_commit == STALE_OID


@pytest.mark.parametrize(
    "marker",
    [
        "--glob=refs/heads/*..",  # option-shaped: would reach `git rev-list` argv downstream
        "some-other-commit",  # not a hex OID at all
        "ABC123" + "0" * 34,  # uppercase hex — git OIDs are lowercase
        "6505d208",  # abbreviated — only a full 40-hex OID is trusted
    ],
)
def test_allow_stale_rejects_a_marker_that_is_not_a_full_hex_oid(
    tmp_path: Path, marker: str
) -> None:
    # The accepted-stale marker flows into `git rev-list <marker>..<head>`
    # (verbs/pr.py `_commits_behind`), so the boundary here trusts nothing but
    # a full lowercase 40-hex object id — an option-shaped or garbage marker
    # stays on the unavailable path even with the opt-in on.
    payload = _graph_json(
        built_at_commit=marker,
        nodes=[_node("a", "a.py"), _node("b", "b.py")],
        links=[_link("a", "b", relation="calls", confidence="EXTRACTED")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID, allow_stale=True)

    assert not axis.is_available
    assert axis.unavailable_reason == "graph build-commit != PR head"
    assert axis.stale_built_at_commit is None


def test_allow_stale_with_matching_commit_is_fresh_not_stale(tmp_path: Path) -> None:
    # A fresh graph never gets stamped stale just because the caller opted in —
    # the opt-in only matters when it is actually needed.
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[_node("a", "a.py"), _node("b", "b.py")],
        links=[_link("a", "b", relation="calls", confidence="EXTRACTED")],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID, allow_stale=True)

    assert axis.is_available
    assert axis.stale_built_at_commit is None


def test_allow_stale_absent_graphify_out_is_still_unavailable(tmp_path: Path) -> None:
    missing_path = tmp_path / "graphify-out" / "graph.json"

    axis = centrality_axis(missing_path, HEAD_OID, allow_stale=True)

    assert not axis.is_available
    assert axis.scores is None
    assert axis.stale_built_at_commit is None


def test_allow_stale_truncated_invalid_json_is_still_unavailable(tmp_path: Path) -> None:
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text('{"built_at_commit": "some-other-commit", "nodes": [', encoding="utf-8")

    axis = centrality_axis(graph_path, HEAD_OID, allow_stale=True)

    assert not axis.is_available
    assert axis.scores is None
    assert axis.stale_built_at_commit is None


def test_allow_stale_missing_nodes_or_links_is_still_unavailable(tmp_path: Path) -> None:
    # The opt-in only bypasses the commit-identity check, never the parse
    # guards: a stale graph that is ALSO malformed still fails soft.
    graph_path = _write_graph(tmp_path, {"built_at_commit": "some-other-commit"})

    axis = centrality_axis(graph_path, HEAD_OID, allow_stale=True)

    assert not axis.is_available
    assert axis.scores is None
    assert axis.stale_built_at_commit is None


def test_truncated_invalid_json_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text('{"built_at_commit": "head1234", "nodes": [', encoding="utf-8")

    axis = centrality_axis(graph_path, HEAD_OID)

    assert not axis.is_available
    assert axis.scores is None


def test_non_dependency_relations_do_not_contribute(tmp_path: Path) -> None:
    # `contains`/`rationale_for` are not dependency relations; even at
    # EXTRACTED confidence they must never contribute to in-degree.
    assert "contains" not in DEP_RELATIONS
    assert "rationale_for" not in DEP_RELATIONS
    payload = _graph_json(
        built_at_commit=HEAD_OID,
        nodes=[_node("p1", "parent.py"), _node("p2", "child.py")],
        links=[
            _link("p1", "p2", relation="contains", confidence="EXTRACTED"),
            _link("p1", "p2", relation="rationale_for", confidence="EXTRACTED"),
        ],
    )
    graph_path = _write_graph(tmp_path, payload)

    axis = centrality_axis(graph_path, HEAD_OID)

    assert axis.scores is not None
    assert axis.scores.get("child.py", 0.0) == 0.0


def test_graph_json_missing_nodes_or_links_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    # Well-formed JSON, correct built_at_commit, but missing the nodes/links keys
    # entirely (a malformed graphify emission) — must fail soft, not KeyError.
    graph_path = _write_graph(tmp_path, {"built_at_commit": HEAD_OID})

    axis = centrality_axis(graph_path, HEAD_OID)

    assert not axis.is_available
    assert axis.scores is None


@pytest.mark.parametrize(
    "payload_text",
    [
        pytest.param('["not", "an", "object"]', id="top-level-array"),
        pytest.param('"just a string"', id="top-level-string"),
        pytest.param(
            json.dumps({"built_at_commit": HEAD_OID, "nodes": ["a", "b"], "links": []}),
            id="non-object-nodes",
        ),
        pytest.param(
            json.dumps(
                {
                    "built_at_commit": HEAD_OID,
                    "nodes": [{"id": "a", "source_file": "a.py"}],
                    "links": ["not-an-object"],
                }
            ),
            id="non-object-links",
        ),
        pytest.param(
            json.dumps({"built_at_commit": HEAD_OID, "nodes": 42, "links": 7}),
            id="non-iterable-nodes-links",
        ),
    ],
)
def test_valid_json_with_wrong_shape_is_unavailable_not_a_crash(
    tmp_path: Path, payload_text: str
) -> None:
    # Valid JSON that is not the expected node-link object shape (top-level
    # array/scalar, non-object node or link entries, non-iterable containers)
    # must fail soft like any other malformed graph.json — never raise.
    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(payload_text, encoding="utf-8")

    axis = centrality_axis(graph_path, HEAD_OID)

    assert not axis.is_available
    assert axis.scores is None
    assert axis.unavailable_reason


def test_centrality_axis_unavailable_and_from_indegree_helpers() -> None:
    unavailable = CentralityAxis.unavailable("no graphify-out")
    assert unavailable.scores is None
    assert unavailable.unavailable_reason == "no graphify-out"
    assert not unavailable.is_available
    assert unavailable.edges == ()  # fail-soft means empty edges too, never stale ones
    assert unavailable.stale_built_at_commit is None

    available = CentralityAxis.from_indegree({"a.py": 2, "b.py": 1, "c.py": 0})
    assert available.is_available
    assert available.scores == {"a.py": 1.0, "b.py": 0.5, "c.py": 0.0}
    assert available.edges == ()  # edges is opt-in via the `edges=` kwarg
    assert available.stale_built_at_commit is None  # opt-in via the `stale_built_at_commit=` kwarg

    empty = CentralityAxis.from_indegree({})
    assert empty.is_available
    assert empty.scores == {}

    edged = CentralityAxis.from_indegree({"a.py": 1}, edges=(("x.py", "a.py", "extracted"),))
    assert edged.edges == (("x.py", "a.py", "extracted"),)

    staled = CentralityAxis.from_indegree({"a.py": 1}, stale_built_at_commit="deadbeef")
    assert staled.stale_built_at_commit == "deadbeef"
