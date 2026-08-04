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

import dataclasses
import json
from argparse import Namespace
from io import StringIO

import pytest

from tests.conftest import run_cli, run_cli_with_runner
from tests.fake_backend import FakeBackend, ReadOnlyFakeBackend
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli import cli as cli_module
from workcli.adapters.bd.runner import BdResult
from workcli.backend import Capabilities, DepOp, ReadySupport, SyncSupport
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.discover import discover
from workcli.model import Item


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
        backlog_groom_nag_days=None,
        groom_state_item=None,
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


def test_success_payload_matches_the_complete_data_shape_exactly() -> None:
    """The whole `data` payload for a successful discover, not a subset --
    catches a field dropped, renamed, or added that a narrower assertion
    would miss."""
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args()

    data = discover(backend, args)

    assert isinstance(data, dict)
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    assert data == {
        "item": {"id": new_id, "title": "New discovery", "track": None},
        "edges": {"parent": "epic-1", "discovered_from": "src-1"},
        "triage": {"scope": "out-of-scope", "priority": "P2", "anchor": "epic-1"},
        "manifest_row": {
            "item": "New discovery",
            "scope": "out-of-scope",
            "lands_in": "epic-1",
            "tracked_item": new_id,
            "priority_why": "P2 — reason",
        },
        "remaining_work": False,
        "warnings": [],
    }


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


# --- recovery contract: post-create track read fails -> detail.created_id set ---
# (codex review finding on PR #327: backend.get(new_id) for track derivation is a
# third post-create step not covered by the original enumeration; it must carry
# created_id on failure exactly like the edge-add and orphan-marker seams do.)


class _GetFailingBackend(FakeBackend):
    def get(self, item_id: str) -> Item:
        if item_id not in ("epic-1", "src-1"):
            raise WorkError(ErrorCode.BACKEND_DRIFT, "boom", detail={})
        return super().get(item_id)


def test_post_create_track_read_failure_surfaces_created_id_for_replay() -> None:
    backend = _GetFailingBackend()
    backend.add("epic-1", type="epic", labels=["shape-epic"])
    backend.add("src-1", type="task", parent="epic-1")
    args = _out_of_scope_args()

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.BACKEND_DRIFT
    assert exc_info.value.detail["created_id"] in backend.ids()
    assert exc_info.value.detail["created_id"] not in ("epic-1", "src-1")


# --- AC11: --noun outside the leaf set -> E_USAGE (leaf nouns only) ---


@pytest.mark.parametrize("noun", ["spec", "epic", "milestone"])
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


# --- accepted argument-shape aliases (--noun 'bug', bare --priority), and
# single-pass reporting when both --noun and --priority are malformed. ---


def test_noun_alias_bug_resolves_to_canonical_bugfix_template() -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(noun="bug")

    data = discover(backend, args)

    assert isinstance(data, dict)
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    assert backend.get(new_id).type == "bug"
    assert "shape-bugfix" in backend.labels(new_id)


@pytest.mark.parametrize("digit", ["0", "1", "2", "3", "4"])
def test_bare_priority_normalizes_to_canonical_p_notation(digit: str) -> None:
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(priority=digit)
    expected = f"P{digit}"

    data = discover(backend, args)

    assert isinstance(data, dict)
    assert data["triage"]["priority"] == expected  # type: ignore[index]
    new_id = data["item"]["id"]  # type: ignore[index]
    assert isinstance(new_id, str)
    assert backend.get(new_id).priority == expected
    assert f"- Priority: {expected} — reason" in backend.get(new_id).description


def test_alias_and_canonical_forms_produce_byte_identical_stored_records() -> None:
    backend_alias = _backend_with_epic_anchor()
    backend_canon = _backend_with_epic_anchor()

    data_alias = discover(backend_alias, _out_of_scope_args(noun="bug", priority="2"))
    data_canon = discover(backend_canon, _out_of_scope_args(noun="bugfix", priority="P2"))

    assert isinstance(data_alias, dict)
    assert isinstance(data_canon, dict)
    id_alias = data_alias["item"]["id"]  # type: ignore[index]
    id_canon = data_canon["item"]["id"]  # type: ignore[index]
    assert isinstance(id_alias, str)
    assert isinstance(id_canon, str)
    item_alias = backend_alias.get(id_alias)
    item_canon = backend_canon.get(id_canon)

    # Byte-identical field for field -- title, type, status, priority,
    # labels, parent, description, notes, children, and dep edges -- except
    # each backend's own assigned id.
    assert dataclasses.replace(item_alias, id="") == dataclasses.replace(item_canon, id="")
    # The discovered-from provenance edge, named explicitly.
    assert item_alias.deps == item_canon.deps


def test_unknown_noun_alone_raises_single_field_usage_error() -> None:
    """A single bad --noun still raises its own (non-combined) error unchanged:
    the exact code, message, and detail, not just a fragment of any of them --
    AC5 pins full error identity, not "close enough"."""
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(noun="widget")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE
    assert exc_info.value.message == (
        "invalid choice: 'widget' (choose from spike, chore, decision, feat, bugfix)"
    )
    assert exc_info.value.detail == {"field": "noun"}
    assert backend.ids() == ["epic-1", "src-1"]


