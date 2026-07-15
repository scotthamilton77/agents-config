"""cycle_guard.find_cycle: cycle-safety over the FULL accepted logical
dependency graph (spec §5.3/§5.7, test item 17).

The combined graph is beads `blocks` edges (read on demand through
`TrackerPort`, backed by `tests.fakes.ScriptedTrackerRunner` — no real
subprocess) plus sidecar-held accepted dependency edges passed in directly as
plain data (the sidecar itself is a separate concern this slice does not
read/write). These tests cover beads-only cycles, sidecar-only cycles, mixed
paths, safe cases, and pin the deterministic (sorted-child) traversal order.
"""

from __future__ import annotations

from tests.fakes import ScriptedTrackerRunner, tracker_show_ok
from vizsuite.tracker.cycle_guard import (
    CycleRefusal,
    ProposedEdge,
    Safe,
    SidecarDependencyEdge,
    find_cycle,
)
from vizsuite.tracker.port import TrackerPort, TrackerResult


def _port(show_results: dict[str, TrackerResult]) -> tuple[TrackerPort, ScriptedTrackerRunner]:
    runner = ScriptedTrackerRunner(show_results=show_results)
    return TrackerPort(runner), runner


def test_safe_when_target_unreachable():
    port, _runner = _port({"b": tracker_show_ok("b", deps=[])})

    result = find_cycle(port, sidecar_edges=(), proposed=ProposedEdge("a", "b"))

    assert result == Safe()


def test_cycle_through_beads_edges_alone():
    # "b" already (directly) depends on "a" via a real beads `blocks` edge;
    # proposing "a depends on b" would close the loop.
    port, _runner = _port({"b": tracker_show_ok("b", deps=[("a", "blocks", "open")])})

    result = find_cycle(port, sidecar_edges=(), proposed=ProposedEdge("a", "b"))

    assert result == CycleRefusal(cycle=("a", "b", "a"))


def test_cycle_through_sidecar_edges_alone():
    # "y" depends on "x" only via a sidecar-held accepted edge (e.g. a
    # type-wall `related-to` fallback) -- beads itself carries no `blocks`
    # edge for this pair.
    port, _runner = _port({"y": tracker_show_ok("y", deps=[])})
    sidecar_edges = (SidecarDependencyEdge(from_bead="y", to_bead="x"),)

    result = find_cycle(port, sidecar_edges=sidecar_edges, proposed=ProposedEdge("x", "y"))

    assert result == CycleRefusal(cycle=("x", "y", "x"))


def test_cycle_through_mixed_beads_and_sidecar_edges():
    # q -[sidecar]-> r -[beads blocks]-> p; proposing "p depends on q" closes
    # a cycle that crosses both edge sources.
    port, _runner = _port(
        {
            "q": tracker_show_ok("q", deps=[]),
            "r": tracker_show_ok("r", deps=[("p", "blocks", "open")]),
        }
    )
    sidecar_edges = (SidecarDependencyEdge(from_bead="q", to_bead="r"),)

    result = find_cycle(port, sidecar_edges=sidecar_edges, proposed=ProposedEdge("p", "q"))

    assert result == CycleRefusal(cycle=("p", "q", "r", "p"))


def test_related_to_beads_edges_do_not_count_toward_cycles():
    # A beads `related-to` edge that is NOT a sidecar-declared dependency
    # fallback (e.g. discoverability for an overlap/conflict/synergy fact)
    # must never be treated as a logical dependency.
    port, _runner = _port({"b": tracker_show_ok("b", deps=[("a", "related-to", "open")])})

    result = find_cycle(port, sidecar_edges=(), proposed=ProposedEdge("a", "b"))

    assert result == Safe()


def test_self_loop_is_refused_without_touching_the_port():
    runner = ScriptedTrackerRunner()
    port = TrackerPort(runner)

    result = find_cycle(port, sidecar_edges=(), proposed=ProposedEdge("x.1", "x.1"))

    assert result == CycleRefusal(cycle=("x.1", "x.1"))
    assert runner.calls == []


def test_safe_diamond_does_not_revisit_a_shared_node():
    port, runner = _port(
        {
            "start": tracker_show_ok(
                "start", deps=[("n1", "blocks", "open"), ("n2", "blocks", "open")]
            ),
            "n1": tracker_show_ok("n1", deps=[("shared", "blocks", "open")]),
            "n2": tracker_show_ok("n2", deps=[("shared", "blocks", "open")]),
            "shared": tracker_show_ok("shared", deps=[]),
        }
    )

    result = find_cycle(port, sidecar_edges=(), proposed=ProposedEdge("target", "start"))

    assert result == Safe()
    # "shared" is reachable via both n1 and n2 -- the visited-set
    # short-circuit means it is read exactly once, not twice.
    assert runner.calls.count(("show", "shared")) == 1


def test_deterministic_cycle_path_explores_the_lexicographically_first_child():
    # "start" depends on both path_b and path_a; sorted order visits path_a
    # first. path_b has NO scripted `show` response on purpose -- if the
    # traversal ever visited it, the fake would raise, proving determinism.
    port, _runner = _port(
        {
            "start": tracker_show_ok(
                "start", deps=[("path_b", "blocks", "open"), ("path_a", "blocks", "open")]
            ),
            "path_a": tracker_show_ok("path_a", deps=[("end", "blocks", "open")]),
        }
    )

    result = find_cycle(port, sidecar_edges=(), proposed=ProposedEdge("end", "start"))

    assert result == CycleRefusal(cycle=("end", "start", "path_a", "end"))


def test_a_chain_deeper_than_the_recursion_limit_still_returns_a_typed_result():
    # 5000-link sidecar chain: n0000 -> n0001 -> ... -> n5000. Proposing
    # "n5000 depends on n0000" closes the loop; the traversal must walk the
    # full depth and return CycleRefusal, never a RecursionError escaping the
    # Safe/CycleRefusal contract (each node also answers an empty beads read).
    depth = 5000
    names = [f"n{i:04d}" for i in range(depth + 1)]
    show_results = {name: tracker_show_ok(name, deps=[]) for name in names}
    port, _runner = _port(show_results)
    sidecar_edges = tuple(
        SidecarDependencyEdge(from_bead=names[i], to_bead=names[i + 1]) for i in range(depth)
    )

    result = find_cycle(
        port, sidecar_edges=sidecar_edges, proposed=ProposedEdge(names[-1], names[0])
    )

    assert isinstance(result, CycleRefusal)
    assert len(result.cycle) == depth + 2  # n5000, n0000..n5000
    assert result.cycle[0] == names[-1] and result.cycle[-1] == names[-1]
