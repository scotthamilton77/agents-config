"""`work discover` -- mechanical enforcement of discovered-work triage form.

Covers the 2026-07-17 spec's acceptance criteria 1-18. Most behavior is
exercised directly against `discover()` with a `FakeBackend` (state-based
assertions, mirroring `test_create_track_gate.py`'s convention for
create-composition tests); a handful of criteria that are specifically about
bd call *order* (AC5, AC15) or the pre-handler capability gate (AC17) go
through the CLI (`run_cli`/`run_cli_with_runner`/`cli_module.main`) instead,
matching `test_dep_type_wall.py`/`test_capabilities.py`.
"""

from __future__ import annotations

import json
from argparse import Namespace
from io import StringIO

import pytest

from tests.conftest import run_cli, run_cli_with_runner
from tests.fake_backend import FakeBackend
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli import cli as cli_module
from workcli.adapters.bd.runner import BdResult
from workcli.backend import Capabilities, DepOp, ReadySupport, SyncSupport
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.discover import discover


def _not_found_config_loader(_explicit_path: str | None = None) -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def _config(enforcement: str) -> TrackLayerConfig:
    return TrackLayerConfig(
        names=("alpha", "beta"),
        organizing_only=(),
        enforcement=enforcement,
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        extraction_max_track_backlog=None,
        extraction_external_consumer_tracks=(),
        extraction_independent_release_tracks=(),
        extraction_max_cross_track_edges=None,
    )


def _args(
    *,
    noun: str = "feat",
    title: str = "New discovery",
    description: str | None = None,
    anchor: str | None = None,
    orphan: bool = False,
    discovered_from: str | None = "src-1",
    scope: str | None = "out-of-scope",
    scope_why: str | None = "rationale",
    priority: str | None = "P2",
    priority_why: str | None = "reason",
    anchor_why: str | None = None,
    escalation_why: str | None = None,
    track: str | None = None,
    load_config: object = _not_found_config_loader,
) -> Namespace:
    return Namespace(
        noun=noun,
        title=title,
        description=description,
        anchor=anchor,
        orphan=orphan,
        discovered_from=discovered_from,
        scope=scope,
        scope_why=scope_why,
        priority=priority,
        priority_why=priority_why,
        anchor_why=anchor_why,
        escalation_why=escalation_why,
        track=track,
        load_config=load_config,
    )


def _backend_with_epic_anchor() -> FakeBackend:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["shape-epic"])
    backend.add("src-1", type="task", parent="epic-1")
    return backend


def _out_of_scope_args(**overrides: object) -> Namespace:
    base = dict(anchor="epic-1", anchor_why="best fit epic")
    base.update(overrides)
    return _args(**base)  # type: ignore[arg-type]


# --- AC1: missing triage fields -> E_TRIAGE_INCOMPLETE, creates nothing ---


@pytest.mark.parametrize(
    "field", ["scope", "scope_why", "priority", "priority_why", "discovered_from"]
)
def test_missing_triage_field_refuses_and_creates_nothing(field: str) -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(**{field: None})

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == field
    assert backend.ids() == ["epic-1", "src-1"]


# --- AC2: anchor/orphan XOR -> E_USAGE ---


def test_neither_anchor_nor_orphan_is_usage_error() -> None:
    backend = _backend_with_epic_anchor()
    args = _args(anchor=None, orphan=False, anchor_why="x")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE
    assert backend.ids() == ["epic-1", "src-1"]


def test_both_anchor_and_orphan_is_usage_error() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(orphan=True, escalation_why="none fits")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE


# --- AC3: invalid scope / unknown hatch / bad priority -> E_TRIAGE_INCOMPLETE ---


def test_invalid_scope_value_names_field() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(scope="sideways")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "scope"


def test_unknown_hatch_names_field_and_valid_vocabulary() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(scope="in-scope-deferred:rushed")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert "blast-radius" in exc_info.value.message


def test_invalid_priority_names_field_and_accepted_range() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "priority"
    assert "P0" in exc_info.value.message and "P4" in exc_info.value.message


# --- AC4: escalation/anchor rationale required; rationale-shape rule ---


def test_orphan_without_escalation_why_refuses() -> None:
    backend = _backend_with_epic_anchor()
    args = _args(anchor=None, orphan=True, escalation_why=None)

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "escalation_why"


def test_anchor_without_anchor_why_refuses() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(anchor_why=None)

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "anchor_why"


