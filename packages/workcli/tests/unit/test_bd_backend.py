"""BdBackend: the Backend protocol's bd implementation, over a BdRunner.

Task 2 wires only the read primitives (`capabilities`, `get`, `batch_get`,
`query`) -- write/relation/sync primitives land in Tasks 3-5. Every test
here drives a `ScriptedBdRunner`, never a real subprocess.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError
from workcli.model import QueryFilters

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_capabilities_are_all_true_for_bd():
    backend = BdBackend(ScriptedBdRunner(steps=[]))

    caps = backend.capabilities

    assert caps.supports_ready is True
    assert caps.supports_dep_types is True
    assert caps.supports_sync is True


def test_get_sends_show_json_and_returns_the_normalized_item():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "agents-config-wgclw.9.1", "--json"),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.1.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    item = backend.get("agents-config-wgclw.9.1")

    assert item.id == "agents-config-wgclw.9.1"
    assert runner.calls == [("show", "agents-config-wgclw.9.1", "--json")]


def test_get_maps_no_issue_found_stderr_to_not_found_error():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.get("bogus-id")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_get_maps_an_unrecognized_nonzero_exit_to_backend_drift_with_diagnostic_detail():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("show",), BdResult(returncode=2, stdout="", stderr="boom: segfault"))]
    )
    backend = BdBackend(runner)

    try:
        backend.get("x.1")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT
        assert error.detail["returncode"] == 2
        assert "segfault" in error.detail["stderr"]
        assert error.detail["argv"] == ["show", "x.1", "--json"]


def test_batch_get_raises_not_found_when_bd_silently_omits_a_requested_id():
    # Empirically confirmed against the real bd binary: `bd show valid bogus
    # --json` exits 0 and returns only the valid item, logging the miss to
    # stderr rather than failing the whole call -- the facade must not treat
    # that as success (decision 10 needs `data.items` to match the request).
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show", "agents-config-wgclw.9.1", "bogus-id", "--json"),
                BdResult(returncode=0, stdout=_read("bd_show_wgclw9.1.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.batch_get(["agents-config-wgclw.9.1", "bogus-id"])
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND
        assert error.detail["missing"] == ["bogus-id"]


def test_query_defaults_to_limit_zero_meaning_unbounded():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=0, stdout=_read("bd_list_open_limit5.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.query(QueryFilters())

    assert len(items) == 5
    assert runner.calls == [("list", "--json", "--limit", "0")]


def test_query_passes_through_a_positive_limit_and_the_status_filter():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=0, stdout="[]", stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.query(QueryFilters(status="open", limit=7))

    assert runner.calls == [("list", "--json", "--status", "open", "--limit", "7")]


def test_query_passes_through_the_label_parent_and_type_filters():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=0, stdout="[]", stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    backend.query(QueryFilters(label="tech-debt", parent="x.1", type="task"))

    assert runner.calls == [
        (
            "list",
            "--json",
            "--label",
            "tech-debt",
            "--parent",
            "x.1",
            "--type",
            "task",
            "--limit",
            "0",
        )
    ]


def test_query_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("list", "--json"),
                BdResult(returncode=1, stdout="", stderr="boom: out of memory"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.query(QueryFilters())
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_ready_defaults_to_limit_zero_meaning_unbounded():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("ready", "--json"),
                BdResult(returncode=0, stdout=_read("bd_list_open_limit5.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.ready(None)

    assert len(items) == 5
    assert runner.calls == [("ready", "--json", "--limit", "0")]


def test_ready_passes_through_the_label_filter():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("ready", "--json"), BdResult(returncode=0, stdout="[]", stderr=""))]
    )
    backend = BdBackend(runner)

    backend.ready("tech-debt")

    assert runner.calls == [("ready", "--json", "--label", "tech-debt", "--limit", "0")]


def test_ready_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("ready", "--json"),
                BdResult(returncode=1, stdout="", stderr="boom: out of memory"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.ready(None)
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT


def test_search_sends_the_query_and_returns_normalized_items():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("search", "quarantine", "--json"),
                BdResult(returncode=0, stdout=_read("bd_list_open_limit5.json"), stderr=""),
            )
        ]
    )
    backend = BdBackend(runner)

    items = backend.search("quarantine")

    assert len(items) == 5
    assert runner.calls == [("search", "quarantine", "--json")]


def test_search_maps_an_unrecognized_nonzero_exit_to_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("search",),
                BdResult(returncode=1, stdout="", stderr="boom: out of memory"),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.search("x")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.BACKEND_DRIFT
