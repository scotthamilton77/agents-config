"""The four lifecycle seam primitives (plan L2) + `create`'s new fields (L3).

`claim`/`set_status`/`set_type`/`set_acceptance` are thin `BdBackend`
primitives the lifecycle verb layer (bead .9.2, later tasks) composes into
guarded transitions -- each is exactly one `bd update` call, mapped through
the existing `map_bd_failure` table on a nonzero exit. `create` gains
`--acceptance`/`--deps blocks:<id>` when `CreateFields.acceptance`/
`blocked_by` are set; the transport `create --raw` path never sets them, so
its argv is unchanged (pinned as a regression here).
"""

from __future__ import annotations

import json

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.backend import BdBackend
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError
from workcli.model import CreateFields

_OK = BdResult(returncode=0, stdout="", stderr="")


def test_claim_sends_bd_update_claim():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update", "x", "--claim"), _OK)])
    backend = BdBackend(runner)

    backend.claim("x")

    assert runner.calls == [("update", "x", "--claim")]


def test_claim_raises_mapped_error_on_scripted_failure():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("update", "x", "--claim"),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.claim("x")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_set_status_sends_bd_update_status():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update", "x", "--status", "open"), _OK)])
    backend = BdBackend(runner)

    backend.set_status("x", "open")

    assert runner.calls == [("update", "x", "--status", "open")]


def test_set_status_raises_mapped_error_on_scripted_failure():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("update", "x", "--status", "open"),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.set_status("x", "open")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_set_type_sends_bd_update_type():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update", "x", "--type", "bug"), _OK)])
    backend = BdBackend(runner)

    backend.set_type("x", "bug")

    assert runner.calls == [("update", "x", "--type", "bug")]


def test_set_type_raises_mapped_error_on_scripted_failure():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("update", "x", "--type", "bug"),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.set_type("x", "bug")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def test_set_acceptance_sends_bd_update_acceptance():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("update", "x", "--acceptance", "AC"), _OK)])
    backend = BdBackend(runner)

    backend.set_acceptance("x", "AC")

    assert runner.calls == [("update", "x", "--acceptance", "AC")]


def test_set_acceptance_raises_mapped_error_on_scripted_failure():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("update", "x", "--acceptance", "AC"),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x"\n'),
            )
        ]
    )
    backend = BdBackend(runner)

    try:
        backend.set_acceptance("x", "AC")
        raise AssertionError("expected WorkError")
    except WorkError as error:
        assert error.code == ErrorCode.NOT_FOUND


def _create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


def test_create_appends_acceptance_and_blocked_by_deps_when_set():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("create",), _create_result("x.9"))])
    backend = BdBackend(runner)

    backend.create(CreateFields(title="T", acceptance="A", blocked_by="d1"))

    assert runner.calls == [
        ("create", "--json", "--title", "T", "--acceptance", "A", "--deps", "blocks:d1")
    ]


def test_create_without_acceptance_or_blocked_by_omits_both_flags():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("create",), _create_result("x.9"))])
    backend = BdBackend(runner)

    backend.create(CreateFields(title="T"))

    assert runner.calls == [("create", "--json", "--title", "T")]
    assert "--acceptance" not in runner.calls[0]
    assert "--deps" not in runner.calls[0]