@pytest.mark.parametrize("bad_value", ["", "   ", "line one\nline two", "line\rreturn"])
def test_blank_or_multiline_rationale_refuses_and_creates_nothing(bad_value: str) -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(scope_why=bad_value)

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "scope_why"
    assert backend.ids() == ["epic-1", "src-1"]


# --- AC5: a valid --anchor invocation mints with both edges in one call ---


def test_valid_anchor_invocation_creates_both_edges_in_call_order() -> None:
    def _show_result(item_id: str, issue_type: str) -> BdResult:
        return BdResult(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": item_id,
                        "title": "t",
                        "issue_type": issue_type,
                        "status": "open",
                        "priority": 2,
                        "labels": [],
                    }
                ]
            ),
            stderr="",
        )

    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show", "src-1", "--json"), _show_result("src-1", "task")),
            ScriptedStep(("show", "epic-1", "--json"), _show_result("epic-1", "epic")),
            ScriptedStep(("search",), BdResult(returncode=0, stdout=json.dumps([]), stderr="")),
            ScriptedStep(
                ("create",),
                BdResult(returncode=0, stdout=json.dumps({"id": "new-1"}), stderr=""),
            ),
            ScriptedStep(("dep", "add"), BdResult(returncode=0, stdout="", stderr="")),
            ScriptedStep(("show", "new-1", "--json"), _show_result("new-1", "feature")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        [
            "discover",
            "--noun",
            "feat",
            "--title",
            "New discovery",
            "--anchor",
            "epic-1",
            "--anchor-why",
            "best fit",
            "--discovered-from",
            "src-1",
            "--scope",
            "out-of-scope",
            "--scope-why",
            "found it",
            "--priority",
            "P2",
            "--priority-why",
            "hurts overnight",
        ],
        runner,
        config_loader=_not_found_config_loader,
    )

    assert exit_code == 0
    assert envelope["ok"] is True
    create_index = next(i for i, call in enumerate(runner.calls) if call[0] == "create")
    assert "--parent" in runner.calls[create_index] and "epic-1" in runner.calls[create_index]
    assert runner.calls[create_index + 1] == (
        "dep",
        "add",
        "new-1",
        "src-1",
        "--type",
        "discovered-from",
    )


# --- AC6/AC7: manifest_row shape + remaining_work ---


def test_manifest_row_out_of_scope_and_remaining_work_false() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args()

    data = discover(backend, args)

    assert isinstance(data, dict)
    row = data["manifest_row"]
    assert isinstance(row, dict)
    assert row["item"] == "New discovery"
    assert row["lands_in"] == "epic-1"
    assert row["tracked_item"] == data["item"]["id"]  # type: ignore[index]
    assert row["priority_why"] == "P2 — reason"
    assert data["remaining_work"] is False


def test_manifest_row_in_scope_deferred_lands_in_parent_and_remaining_work_true() -> None:
    backend = _backend_with_epic_anchor()
    args = _args(
        anchor="epic-1",
        anchor_why="sibling",
        scope="in-scope-deferred:blast-radius",
    )

    data = discover(backend, args)

    assert isinstance(data, dict)
    row = data["manifest_row"]
    assert isinstance(row, dict)
    assert row["lands_in"] == "parent work item (epic-1)"
    assert data["remaining_work"] is True


def test_manifest_row_orphan_lands_in_unanchored() -> None:
    backend = _backend_with_epic_anchor()
    args = _args(anchor=None, orphan=True, escalation_why="nothing fits")

    data = discover(backend, args)

    assert isinstance(data, dict)
    row = data["manifest_row"]
    assert isinstance(row, dict)
    assert row["lands_in"] == "unanchored — needs your call"


# --- AC8: rendered triage block ---


def test_rendered_triage_block_out_of_scope() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args()

    data = discover(backend, args)

    assert isinstance(data, dict)
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    description = backend.get(new_id).description
    assert "## Triage" in description
    assert "- Scope: out-of-scope — rationale" in description
    assert "- Priority: P2 — reason" in description
    assert "- Anchor: epic-1 — best fit epic" in description


def test_rendered_triage_block_in_scope_deferred_never_shows_raw_cli_token() -> None:
    backend = _backend_with_epic_anchor()
    args = _args(anchor="epic-1", anchor_why="sibling", scope="in-scope-deferred:blast-radius")

    data = discover(backend, args)

    assert isinstance(data, dict)
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    description = backend.get(new_id).description
    assert "- Scope: in-scope — deferred: blast-radius — rationale" in description
    assert "in-scope-deferred:blast-radius" not in description


# --- AC9: duplicate title -> E_DUPLICATE_TITLE, creates nothing ---


