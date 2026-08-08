"""Protocol handshake tests.

`work --protocol-version` is the consumer handshake at adapter init: prgroom
and PDLC pin a major version and refuse to run against a mismatched facade.
"""

from __future__ import annotations

import json
import re
import sys
from io import StringIO
from pathlib import Path

import pytest

from tests.conftest import run_cli
from workcli import PROTOCOL_VERSION
from workcli.cli import entry, main


def test_run_cli_helper_drives_protocol_version_without_touching_the_scripted_runner():
    # No verb reaches a Backend yet -- an empty script proves
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
    #
    # 1.5 added `unknown_relations` to every read item and stopped emitting the
    # relationship fields it names. The removals keep the major: the fields
    # they drop were never populated on those reads, so no consumer can have
    # been reading a true value out of one, and the major is what every
    # consumer handshake pins on.
    #
    # 1.6 adds `update --set-parent`, and starts refusing two inputs `dep add`
    # used to accept: a `--type` outside bd's vocabulary, and a second parent
    # for an item that already has one. The rule scopes MAJOR to breaking
    # changes in the ENVELOPE or `data` shapes, and neither moves here -- a new
    # flag is additive, and a newly-refused input yields the same typed failure
    # envelope every other rejection already does. Both refusals only ever
    # rejected a call whose success was the defect, so no consumer had correct
    # behaviour to lose.
    #
    # 1.7 adds `E_NO_WORKSPACE`, which takes a failure that used to arrive as
    # `E_BACKEND_DRIFT` -- a directory with no tracker workspace configured.
    # The envelope and every `data` shape are untouched, so the major holds. A
    # consumer branching on the drift alarm loses only a case it could not have
    # handled correctly anyway: it was being told the facade's model of its
    # backend had broken, when what was missing was a workspace.
    assert PROTOCOL_VERSION == "1.7"


def test_the_readme_states_the_protocol_version_the_code_emits() -> None:
    # The README documents the wire contract, and it had drifted four
    # versions behind the code before anyone noticed -- exactly the class of
    # rot that a reader is trusted to catch and never does. The version is
    # quoted in prose and in every sample envelope, so this reads them all
    # rather than one blessed line: a bump that updates the headline and
    # leaves the samples stale is the same defect in a smaller form.
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    stated = set(re.findall(r'"protocol": "(\d+\.\d+)"', readme)) | set(
        re.findall(r"Protocol is `\"(\d+\.\d+)\"`", readme)
    )

    assert stated, "the README quotes no protocol version; this check has nothing to hold"
    assert stated == {PROTOCOL_VERSION}, (
        f"README states protocol {sorted(stated)}, code emits {PROTOCOL_VERSION!r}"
    )
