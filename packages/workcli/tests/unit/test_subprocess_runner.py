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


def test_run_uses_injected_bd_binary_cwd_and_env(tmp_path, monkeypatch):
    # A fake bd that proves all three injected params reached subprocess.run:
    # it echoes its own cwd and a custom env var.
    fake_dir = tmp_path / "bin"
    fake_dir.mkdir()
    fake_bd = fake_dir / "mybd"
    fake_bd.write_text('#!/bin/sh\necho "cwd=$(pwd)"\necho "marker=$WORKCLI_ITEST_MARKER"\n')
    fake_bd.chmod(fake_bd.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "work"
    workdir.mkdir()
    # Ensure PATH does NOT contain a `bd`, proving bd_binary (absolute) is used.
    monkeypatch.setenv("PATH", "/nonexistent")

    runner = SubprocessBdRunner(
        bd_binary=str(fake_bd),
        cwd=str(workdir),
        env={"WORKCLI_ITEST_MARKER": "42", "PATH": "/nonexistent"},
    )
    result = runner.run(["show", "--json"])

    assert result.returncode == 0
    assert f"cwd={os.path.realpath(workdir)}" in result.stdout
    assert "marker=42" in result.stdout


def test_run_defaults_are_unchanged(tmp_path, monkeypatch):
    # Default construction must remain byte-identical to today: binary "bd",
    # inherited cwd/env. Prove by putting a fake `bd` on PATH and NOT passing
    # any injected params.
    _write_fake_bd(tmp_path, 'echo "default-path-bd"\n')
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)

    result = SubprocessBdRunner().run(["list"])

    assert result.returncode == 0
    assert result.stdout == "default-path-bd\n"
