"""work graph --json: bulk node/edge export validating against the shipped schema."""

from __future__ import annotations

import json
from argparse import Namespace
from importlib import resources

import jsonschema
import pytest

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.model import DepEdge
from workcli.verbs.report import graph

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
    backlog_groom_nag_days=None,
    groom_state_bead=None,
    extraction_max_track_backlog=None,
    extraction_external_consumer_tracks=(),
    extraction_independent_release_tracks=(),
    extraction_max_cross_track_edges=None,
)


def _graph_args(*, json_output: bool = True) -> Namespace:
    return Namespace(json_output=json_output, load_config=lambda: CONFIG)


def _backend() -> FakeBackend:
    backend = FakeBackend()
    backend.add("m-1", type="milestone", status="in_progress")
    # Non-closed bead whose ancestry runs through a CLOSED epic.
    backend.add("closed-epic", type="epic", status="closed", parent="m-1")
    backend.add(
        "leaf",
        parent="closed-epic",
        labels=["track:alpha"],
        deps=[DepEdge(id="blocker", type="blocks", status="open")],
    )
    backend.add("blocker", labels=["track:beta"])
    return backend


def _schema() -> dict[str, object]:
    schema_text = (resources.files("workcli") / "schemas" / "work-graph.schema.json").read_text(
        encoding="utf-8"
    )
    loaded = json.loads(schema_text)
    assert isinstance(loaded, dict)
    return loaded


def test_graph_output_validates_against_shipped_schema() -> None:
    data = graph(_backend(), _graph_args())
    jsonschema.validate(data, _schema())  # criterion 12's contract leg


def test_graph_carries_every_nonclosed_bead_with_track_and_typed_edges() -> None:
    data = graph(_backend(), _graph_args())
    assert isinstance(data, dict)
    nodes = data["nodes"]
    edges = data["edges"]
    assert isinstance(nodes, list)
    assert isinstance(edges, list)

    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    # Every non-closed bead present...
    assert {"m-1", "leaf", "blocker"} <= set(by_id)
    # ...plus the closed container needed for leaf's ancestry.
    assert "closed-epic" in by_id
    assert by_id["closed-epic"]["status"] == "closed"
    assert by_id["leaf"]["track"] == "alpha"
    assert by_id["m-1"]["track"] is None

    assert {"from": "leaf", "to": "blocker", "type": "blocks"} in edges
    assert {"from": "leaf", "to": "closed-epic", "type": "parent-child"} in edges
    assert {"from": "closed-epic", "to": "m-1", "type": "parent-child"} in edges


def test_graph_without_json_flag_is_usage_error() -> None:
    with pytest.raises(WorkError) as exc_info:
        graph(_backend(), _graph_args(json_output=False))
    assert exc_info.value.code is ErrorCode.USAGE