def test_malformed_noun_and_priority_together_are_both_reported_from_one_call() -> None:
    """Neither 'widget' (not a noun or a known alias) nor 'P9' (out of
    P0-P4, even after bare-digit normalization) is individually acceptable;
    both are named from this single invocation. The top-level code is
    `E_TRIAGE_INCOMPLETE`, so a caller grepping for a triage rejection
    still finds one, even though the noun failure alone is `E_USAGE`.
    """
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(noun="widget", priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert "widget" in exc_info.value.message
    assert "P0" in exc_info.value.message and "P4" in exc_info.value.message
    errors = exc_info.value.detail["errors"]
    assert isinstance(errors, list)
    fields = {entry["field"] for entry in errors}  # type: ignore[union-attr]
    assert fields == {"noun", "priority"}
    # Every individual field's own code still survives in detail.errors,
    # even though the top-level code is the folded one above.
    codes_by_field = {entry["field"]: entry["code"] for entry in errors}  # type: ignore[union-attr]
    assert codes_by_field == {
        "noun": str(ErrorCode.USAGE),
        "priority": str(ErrorCode.TRIAGE_INCOMPLETE),
    }
    assert backend.ids() == ["epic-1", "src-1"]


def test_unknown_noun_alone_touches_no_backend_mutation() -> None:
    """`ReadOnlyFakeBackend` raises on every mutator, so a malformed --noun
    reaching `create_noun` fails loudly here. The backend is left empty --
    noun validation runs before any read too, so nothing needs seeding.
    """
    backend = ReadOnlyFakeBackend()
    args = _out_of_scope_args(noun="widget")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE


def test_malformed_noun_and_priority_together_touches_no_backend_mutation() -> None:
    """Same mechanical proof as above, for the combined-failure path."""
    backend = ReadOnlyFakeBackend()
    args = _out_of_scope_args(noun="widget", priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE


def test_priority_only_failure_still_returns_triage_incomplete_alone() -> None:
    """A triage-semantic failure alone returns `E_TRIAGE_INCOMPLETE` with its
    own field and message -- matches
    `test_invalid_priority_names_field_and_accepted_range` field for field.
    """
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.message == "priority must be one of P0-P4, got 'P9'"
    assert exc_info.value.detail == {"field": "priority"}


def test_placement_usage_precedes_the_noun_priority_aggregate() -> None:
    """Placement (pure arg-shape, `E_USAGE`) fires before the noun/priority
    aggregate: the aggregate must never move a pure well-formedness check
    behind it.
    """
    backend = _backend_with_epic_anchor()
    args = _args(anchor=None, orphan=False, priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE
    assert "anchor" in exc_info.value.message and "orphan" in exc_info.value.message


def test_scope_precedes_the_noun_priority_aggregate() -> None:
    """Bad --scope with bad --priority together surfaces the scope
    rejection, not the priority one: scope fires before the aggregate.
    """
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(scope="sideways", priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "scope"


def test_placement_usage_precedes_the_noun_priority_aggregate_for_a_bad_noun() -> None:
    """Same precedence proof as the bad-priority case above, exercising the
    noun side of the aggregate instead: the whole aggregate sits behind
    placement and scope, not just --priority's side of it.
    """
    backend = _backend_with_epic_anchor()
    args = _args(anchor=None, orphan=False, noun="widget")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE
    assert "anchor" in exc_info.value.message and "orphan" in exc_info.value.message


def test_scope_precedes_the_noun_priority_aggregate_for_a_bad_noun() -> None:
    """Same precedence proof as the bad-priority case above, but exercising
    the noun side of the aggregate."""
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(scope="sideways", noun="widget")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.TRIAGE_INCOMPLETE
    assert exc_info.value.detail["field"] == "scope"


def test_placement_usage_both_shape_precedes_the_noun_priority_aggregate() -> None:
    """The 'both' placement shape (--anchor and --orphan together) must also
    fire before the noun/priority aggregate -- the existing placement
    precedence tests above only cover the 'neither' shape.
    """
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(orphan=True, escalation_why="none fits", priority="P9")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE
    assert "anchor" in exc_info.value.message and "orphan" in exc_info.value.message


def test_placement_usage_both_shape_precedes_the_noun_priority_aggregate_for_a_bad_noun() -> None:
    """Same 'both' placement shape proof as above, exercising the noun side
    of the aggregate."""
    backend = _backend_with_epic_anchor()
    args = _out_of_scope_args(orphan=True, escalation_why="none fits", noun="widget")

    with pytest.raises(WorkError) as exc_info:
        discover(backend, args)

    assert exc_info.value.code is ErrorCode.USAGE
    assert "anchor" in exc_info.value.message and "orphan" in exc_info.value.message


def test_malformed_noun_and_priority_together_via_cli_one_envelope() -> None:
    """Same double-failure, driven through the CLI -- top-level code is
    `E_TRIAGE_INCOMPLETE` (see the unit-level test's docstring above for
    why)."""
    exit_code, envelope, _ = run_cli(
        [
            "discover",
            "--noun",
            "widget",
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
            "P9",
            "--priority-why",
            "x",
        ],
        steps=[],
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.TRIAGE_INCOMPLETE)
    detail = error["detail"]
    assert isinstance(detail, dict)
    errors = detail["errors"]
    assert isinstance(errors, list)
    fields = {entry["field"] for entry in errors}  # type: ignore[union-attr]
    assert fields == {"noun", "priority"}


def test_previously_rejected_shapes_now_succeed_via_cli() -> None:
    """--noun bug and --priority 2 together succeed, driven through the CLI."""

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
            ScriptedStep(("show", "new-1", "--json"), _show_result("new-1", "bug")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        [
            "discover",
            "--noun",
            "bug",
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
            "2",
            "--priority-why",
            "hurts overnight",
        ],
        runner,
        config_loader=_not_found_config_loader,
    )

    assert exit_code == 0
    assert envelope["ok"] is True
    create_index = next(i for i, call in enumerate(runner.calls) if call[0] == "create")
    create_call = runner.calls[create_index]
    assert "--type" in create_call and "bug" in create_call
    assert "--priority" in create_call and "P2" in create_call


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
