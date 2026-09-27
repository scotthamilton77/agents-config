"""Where the installer deploys skills for the gemini tool, driven end to end through main().

Antigravity CLI replaced Gemini CLI and reuses ``~/.gemini``, but it discovers
global skills only under ``~/.gemini/config/skills/``. The rest of
``~/.gemini/config/`` is Antigravity's own state. These tests run the real
install and prune pipelines against a hermetic repo and a temporary home, with
every seam main() takes injected except ``cli_deploy``, which a non-real home
already skips.
"""

from __future__ import annotations

from pathlib import Path

from installer.cli import main
from installer.core.io_port import ScriptedIO
from installer.core.receipt import Receipt, ReceiptEntry, dir_content_digest
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RECEIPT = Path(".config/agents-config/install-receipt.json")


def _admitted(body: bytes) -> bytes:
    """Wrap ``body`` in front matter carrying a complete admission record, so the
    admission gate deploys it."""
    return (
        b"---\n"
        b"name: fixture\n"
        b"description: a fixture artifact\n"
        b"admission:\n"
        b"  provides: a fixture for the deploy location\n"
        b"  cost: one staged item\n"
        b"  remove_when: the fixture is no longer needed\n"
        b"---\n" + body
    )


def _repo(tmp_path: Path) -> Path:
    """A hermetic source repo with two admitted shared skills, one admitted shared
    rule and a Gemini instruction template."""
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    for name in ("foo", "bar"):
        (shared / "skills" / name).mkdir(parents=True)
        (shared / "skills" / name / "SKILL.md").write_bytes(_admitted(name.encode() + b"\n"))
    (shared / "rules").mkdir(parents=True)
    (shared / "rules" / "r.md").write_bytes(_admitted(b"a rule\n"))
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)
    (repo / "src" / "user" / ".gemini" / "GEMINI.md.template").write_bytes(b"gemini laws\n")
    for manifest in (".installignore", "profiles.toml"):
        (repo / manifest).write_bytes((_REPO_ROOT / manifest).read_bytes())
    return repo


def _run(argv: list[str], *, tmp_path: Path, repo: Path, home: Path) -> int:
    return main(argv, home=home, io=ScriptedIO(interactive=False), repo_root=repo, cwd=tmp_path)


def _receipt_paths(home: Path) -> set[Path]:
    result = read_receipt(home / _RECEIPT)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    return {e.path for e in result.receipt.entries}


def _tree(root: Path) -> dict[Path, tuple[bytes, int] | None]:
    """Every path under ``root``, mapped to a file's bytes and mtime, or None for a
    directory."""
    return {
        p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) if p.is_file() else None
        for p in root.rglob("*")
    }


def test_gemini_skills_deploy_under_config_skills(tmp_path: Path) -> None:
    """
    Given two admitted shared skills
    When a plain install targets every tool
    Then each Gemini copy lands at ~/.gemini/config/skills/<name>/SKILL.md, the
    receipt records it there, and nothing lands in ~/.gemini/skills/.

    Also pins that only the Gemini skill location moved: the other tools'
    skills, and Gemini's rules and instruction file, keep their destinations.
    """
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)

    rc = _run(
        ["--tools=claude,codex,gemini,opencode", "--yes"], tmp_path=tmp_path, repo=repo, home=home
    )

    assert rc == 0
    for name in ("foo", "bar"):
        # The admission record is stripped on deploy, so the deployed file keeps
        # the tool-facing front matter and the body rather than the source bytes.
        deployed = (home / ".gemini" / "config" / "skills" / name / "SKILL.md").read_bytes()
        assert deployed == b"---\nname: fixture\ndescription: a fixture artifact\n---\n" + (
            name.encode() + b"\n"
        )
        assert Path(".gemini/config/skills", name) in _receipt_paths(home)
        for other in (".claude", ".codex", ".config/opencode"):
            assert (home / other / "skills" / name / "SKILL.md").is_file()
    assert not (home / ".gemini" / "skills").exists()
    assert (home / ".gemini" / "rules" / "r.md").is_file()
    assert (home / ".gemini" / "GEMINI.md").is_file()


