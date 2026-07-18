"""Envelope machinery: emit_success/emit_failure shapes, and the cli dispatch
paths that produce them (usage errors, unhandled exceptions).
"""

from __future__ import annotations

import json
from io import StringIO

from tests.fakes import ScriptedBdRunner
from workcli import PROTOCOL_VERSION
from workcli import cli as cli_module
from workcli.envelope import (
    ErrorCode,
    StepProgress,
    WorkError,
    emit_failure,
    emit_success,
    with_progress,
)


def test_emit_success_writes_ok_envelope_and_returns_zero():
    out = StringIO()

    exit_code = emit_success({"id": "x.1"}, out)

    assert exit_code == 0
    assert json.loads(out.getvalue()) == {
        "protocol": PROTOCOL_VERSION,
        "ok": True,
        "data": {"id": "x.1"},
        "error": None,
    }


def test_emit_failure_writes_error_envelope_and_returns_one():
    out = StringIO()
    error = WorkError(ErrorCode.NOT_FOUND, "no such item", detail={"id": "x.1"})

    exit_code = emit_failure(error, out)

    assert exit_code == 1
    assert json.loads(out.getvalue()) == {
        "protocol": PROTOCOL_VERSION,
        "ok": False,
        "data": None,
        "error": {"code": "E_NOT_FOUND", "message": "no such item", "detail": {"id": "x.1"}},
    }


def test_unknown_verb_yields_usage_envelope_not_argparse_stderr_dump():
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["bogus-verb"], out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"


def test_invalid_argparse_choice_yields_usage_envelope_not_argparse_stderr_dump():
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["--format", "xml"], out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"


def test_handler_success_yields_success_envelope_with_returned_data(monkeypatch):
    # A stub replaces a REGISTERED verb's handler ("show") rather than
    # inventing a new verb name -- real argparse subparsers (Task 3+) reject
    # any subcommand name that isn't wired up before VERBS is ever consulted.
    def _echo(_backend: object, _args: object) -> dict[str, str]:
        return {"id": "x.1"}

    monkeypatch.setitem(cli_module.VERBS, "show", _echo)
    out = StringIO()

    exit_code = cli_module.main(
        ["show", "x.1"], runner=ScriptedBdRunner(steps=[]), out=out, err=StringIO()
    )

    assert exit_code == 0
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is True
    assert envelope["data"] == {"id": "x.1"}


def test_handler_raising_work_error_yields_that_errors_envelope(monkeypatch):
    def _reject(_backend: object, _args: object) -> None:
        raise WorkError(ErrorCode.NOT_FOUND, "no such item", detail={"id": "x.1"})

    monkeypatch.setitem(cli_module.VERBS, "show", _reject)
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(
        ["show", "x.1"], runner=ScriptedBdRunner(steps=[]), out=out, err=err
    )

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["error"] == {
        "code": "E_NOT_FOUND",
        "message": "no such item",
        "detail": {"id": "x.1"},
    }


def test_step_progress_as_detail_shapes_the_partial_progress_record():
    progress = StepProgress(
        operation="label_mutate", steps_total=3, completed=("a",), failed="b", remaining=("c",)
    )

    assert progress.as_detail() == {
        "partial_progress": {
            "operation": "label_mutate",
            "steps_total": 3,
            "completed": ["a"],
            "failed": "b",
            "remaining": ["c"],
        }
    }


def test_with_progress_preserves_the_original_code_and_message_and_merges_detail():
    err = WorkError(ErrorCode.BACKEND_DRIFT, "bd exited weird", detail={"argv": ["x"]})
    progress = StepProgress(
        operation="sync", steps_total=2, completed=("commit",), failed="push", remaining=()
    )

    wrapped = with_progress(err, progress)

    assert wrapped.code == ErrorCode.BACKEND_DRIFT
    assert wrapped.message == "bd exited weird"
    assert wrapped.detail["argv"] == ["x"]
    assert wrapped.detail["partial_progress"] == {
        "operation": "sync",
        "steps_total": 2,
        "completed": ["commit"],
        "failed": "push",
        "remaining": [],
    }


def test_handler_exception_yields_internal_envelope_with_traceback_on_stderr(monkeypatch):
    def _boom(_backend: object, _args: object) -> None:
        raise ValueError("kaboom")

    monkeypatch.setitem(cli_module.VERBS, "show", _boom)
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(
        ["show", "x.1"], runner=ScriptedBdRunner(steps=[]), out=out, err=err
    )

    assert exit_code == 1
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "ValueError: kaboom" in err.getvalue()