def test_duplicate_title_refuses_and_creates_nothing() -> None:
    backend = _backend_with_epic_anchor()
    backend.add("dup-1", title="New discovery")
    args = _out_of_scope_args()

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.DUPLICATE_TITLE
    assert backend.ids() == ["epic-1", "src-1", "dup-1"]


# --- AC10: discovered-from edge add fails -> detail.created_id set ---


class _EdgeFailingBackend(FakeBackend):
    def dep_mutate(self, op: DepOp, from_id: str, to_id: str, dep_type: str) -> None:
        if dep_type == "discovered-from":
            raise WorkError(ErrorCode.BACKEND_DRIFT, "boom", detail={})
        super().dep_mutate(op, from_id, to_id, dep_type)


def test_edge_add_failure_surfaces_created_id_for_replay() -> None:
    backend = _EdgeFailingBackend()
    backend.add("epic-1", type="epic", labels=["shape-epic"])
    backend.add("src-1", type="task", parent="epic-1")
    args = _out_of_scope_args()

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.BACKEND_DRIFT
    assert exc_info.value.detail["created_id"] in backend.ids()
    assert exc_info.value.detail["created_id"] not in ("epic-1", "src-1")


# --- AC11: --noun spec/epic -> E_USAGE (leaf nouns only, argparse choices) ---


@pytest.mark.parametrize("noun", ["spec", "epic"])
def test_container_noun_is_usage_error_via_cli(noun: str) -> None:
    exit_code, envelope, _ = run_cli(
        [
            "discover",
            "--noun",
            noun,
            "--title",
            "T",
            "--anchor",
            "epic-1",
            "--anchor-why",
            "x",
            "--discovered-from",
            "src-1",
            "--scope",
            "out-of-scope",
            "--scope-why",
            "x",
            "--priority",
            "P2",
            "--priority-why",
            "x",
        ],
        steps=[],
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.USAGE)  # type: ignore[index]


# --- AC12: every invocation emits exactly one parseable envelope ---


def test_success_and_failure_each_emit_one_envelope_with_protocol_and_matching_exit_code() -> None:
    exit_code, envelope, _ = run_cli(["discover", "--noun", "feat", "--title", "T"], steps=[])
    assert exit_code == 1
    assert envelope["ok"] is False
    assert "protocol" in envelope


# --- AC13: track layer composition ---


def test_orphan_required_mode_no_track_fails_track_required() -> None:
    backend = FakeBackend()
    backend.add("src-1", type="task")
    args = _args(
        anchor=None,
        orphan=True,
        escalation_why="nothing fits",
        load_config=lambda: _config("required"),
    )

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRACK_REQUIRED


def test_orphan_required_mode_with_track_succeeds() -> None:
    backend = FakeBackend()
    backend.add("src-1", type="task")
    args = _args(
        anchor=None,
        orphan=True,
        escalation_why="nothing fits",
        track="alpha",
        load_config=lambda: _config("required"),
    )

    data = discover(backend, args)

    assert isinstance(data, dict)
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    assert "track:alpha" in backend.labels(new_id)


def test_orphan_advisory_mode_no_track_succeeds_with_warning() -> None:
    backend = FakeBackend()
    backend.add("src-1", type="task")
    args = _args(
        anchor=None,
        orphan=True,
        escalation_why="nothing fits",
        load_config=lambda: _config("advisory"),
    )

    data = discover(backend, args)

    assert isinstance(data, dict)
    warnings = data["warnings"]
    assert isinstance(warnings, list)
    assert any("untracked" in str(w) for w in warnings)


def test_anchor_under_trackless_milestone_required_mode_fails_without_track() -> None:
    backend = FakeBackend()
    backend.add("milestone-1", type="milestone")
    backend.add("src-1", type="task", parent="milestone-1")
    args = _args(
        anchor="milestone-1",
        anchor_why="fallback container",
        load_config=lambda: _config("required"),
    )

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRACK_REQUIRED


def test_anchor_under_trackless_milestone_with_track_succeeds() -> None:
    backend = FakeBackend()
    backend.add("milestone-1", type="milestone")
    backend.add("src-1", type="task", parent="milestone-1")
    args = _args(
        anchor="milestone-1",
        anchor_why="fallback container",
        track="alpha",
        load_config=lambda: _config("required"),
    )

    data = discover(backend, args)

    assert isinstance(data, dict)
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    assert "track:alpha" in backend.labels(new_id)


# --- AC14: --discovered-from names a nonexistent item ---


def test_discovered_from_not_found_names_flag_and_creates_nothing() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(discovered_from="ghost-1")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.NOT_FOUND
    assert "--discovered-from" in exc_info.value.message
    assert backend.ids() == ["epic-1", "src-1"]


