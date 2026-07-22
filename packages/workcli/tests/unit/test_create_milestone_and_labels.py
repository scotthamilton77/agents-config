"""Slice S2-A: mint completeness (spec 2026-07-22-workcli-completion-s2 §3).

The milestone noun closes the milestone-with-acceptance expressibility gap
(S2-D6; V2 audit rows mint (a)/(b)); additive `--label` behind the
reserved-namespace wall closes the single-call-atomicity gap (S2-D7; row
mint (c)). State assertions run against `FakeBackend`; one CLI-level test
pins the argparse wiring for the new noun.
"""

from __future__ import annotations

import json
from argparse import Namespace

import pytest

from tests.conftest import run_cli_with_runner
from tests.fake_backend import FakeBackend
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle import ORPHAN_MARKER, is_container
from workcli.lifecycle.create import create_noun
from workcli.lifecycle.transitions import claim

_OK = BdResult(returncode=0, stdout="", stderr="")


def _raise_not_configured() -> TrackLayerConfig:
    # Track gate as a no-op (criterion 17): these tests are about nouns and
    # labels, never track resolution.
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def _create_args(
    noun: str,
    *,
    title: str = "T",
    parent: str | None = None,
    orphan: bool = False,
    label: list[str] | None = None,
    acceptance: str | None = None,
) -> Namespace:
    return Namespace(
        noun=noun,
        raw=False,
        title=title,
        description=None,
        type=None,
        priority=None,
        parent=parent,
        label=label or [],
        orphan=orphan,
        spec=None,
        trivial=False,
        acceptance=acceptance,
        track=None,
        load_config=_raise_not_configured,
    )


def test_create_milestone_mints_container_with_acceptance():  # S2-A1
    backend = FakeBackend()

    data = create_noun(backend, _create_args("milestone", orphan=True, acceptance="AC1 ..."))

    assert isinstance(data, dict)
    item = backend.get(str(data["id"]))
    assert item.type == "milestone"
    assert "shape-milestone" in item.labels
    assert backend.acceptance_of(item.id) == "AC1 ..."
    assert is_container(item)
    assert ORPHAN_MARKER in backend.note_lines(item.id)


def test_create_milestone_duplicate_title_refused():  # S2-A2
    backend = FakeBackend().add("m0", title="Roadmap", type="milestone")

    with pytest.raises(WorkError) as excinfo:
        create_noun(backend, _create_args("milestone", title="Roadmap", orphan=True))

    assert excinfo.value.code is ErrorCode.DUPLICATE_TITLE
    assert backend.ids() == ["m0"]


def test_create_feat_with_user_label_is_one_call():  # S2-A3
    backend = FakeBackend().add("P", title="Parent", type="epic", labels=["shape-epic"])

    data = create_noun(backend, _create_args("feat", parent="P", label=["install"]))

    assert isinstance(data, dict)
    item = backend.get(str(data["id"]))
    # Both labels present at birth -- carried by the single create, never a
    # follow-up `work label add`.
    assert "shape-feat" in item.labels
    assert "install" in item.labels


@pytest.mark.parametrize(
    "reserved",
    [
        "shape-x",
        "track:workcli",
        "planned",
        "creating-spec",
        "impl-placeholder",
        "spec-ready",
        "parked",
    ],
)
def test_reserved_labels_refused_before_any_mutation(reserved: str):  # S2-A4
    backend = FakeBackend().add("P", title="Parent", type="epic", labels=["shape-epic"])

    with pytest.raises(WorkError) as excinfo:
        create_noun(backend, _create_args("feat", parent="P", label=[reserved]))

    assert excinfo.value.code is ErrorCode.USAGE
    assert reserved in excinfo.value.message
    assert backend.ids() == ["P"]


def test_claim_milestone_refused_as_container():  # S2-A5
    backend = FakeBackend().add("m1", type="milestone", labels=["shape-milestone"], status="open")

    with pytest.raises(WorkError) as excinfo:
        claim(backend, Namespace(id="m1"))

    assert excinfo.value.code is ErrorCode.NOT_CLAIMABLE


def test_cli_accepts_the_milestone_noun():  # S2-A1 (wiring)
    create_result = BdResult(
        returncode=0,
        stdout=json.dumps({"id": "m.1", "schema_version": 3, "title": "T"}),
        stderr="",
    )
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), BdResult(returncode=0, stdout="[]", stderr="")),
            ScriptedStep(("create",), create_result),
            ScriptedStep(("update",), _OK),  # orphan marker append
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "milestone", "--title", "T", "--orphan", "--acceptance", "AC1"],
        runner,
        config_loader=lambda _p: _raise_not_configured(),
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "m.1"}


def _required_config() -> TrackLayerConfig:
    return TrackLayerConfig(
        names=("workcli",),
        organizing_only=(),
        enforcement="required",
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
        backlog_groom_nag_days=None,
        groom_state_bead=None,
        extraction_max_track_backlog=None,
    )


def test_create_milestone_is_track_exempt_under_required_enforcement():  # S2-A1
    # Track spec §3: milestone-type beads are track-exempt and carry no
    # track:* label -- even when [tracks].enforcement = "required".
    backend = FakeBackend()
    args = _create_args("milestone", orphan=True)
    args.load_config = _required_config

    data = create_noun(backend, args)

    assert isinstance(data, dict)
    item = backend.get(str(data["id"]))
    assert not any(label.startswith("track:") for label in item.labels)


def test_create_milestone_with_explicit_track_is_refused():  # S2-A1 (inverse)
    backend = FakeBackend()
    args = _create_args("milestone", orphan=True)
    args.track = "workcli"
    args.load_config = _required_config

    with pytest.raises(WorkError) as excinfo:
        create_noun(backend, args)

    assert excinfo.value.code is ErrorCode.USAGE
    assert "track-exempt" in excinfo.value.message
    assert backend.ids() == []
