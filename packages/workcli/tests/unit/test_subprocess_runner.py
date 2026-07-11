"""SubprocessBdRunner: the one real I/O boundary in workcli.

Every contract test elsewhere drives a `ScriptedBdRunner` fake instead --
this file is the sole place that proves the subprocess wiring itself
(argv prefix, captured stdout/stderr, returncode) actually works, using a
tiny substitute `bd` script on PATH rather than the real binary.
"""

from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path

from workcli.adapters.bd.runner import SubprocessBdRunner


def _write_fake_bd(tmp_path: Path, script: str) -> None:
    fake_bd = tmp_path / "bd"
    fake_bd.write_text(f"#!/bin/sh\n{textwrap.dedent(script)}")
    fake_bd.chmod(fake_bd.stat().st_mode | stat.S_IEXEC)


def test_run_invokes_bd_with_the_given_args_and_captures_the_full_result(tmp_path, monkeypatch):
    _write_fake_bd(
        tmp_path,
        """\
        echo "args: $*"
        echo "warning: something" 1>&2
        exit 3
        """,
    )
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)

    result = SubprocessBdRunner().run(["show", "x.1", "--json"])

    assert result.returncode == 3
    assert result.stdout == "args: show x.1 --json\n"
    assert result.stderr == "warning: something\n"