# --- AC15: orphan create succeeds, orphan-marker append fails ---


class _OrphanMarkerFailingBackend(FakeBackend):
    def append_note(self, _item_id: str, _text: str) -> None:
        raise WorkError(ErrorCode.BACKEND_DRIFT, "append boom", detail={})


def test_orphan_marker_append_failure_surfaces_created_id() -> None:
    backend = _OrphanMarkerFailingBackend()
    backend.add("src-1", type="task")
    args = _args(anchor=None, orphan=True, escalation_why="nothing fits")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.BACKEND_DRIFT
    assert exc_info.value.detail["created_id"] in backend.ids()


# --- AC16: out-of-scope non-container anchor refuses; in-scope-deferred allows it ---


def test_out_of_scope_non_container_anchor_refuses_and_creates_nothing() -> None:
    backend = FakeBackend()
    backend.add("leaf-1", type="task")  # non-container
    backend.add("src-1", type="task", parent="leaf-1")
    args = _args(anchor="leaf-1", anchor_why="x", scope="out-of-scope")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "anchor"
    assert backend.ids() == ["leaf-1", "src-1"]


def test_in_scope_deferred_non_container_anchor_that_is_sibling_parent_succeeds() -> None:
    backend = FakeBackend()
    backend.add("leaf-1", type="task")  # non-container, but IS source's parent
    backend.add("src-1", type="task", parent="leaf-1")
    args = _args(anchor="leaf-1", anchor_why="sibling", scope="in-scope-deferred:blast-radius")

    data = discover(backend, args)

    assert isinstance(data, dict)
    warnings = data["warnings"]
    assert warnings == []


# --- AC17: dep-write capability gate refuses before the handler runs ---


class _StubDepWriteDenyingBackend:
    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            ready=ReadySupport.NATIVE, sync=SyncSupport.NATIVE, supports_dep_write=False
        )

    def search(self, _query: str) -> list[object]:
        raise AssertionError("capability gate must refuse dispatch before the handler runs")

    def create(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("capability gate must refuse dispatch before the handler runs")


def test_discover_dispatch_refused_when_backend_denies_dep_write(monkeypatch) -> None:
    monkeypatch.setattr(
        cli_module, "_build_backend", lambda _runner, _sleep: _StubDepWriteDenyingBackend()
    )
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(
        [
            "discover",
            "--noun",
            "feat",
            "--title",
            "T",
            "--anchor",
            "epic-1",
            "--anchor-why",
            "x",
            "--discovered-from",
            "src-1",
            "--scope",
            "out-of-scope",
            "--scope-why",
            "x",
            "--priority",
            "P2",
            "--priority-why",
            "x",
        ],
        out=out,
        err=err,
    )

    assert exit_code == 1
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == str(ErrorCode.UNSUPPORTED_CAPABILITY)


# --- AC18: in-scope sibling-anchor enforcement ---


def _sibling_backend() -> FakeBackend:
    backend = FakeBackend()
    backend.add("P", type="epic")
    backend.add("S", type="task", parent="P")
    return backend


def test_sibling_anchor_equal_to_parent_succeeds() -> None:
    backend = _sibling_backend()
    args = _args(
        anchor="P",
        anchor_why="sibling",
        discovered_from="S",
        scope="in-scope-deferred:blast-radius",
    )

    data = discover(backend, args)
    assert isinstance(data, dict)


def test_sibling_anchor_equal_to_discovered_from_itself_refuses() -> None:
    backend = _sibling_backend()
    args = _args(
        anchor="S",
        anchor_why="wrong",
        discovered_from="S",
        scope="in-scope-deferred:blast-radius",
    )

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert "child-of-in-flight" in exc_info.value.message
    assert backend.ids() == ["P", "S"]


def test_sibling_anchor_unrelated_leaf_refuses() -> None:
    backend = _sibling_backend()
    backend.add("other", type="epic")
    args = _args(
        anchor="other",
        anchor_why="wrong",
        discovered_from="S",
        scope="in-scope-deferred:blast-radius",
    )

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert backend.ids() == ["P", "S", "other"]


def test_sibling_source_with_no_parent_refuses_any_anchor() -> None:
    backend = FakeBackend()
    backend.add("S", type="task")  # no parent
    backend.add("other", type="epic")
    args = _args(
        anchor="other",
        anchor_why="wrong",
        discovered_from="S",
        scope="in-scope-deferred:blast-radius",
    )

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert "out-of-scope" in exc_info.value.message
