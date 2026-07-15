"""Tests for the --project/--profiles guard rails (Task 7 of the S2 plan).

This version adds only the argparse flags and two early validation guards in
_run(); no project-scoped install behavior exists yet. Each test pins one
guard's coded decision (exit code + message), not argparse machinery."""

from __future__ import annotations

import json
import tomllib
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


def test_project_no_profiles_no_persisted_config_errors_no_implicit_full(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No --profiles and no project-config.toml: still the exit-2 guard."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "no implicit full" in err


def test_project_persisted_profiles_resolved_without_explicit_flag(tmp_path: Path) -> None:
    """No --profiles, but <project>/project-config.toml persists a selection:
    that selection resolves and installs, exactly as if passed via --profiles."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "project-config.toml").write_text(
        '[install]\nprofiles = ["beads-kit"]\n', encoding="utf-8"
    )

    rc = main(
        ["--project", str(project), "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (project / ".beads" / "PRIME.md").read_bytes() == b"beads prime\n"


def test_project_persisted_empty_profiles_list_is_not_implicit_full(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A persisted but EMPTY ``[install] profiles = []`` must NOT be read as an
    implicit "full" selection — it hits the no-implicit-full guard, same as no
    persisted config at all. (resolve() treats an empty selection as the full
    profile, so this guards against a silent full project install.)"""
    repo = _hermetic_repo_with_profiles(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "project-config.toml").write_text("[install]\nprofiles = []\n", encoding="utf-8")

    rc = main(
        ["--project", str(project), "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 2
    assert "no implicit full" in capsys.readouterr().err
    assert not (project / ".beads").exists()


def test_project_unknown_profile_exits_cleanly_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown --profiles name surfaces resolve()'s ProfilesError as a clean
    exit-2 diagnostic, not an uncaught traceback."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=does-not-exist", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 2
    assert capsys.readouterr().err.startswith("installer:")


def test_project_malformed_persisted_config_exits_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A persisted ``[install] profiles`` that is not a list of strings exits 2
    with a diagnostic instead of raising ValueError out of read_project_profiles."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "project-config.toml").write_text("[install]\nprofiles = 42\n", encoding="utf-8")

    rc = main(
        ["--project", str(project), "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 2
    assert "malformed project-config.toml" in capsys.readouterr().err


def test_project_profiles_trailing_comma_rejected_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stray trailing comma in --profiles is rejected with a clean exit-2
    diagnostic, not a confusing downstream 'unknown empty profile' error."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=beads-kit,", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 2
    assert "empty profile name" in capsys.readouterr().err
    assert not (project / ".beads").exists()


def test_project_corrupt_receipt_left_untouched_install_proceeds(tmp_path: Path) -> None:
    """A CORRUPT project receipt fails closed (mirrors the user path): the install
    still proceeds, but the receipt is NOT overwritten — overwriting would erase
    the record of previously-installed paths and defeat future --prune."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()
    receipt_path = project / ".agents-config" / "install-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrity": "sha256:deadbeef",  # forged digest -> read_receipt CORRUPT
                "roots": [".beads"],
                "entries": [
                    {
                        "path": ".beads/STALE.md",
                        "owner": "kit:beads",
                        "root": ".beads",
                        "kind": "file",
                        "sha256": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = receipt_path.read_bytes()

    io = ScriptedIO(interactive=False)
    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=io,
        repo_root=repo,
    )

    assert rc == 0
    assert (project / ".beads" / "PRIME.md").read_bytes() == b"beads prime\n"  # install proceeded
    assert receipt_path.read_bytes() == before  # corrupt receipt left byte-for-byte untouched
    assert any("unreadable" in e.message for e in io.transcript)


def _hermetic_repo_with_project_tool_profile(tmp_path: Path) -> Path:
    """``_hermetic_repo`` plus a hermetic ``profiles.toml`` (independent of the
    real repo-root one — no beads kit needed) carrying one profile,
    ``proj-skill``, that routes the shared ``skills/foo`` namespace item to
    project scope via an explicit include-entry override. Also seeds a real
    ``skills/foo`` shared skill dir so it stages as a ``DIR`` item for every
    tool (shared namespaces stage for all tools regardless of
    ``scoped_namespaces()`` — see ``core/staging.py`` Phase 2)."""
    repo = _hermetic_repo(tmp_path)
    skill_dir = repo / "src" / "user" / ".agents" / "skills" / "foo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"foo skill\n")
    (repo / "profiles.toml").write_text(
        "schema = 1\n"
        "\n"
        "[scopes]\n"
        '"instructions" = "user"\n'
        '"settings" = "user"\n'
        '"skills/**" = "user"\n'
        '"agents/**" = "user"\n'
        '"rules/**" = "user"\n'
        "\n"
        "[profiles.proj-skill]\n"
        'include = [{select="skills/foo", scope="project"}]\n',
        encoding="utf-8",
    )
    return repo


def test_project_tool_ref_writes_under_project_dest(tmp_path: Path) -> None:
    """A project-scoped tool ref (skills/foo, scope="project") for the sole
    active tool (claude, whose project_namespaces() includes "skills") writes
    under <project>/.claude/skills/foo and is recorded in the receipt under
    the claude dest root — the tool tail, not the kit path."""
    repo = _hermetic_repo_with_project_tool_profile(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=proj-skill", "--tools=claude", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (project / ".claude" / "skills" / "foo" / "SKILL.md").read_bytes() == b"foo skill\n"
    receipt = project / ".agents-config" / "install-receipt.json"
    assert receipt.is_file()
    assert "claude" in receipt.read_text()
    # Never wrote to user space.
    assert not (tmp_path / ".claude").exists()


def test_project_tool_ref_outside_project_namespaces_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same profile selected for codex — whose project_namespaces() is ()
    — must fail validation naming the tool and namespace, never silently
    install or silently drop the ref."""
    repo = _hermetic_repo_with_project_tool_profile(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=proj-skill", "--tools=codex", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "codex" in err
    assert "skills" in err
    assert not (project / ".codex").exists()


def test_project_kit_selector_scoped_to_user_errors_pre_resolve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kits are project-only. A profile that routes a kit selector to a
    non-project scope must fail BEFORE resolve() runs — resolve() would
    silently drop the kit ref into the USER scope's counts, discarding its
    identity, so only a pre-resolve check can name the offending selector."""
    repo = _hermetic_repo(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    (repo / "profiles.toml").write_text(
        "schema = 1\n"
        "\n"
        "[scopes]\n"
        '"instructions" = "user"\n'
        '"settings" = "user"\n'
        "\n"
        "[profiles.bad-kit-scope]\n"
        'include = [{select="kits/beads/**", scope="user"}, {select="**", scope="user"}]\n',
        encoding="utf-8",
    )
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=bad-kit-scope", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "kits/beads/**" in err
    assert not (project / ".beads").exists()
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


def test_project_install_persists_profiles_then_bare_rerun_reinstalls(tmp_path: Path) -> None:
    """A successful ``--project p --profiles=beads-kit`` install writes
    <p>/project-config.toml's [install].profiles; a subsequent BARE
    ``--project p`` (no --profiles) then reads that persisted selection
    (Task 10's read_project_profiles path) and reinstalls beads-kit."""
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

    config_path = project / "project-config.toml"
    assert config_path.is_file()
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["install"]["profiles"] == ["beads-kit"]

    (project / ".beads" / "PRIME.md").unlink()

    rc2 = main(
        ["--project", str(project), "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc2 == 0
    assert (project / ".beads" / "PRIME.md").read_bytes() == b"beads prime\n"


def test_project_dry_run_writes_no_project_config_or_receipt(tmp_path: Path) -> None:
    """``--project p --profiles=beads-kit --dry-run`` must not write
    project-config.toml or the receipt — dry-run is a no-op on disk."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes", "--dry-run"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert not (project / "project-config.toml").exists()
    assert not (project / ".agents-config" / "install-receipt.json").exists()


def _hermetic_repo_with_two_kits(tmp_path: Path) -> Path:
    """``_hermetic_repo`` plus a hermetic ``profiles.toml`` carrying two
    project-scoped kits — ``beads`` and ``other`` — each behind its own
    profile, so a run can select one while the other's prior receipt entry
    becomes prunable."""
    repo = _hermetic_repo(tmp_path)
    beads_kit = repo / "src" / "kits" / "beads" / ".beads"
    beads_kit.mkdir(parents=True)
    (beads_kit / "PRIME.md").write_bytes(b"beads prime\n")
    other_kit = repo / "src" / "kits" / "other" / ".other"
    other_kit.mkdir(parents=True)
    (other_kit / "OTHER.md").write_bytes(b"other kit\n")
    (repo / "profiles.toml").write_text(
        "schema = 1\n"
        "\n"
        "[scopes]\n"
        '"instructions" = "user"\n'
        '"settings" = "user"\n'
        '"kits/**" = "project"\n'
        "\n"
        "[profiles.beads-kit]\n"
        'include = ["kits/beads/**"]\n'
        "\n"
        "[profiles.other-kit]\n"
        'include = ["kits/other/**"]\n',
        encoding="utf-8",
    )
    return repo


def test_project_prune_keeps_selected_kit_removes_deselected_kit_orphan(
    tmp_path: Path,
) -> None:
    """A still-selected kit's files survive --prune; a deselected kit's prior
    receipt entry becomes an orphan and is removed. User space untouched."""
    repo = _hermetic_repo_with_two_kits(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()

    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc == 0
    prime = project / ".beads" / "PRIME.md"
    assert prime.read_bytes() == b"beads prime\n"

    # Still selected, --prune: PRIME.md must NOT be deleted.
    rc2 = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes", "--prune"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc2 == 0
    assert prime.is_file()

    # Deselect beads-kit in favor of other-kit, --prune: PRIME.md orphaned and removed.
    rc3 = main(
        ["--project", str(project), "--profiles=other-kit", "--yes", "--prune"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc3 == 0
    assert not prime.exists()
    assert (project / ".other" / "OTHER.md").read_bytes() == b"other kit\n"

    # User space (home) never touched.
    assert not (tmp_path / ".beads").exists()
    assert not (tmp_path / ".agents-config").exists()


def test_project_install_preserves_other_tables_in_project_config(tmp_path: Path) -> None:
    """A pre-existing project-config.toml with an unrelated [merge-policy]
    table must keep that table intact after ``--project p --profiles=beads-kit``
    sets [install].profiles."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()
    config_path = project / "project-config.toml"
    config_path.write_text('[merge-policy]\nmerge-authorization = "explicit"\n', encoding="utf-8")

    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert data["merge-policy"] == {"merge-authorization": "explicit"}
    assert data["install"]["profiles"] == ["beads-kit"]


def _suggestion_lines(io: ScriptedIO) -> list[str]:
    return [
        e.message
        for e in io.transcript
        if e.channel == "info" and "looks like a project" in e.message
    ]


def test_user_run_with_beads_dir_in_cwd_suggests_project_install(tmp_path: Path) -> None:
    """A USER run (no --project) whose cwd contains a .beads/ dir prints
    exactly one suggestion line pointing at --project ."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    cwd = tmp_path / "proj"
    (cwd / ".beads").mkdir(parents=True)
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--tools=claude", "--yes"],
        home=tmp_path,
        io=io,
        repo_root=repo,
        cwd=cwd,
    )

    assert rc == 0
    assert len(_suggestion_lines(io)) == 1


def test_user_run_with_plain_cwd_suggests_nothing(tmp_path: Path) -> None:
    """A USER run whose cwd has neither .beads/ nor a project-config.toml
    [install] table prints no suggestion line."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    cwd = tmp_path / "plain"
    cwd.mkdir()
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--tools=claude", "--yes"],
        home=tmp_path,
        io=io,
        repo_root=repo,
        cwd=cwd,
    )

    assert rc == 0
    assert _suggestion_lines(io) == []


def test_project_run_never_suggests_even_with_beads_dir_in_cwd(tmp_path: Path) -> None:
    """A --project run prints no suggestion line, even when cwd (a DIFFERENT
    directory than the project target) looks like a project."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()
    cwd = tmp_path / "cwd_looks_like_project"
    (cwd / ".beads").mkdir(parents=True)
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--yes"],
        home=tmp_path,
        io=io,
        repo_root=repo,
        cwd=cwd,
    )

    assert rc == 0
    assert _suggestion_lines(io) == []


def test_project_dump_stage_lists_kit_refs_and_writes_nothing(tmp_path: Path) -> None:
    """``--project p --profiles=beads-kit --dump-stage <dir>`` renders the
    resolved PROJECT plan (kit refs listed as ``kit:<name>  <dest_relpath>``)
    and returns 0 WITHOUT installing kit content or writing a receipt — a dump
    is read-only, even under --project."""
    repo = _hermetic_repo_with_profiles(tmp_path)
    kit = repo / "src" / "kits" / "beads" / ".beads"
    kit.mkdir(parents=True)
    (kit / "PRIME.md").write_bytes(b"beads prime\n")
    project = tmp_path / "proj"
    project.mkdir()
    out = tmp_path / "dump"
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--project", str(project), "--profiles=beads-kit", "--dump-stage", str(out)],
        home=tmp_path,
        io=io,
        repo_root=repo,
    )

    assert rc == 0
    kit_lines = [e.message for e in io.transcript if e.channel == "info" and "kit:" in e.message]
    assert kit_lines == ["kit:beads  .beads/PRIME.md"]
    assert not (project / ".beads" / "PRIME.md").exists()
    assert not (project / ".agents-config" / "install-receipt.json").exists()
