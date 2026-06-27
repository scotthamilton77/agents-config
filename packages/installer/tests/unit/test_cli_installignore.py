"""The CLI fails fast (exit 2, clear stderr) when .installignore is absent or
unparseable at the resolved repo root, rather than silently installing with
exclusions off or crashing with a traceback."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from installer.cli import main


def test_missing_manifest_aborts_with_exit_2(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    # tmp_path is a repo root with NO .installignore. Point main() at it and a
    # throwaway HOME so nothing real is touched.
    home = tmp_path / "home"
    home.mkdir()

    rc = main(["--yes"], home=home, repo_root=tmp_path)

    assert rc == 2
    err = capsys.readouterr().err
    assert ".installignore not found" in err


def test_non_utf8_manifest_aborts_with_exit_2(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    # A present-but-non-UTF-8 manifest raises UnicodeDecodeError (a ValueError,
    # not an OSError). The CLI must still fail fast (exit 2) with a clean message,
    # not crash with an uncaught traceback.
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".installignore").write_bytes(b"\xff\xfe\x00bad bytes\n")

    rc = main(["--yes"], home=home, repo_root=tmp_path)

    assert rc == 2
    err = capsys.readouterr().err
    assert "installer:" in err


def test_unreadable_manifest_aborts_with_exit_2(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    # A present-but-unreadable manifest (chmod 000) raises PermissionError, an
    # OSError subclass. cli.main catches (OSError, UnicodeDecodeError) -> exit 2;
    # this pins that the except is broad enough to include PermissionError, not
    # just the missing-file FileNotFoundError. Skipped where chmod cannot make
    # the file unreadable (root, or a filesystem that ignores mode bits).
    home = tmp_path / "home"
    home.mkdir()
    manifest = tmp_path / ".installignore"
    manifest.write_text("AGENTS.md\n", encoding="utf-8")
    manifest.chmod(0o000)
    try:
        if os.access(manifest, os.R_OK):
            pytest.skip("manifest still readable after chmod (root or mode-less fs)")
        rc = main(["--yes"], home=home, repo_root=tmp_path)
        assert rc == 2
        assert "installer:" in capsys.readouterr().err
    finally:
        manifest.chmod(0o644)


def test_dump_stage_missing_manifest_aborts_before_dump(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    # The up-front manifest load precedes the --dump-stage branch, so a missing
    # manifest aborts (exit 2) BEFORE anything is staged or written — pinning that
    # ordering rather than relying on the transitive exit-2 coverage. The output
    # path must not be created.
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "stage-out"

    rc = main(["--dump-stage", str(out), "--tools=claude"], home=home, repo_root=tmp_path)

    assert rc == 2
    assert ".installignore not found" in capsys.readouterr().err
    assert not out.exists()
