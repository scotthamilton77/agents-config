"""Envelope machinery: emit_success/emit_failure shapes and the cli dispatch
paths that produce them (handler success, VizError, unhandled exception).
"""

from __future__ import annotations

import json
from io import StringIO

import pytest

from tests.fakes import ScriptedGitRunner
from vizsuite import PROTOCOL_VERSION
from vizsuite import cli as cli_module
from vizsuite.envelope import ErrorCode, VizError, emit_failure, emit_success


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
    error = VizError(ErrorCode.NOT_FOUND, "no such pr", detail={"pr": 9})

    exit_code = emit_failure(error, out)

    assert exit_code == 1
    assert json.loads(out.getvalue()) == {
        "protocol": PROTOCOL_VERSION,
        "ok": False,
        "data": None,
        "error": {"code": "E_NOT_FOUND", "message": "no such pr", "detail": {"pr": 9}},
    }


def _dispatch(argv: list[str]) -> tuple[int, dict[str, object], str]:
    out, err = StringIO(), StringIO()
    exit_code = cli_module.main(argv, git_runner=ScriptedGitRunner(), out=out, err=err)
    return exit_code, json.loads(out.getvalue()), err.getvalue()


def test_handler_success_yields_success_envelope(monkeypatch: pytest.MonkeyPatch):
    def _echo(_runners: object, _args: object) -> dict[str, str]:
        return {"pr": "ok"}

    monkeypatch.setitem(cli_module.VERBS, "pr", _echo)

    exit_code, envelope, _stderr = _dispatch(["pr", "1"])

    assert exit_code == 0
    assert envelope["ok"] is True
    assert envelope["data"] == {"pr": "ok"}


def test_handler_raising_viz_error_yields_that_errors_envelope(monkeypatch: pytest.MonkeyPatch):
    def _reject(_runners: object, _args: object) -> None:
        raise VizError(ErrorCode.NOT_FOUND, "no such pr", detail={"pr": 1})

    monkeypatch.setitem(cli_module.VERBS, "pr", _reject)

    exit_code, envelope, stderr = _dispatch(["pr", "1"])

    assert exit_code == 1
    assert stderr == ""
    assert envelope["error"] == {
        "code": "E_NOT_FOUND",
        "message": "no such pr",
        "detail": {"pr": 1},
    }


def test_handler_exception_yields_internal_envelope_with_traceback(monkeypatch: pytest.MonkeyPatch):
    def _boom(_runners: object, _args: object) -> None:
        raise ValueError("kaboom")

    monkeypatch.setitem(cli_module.VERBS, "pr", _boom)

    exit_code, envelope, stderr = _dispatch(["pr", "1"])

    assert exit_code == 1
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "ValueError: kaboom" in stderr
