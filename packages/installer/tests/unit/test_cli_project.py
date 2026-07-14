"""Tests for the --project/--profiles guard rails (Task 7 of the S2 plan).

This version adds only the argparse flags and two early validation guards in
_run(); no project-scoped install behavior exists yet. Each test pins one
guard's coded decision (exit code + message), not argparse machinery."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.cli import main
from installer.core.io_port import ScriptedIO

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _write_installignore(repo: Path) -> None:
    """Mirror the real repo-root .installignore so cli.main's up-front fail-fast
    load finds it. Copied from the REAL manifest (not retyped) so it cannot
    drift from it. See test_cli_smoke._write_installignore."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".installignore").write_text(
        (_REPO_ROOT / ".installignore").read_text(encoding="utf-8"), encoding="utf-8"
    )


def _hermetic_repo(tmp_path: Path) -> Path:
    """A minimal source repo: one shared template so a Claude plan is
    non-empty, plus empty tool-root dirs the adapters expect. Mirrors
    test_cli_smoke._hermetic_repo."""
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"shared laws\n")
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)
    _write_installignore(repo)
    return repo


def test_profiles_without_project_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        ["--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=_hermetic_repo(tmp_path),
    )
    assert rc == 2
    assert "--profiles requires --project" in capsys.readouterr().err


def test_project_path_missing_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["--project", str(tmp_path / "nope"), "--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=_hermetic_repo(tmp_path),
    )
    assert rc == 2
    assert "nope" in capsys.readouterr().err


def _hermetic_repo_with_profiles(tmp_path: Path) -> Path:
    """``_hermetic_repo`` plus the real ``profiles.toml`` (needed to resolve
    ``beads-kit``) and the beads kit content the tracer installs."""
    repo = _hermetic_repo(tmp_path)
    (repo / "profiles.toml").write_text(
        (_REPO_ROOT / "profiles.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return repo


def test_project_beads_kit_writes_prime_and_receipt(tmp_path: Path) -> None:
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (project / ".beads" / "PRIME.md").read_bytes() == b"beads prime\n"
    receipt = project / ".agents-config" / "install-receipt.json"
    assert receipt.is_file()
    assert "kit:beads" in receipt.read_text()
    assert not (tmp_path / ".beads").exists()


def test_user_install_byte_identical_through_resolver(tmp_path: Path) -> None:
    """A plain user install (no --project) must stay byte-identical once
    main()'s resolver pass (S2 Task 9) is wired in ahead of install_pipeline.

    An empty CLI profile selection resolves to the "full" profile
    (`include = ["**"]` in profiles.toml), so every staged item matches and
    filter_plan_to_scope narrows each tool plan to itself — a no-op. This
    pins that no-op end to end against the real repo-root profiles.toml
    (needed for the resolver to run at all)."""
    repo = _hermetic_repo_with_profiles(tmp_path)

    rc = main(
        ["--tools=claude", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (tmp_path / ".claude" / "INSTRUCTIONS.md").read_bytes() == b"shared laws\n"