def test_prune_removes_old_gemini_skills_and_leaves_foreign_ones(tmp_path: Path) -> None:
    """
    Given ~/.gemini/skills/ holding skills a prior install recorded (one still
    shipped, one retired, one the user edited since) beside a skill the user
    placed there
    When the next install runs with pruning
    Then the recorded, unedited skills are removed after a backup, and the
    edited and user-placed skills stay.

    The still-shipped skill is an orphan because its recorded path is no longer
    where this run deploys it. The edited one is relinquished because its
    contents no longer match the digest the receipt recorded.
    """
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    old = home / ".gemini" / "skills"
    for name in ("foo", "retired", "edited", "mine"):
        (old / name).mkdir(parents=True)
        (old / name / "SKILL.md").write_bytes(name.encode() + b"\n")
    entries = tuple(
        ReceiptEntry(
            Path(".gemini/skills", name),
            "gemini",
            Path(".gemini"),
            "dir",
            None,
            dir_digest=dir_content_digest(old / name),
        )
        for name in ("foo", "retired", "edited")
    )
    write_receipt(home / _RECEIPT, Receipt(roots=(Path(".gemini"),), entries=entries))
    (old / "edited" / "SKILL.md").write_bytes(b"the user's own change\n")

    rc = _run(["--prune", "--yes", "--tools=gemini"], tmp_path=tmp_path, repo=repo, home=home)

    assert rc == 0
    assert not (old / "foo").exists()
    assert not (old / "retired").exists()
    assert (old / "edited" / "SKILL.md").read_bytes() == b"the user's own change\n"
    assert (old / "mine" / "SKILL.md").read_bytes() == b"mine\n"
    backups = home / ".gemini" / "skills-backup"
    assert [p.name.split(".backup-")[0] for p in sorted(backups.iterdir())] == ["foo", "retired"]
    recorded = _receipt_paths(home)
    assert Path(".gemini/skills/foo") not in recorded
    assert Path(".gemini/skills/retired") not in recorded
    assert Path(".gemini/config/skills/foo") in recorded


def test_install_and_prune_touch_nothing_under_gemini_config_but_skills(tmp_path: Path) -> None:
    """
    Given ~/.gemini/config/ holding Antigravity's state and a skill the user
    placed in config/skills/
    When an install runs, a skill's source changes, and a pruning install
    overwrites the deployed copy
    Then the only additions under ~/.gemini/config/ are the deployed skills,
    every pre-existing path keeps its bytes and mtime, and the overwritten
    skill's backup lands in ~/.gemini/skills-backup/ holding the prior bytes.

    A backup inside config/skills/ would be discovered as a duplicate skill, and
    one in a config/skills-backup/ sibling would write into Antigravity's
    directory.
    """
    repo = _repo(tmp_path)
    home = tmp_path / "home"
    config = home / ".gemini" / "config"
    (config / "projects" / "p").mkdir(parents=True)
    (config / "config.json").write_bytes(b'{"agy": true}\n')
    (config / "mcp_config.json").write_bytes(b"")
    (config / ".migrated").write_bytes(b"")
    (config / "projects" / "p" / "state.json").write_bytes(b"{}\n")
    (config / "skills" / "theirs").mkdir(parents=True)
    (config / "skills" / "theirs" / "SKILL.md").write_bytes(b"theirs\n")
    before = _tree(config)

    assert _run(["--tools=gemini", "--yes"], tmp_path=tmp_path, repo=repo, home=home) == 0
    first = (config / "skills" / "foo" / "SKILL.md").read_bytes()
    (repo / "src" / "user" / ".agents" / "skills" / "foo" / "SKILL.md").write_bytes(
        _admitted(b"foo, revised\n")
    )
    rc = _run(["--prune", "--yes", "--tools=gemini"], tmp_path=tmp_path, repo=repo, home=home)

    assert rc == 0
    after = _tree(config)
    assert {p: after[p] for p in before} == before
    assert set(after) - set(before) == {
        Path("skills/foo"),
        Path("skills/foo/SKILL.md"),
        Path("skills/bar"),
        Path("skills/bar/SKILL.md"),
    }
    (backup,) = (home / ".gemini" / "skills-backup").iterdir()
    assert backup.name.startswith("foo.backup-")
    assert (backup / "SKILL.md").read_bytes() == first
