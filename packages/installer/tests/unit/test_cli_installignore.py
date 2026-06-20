"""The CLI fails fast (exit 2, clear stderr) when .installignore is absent from
the resolved repo root, rather than silently installing with exclusions off."""

from __future__ import annotations

from pathlib import Path

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
