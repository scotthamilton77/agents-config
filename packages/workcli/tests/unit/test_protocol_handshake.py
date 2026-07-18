"""Protocol handshake tests (spec §5, test-plan item 10).

`work --protocol-version` is the consumer handshake at adapter init: prgroom
and PDLC pin a major version and refuse to run against a mismatched facade.
"""

from __future__ import annotations

import json
import sys
from io import StringIO

import pytest

from tests.conftest import run_cli
from workcli import PROTOCOL_VERSION
from workcli.cli import entry, main


def test_run_cli_helper_drives_protocol_version_without_touching_the_scripted_runner():
    # No verb reaches a Backend yet (Task 2) -- an empty script proves
    # `--protocol-version` never calls the injected ScriptedBdRunner.
    exit_code, envelope, stderr_text = run_cli(["--protocol-version"], [])

    assert exit_code == 0
    assert envelope["data"] == {"protocol": PROTOCOL_VERSION}
    assert stderr_text == ""


def test_protocol_version_emits_success_envelope_with_current_protocol():
    out = StringIO()

    exit_code = main(["--protocol-version"], out=out, err=StringIO())

    stdout_text = out.getvalue()
    lines = stdout_text.splitlines()
    assert len(lines) == 1, f"expected exactly one stdout line, got: {stdout_text!r}"
    envelope = json.loads(lines[0])
    assert exit_code == 0
    assert envelope == {
        "protocol": PROTOCOL_VERSION,
        "ok": True,
        "data": {"protocol": PROTOCOL_VERSION},
        "error": None,
    }


def test_entry_exits_zero_and_writes_handshake_to_real_stdout(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["work", "--protocol-version"])

    with pytest.raises(SystemExit) as exc_info:
        entry()

    assert exc_info.value.code == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["data"] == {"protocol": PROTOCOL_VERSION}


def test_protocol_wire_value_is_pinned() -> None:
    # The serialization boundary pins the literal wire value; every other
    # test references PROTOCOL_VERSION. Bumping the protocol means updating
    # this one assertion deliberately.
    assert PROTOCOL_VERSION == "1.2"
