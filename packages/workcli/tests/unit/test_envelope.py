"""Envelope machinery: emit_success/emit_failure shapes, and the cli dispatch
paths that produce them (usage errors, unhandled exceptions).
"""

from __future__ import annotations

import json
from io import StringIO

from workcli import PROTOCOL_VERSION
from workcli import cli as cli_module
from workcli.envelope import ErrorCode, WorkError, emit_failure, emit_success


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
    def _echo(_args: object) -> dict[str, str]:
        return {"id": "x.1"}

    monkeypatch.setitem(cli_module.VERBS, "echo", _echo)
    out = StringIO()

    exit_code = cli_module.main(["echo"], out=out, err=StringIO())

    assert exit_code == 0
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is True
    assert envelope["data"] == {"id": "x.1"}


def test_handler_raising_work_error_yields_that_errors_envelope(monkeypatch):
    def _reject(_args: object) -> None:
        raise WorkError(ErrorCode.NOT_FOUND, "no such item", detail={"id": "x.1"})

    monkeypatch.setitem(cli_module.VERBS, "reject", _reject)
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["reject"], out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["error"] == {
        "code": "E_NOT_FOUND",
        "message": "no such item",
        "detail": {"id": "x.1"},
    }


def test_handler_exception_yields_internal_envelope_with_traceback_on_stderr(monkeypatch):
    def _boom(_args: object) -> None:
        raise ValueError("kaboom")

    monkeypatch.setitem(cli_module.VERBS, "boom", _boom)
    out = StringIO()
    err = StringIO()

    exit_code = cli_module.main(["boom"], out=out, err=err)

    assert exit_code == 1
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "ValueError: kaboom" in err.getvalue()
