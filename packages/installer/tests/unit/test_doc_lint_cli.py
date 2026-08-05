"""The citation lint's CLI edge, and the seam it takes its roster from.

Two things are pinned here that the pure lint cannot pin on its own: that the
asset roster is the admission gate's verdict over a staged ``src/`` rather than a
directory listing, and that the run reports a verdict rather than a traceback
when the tree cannot be read.
"""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

import pytest

from installer import doc_lint_cli
from installer.core.content_lint import admitted_asset_names, deployed_asset_names
from installer.core.doc_lint import Finding
from installer.core.io_port import ScriptedIO

_RECORD = "---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"
_INSTALLIGNORE = "AGENTS.md\nCLAUDE.md\nGEMINI.md\nREADME.md\nrules-readmes/\n"


def _repo(tmp_path: Path, *, skills: dict[str, str]) -> Path:
    """A minimal repo root the installer can stage, mirroring the content-lint
    fixture so both gates are exercised against the same shape."""
    (tmp_path / ".installignore").write_text(_INSTALLIGNORE, encoding="utf-8")
    shared = tmp_path / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "AGENTS.md.template").write_text("# laws\n", encoding="utf-8")
    for name, text in skills.items():
        skill_dir = shared / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return tmp_path


def test_the_roster_is_what_the_admission_gate_admits(tmp_path: Path) -> None:
    """Presence in ``src/`` is not deployment. A record-less skill reaches no
    agent, so prose naming it is naming something nobody can invoke — and a
    roster built by listing directories would say the opposite."""
    repo = _repo(
        tmp_path,
        skills={
            "admitted-skill": _RECORD + "# body\n",
            "recordless-skill": "# body\n",
        },
    )
    roster = deployed_asset_names(repo, io=ScriptedIO())
    assert roster["skills"] == frozenset({"admitted-skill"})


def test_a_name_is_the_destination_minus_its_extension() -> None:
    """How a tool addresses the artifact: a skill directory and a rule file are
    both named for their last component."""
    from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool

    plan = StagingPlan(
        tool=Tool.CLAUDE,
        items={
            Path("skills/writing-skills"): StagedItem(
                source_path=Path("src/skills/writing-skills"),
                dest_relpath=Path("skills/writing-skills"),
                kind=FileKind.DIR,
                namespace="skills",
                provenance=Provenance(kind="tool", name="claude"),
            ),
            Path("rules/delegation.md"): StagedItem(
                source_path=Path("src/rules/delegation.md"),
                dest_relpath=Path("rules/delegation.md"),
                kind=FileKind.NAMESPACED_MD,
                namespace="rules",
                provenance=Provenance(kind="tool", name="claude"),
                content=b"x",
            ),
            Path("AGENTS.md"): StagedItem(
                source_path=Path("src/AGENTS.md"),
                dest_relpath=Path("AGENTS.md"),
                kind=FileKind.OTHER,
                namespace=None,
                provenance=Provenance(kind="tool", name="claude"),
                content=b"x",
            ),
        },
    )
    names = admitted_asset_names({Tool.CLAUDE: plan})
    assert names == {"skills": frozenset({"writing-skills"}), "rules": frozenset({"delegation"})}


def test_a_clean_tree_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skills={"grilling": _RECORD + "# body\n"})
    (repo / "docs" / "specs").mkdir(parents=True)
    (repo / "README.md").write_text("Read the `grilling` skill.\n", encoding="utf-8")
    monkeypatch.setattr(doc_lint_cli, "tracked_files", lambda _root: [Path("README.md")])

    out = capsys.readouterr
    assert doc_lint_cli.main([str(repo)]) == 0
    printed = out().out
    assert "read 1 tracked Markdown file(s)" in printed
    # The silencing rule's reach is on the output of every run, pass or fail:
    # a rule that can hide a finding must not be invisible.
    assert "0 citation(s) not judged" in printed


def test_findings_exit_one_and_are_grouped_by_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Grouped because that is how they get fixed: one file is one editing
    session, and a flat list makes a reader hop between documents."""
    repo = _repo(tmp_path, skills={"grilling": _RECORD + "# body\n"})
    (repo / "docs" / "specs").mkdir(parents=True)
    (repo / "README.md").write_text("Run the `gone-skill` skill.\n", encoding="utf-8")
    (repo / "CONTRIBUTING.md").write_text("See `docs/missing.md`.\n", encoding="utf-8")
    monkeypatch.setattr(
        doc_lint_cli,
        "tracked_files",
        lambda _root: [Path("CONTRIBUTING.md"), Path("README.md")],
    )

    assert doc_lint_cli.main([str(repo)]) == 1
    err = capsys.readouterr().err
    assert "\nCONTRIBUTING.md\n" in err
    assert "\nREADME.md\n" in err
    assert "CONTRIBUTING.md:1: `docs/missing.md` — path does not exist" in err
    assert "2 unresolved citation(s) in 2 file(s)" in err


def test_a_stale_exemption_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skills={"grilling": _RECORD + "# body\n"})
    (repo / "README.md").write_text("Nothing to see.\n", encoding="utf-8")
    monkeypatch.setattr(doc_lint_cli, "tracked_files", lambda _root: [Path("README.md")])

    assert doc_lint_cli.main([str(repo)]) == 1
    assert "exempt from doc-lint" in capsys.readouterr().err


def test_an_unstageable_tree_exits_two_without_a_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A roster that is short reports every correct citation as stale, so a tree
    that will not stage gets no verdict rather than a false one."""
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    assert doc_lint_cli.main([str(tmp_path)]) == 2
    assert "doc-lint:" in capsys.readouterr().err


def test_a_git_failure_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skills={"grilling": _RECORD + "# body\n"})
    (repo / "docs" / "specs").mkdir(parents=True)

    def _boom(_root: Path) -> list[Path]:
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(doc_lint_cli, "tracked_files", _boom)
    assert doc_lint_cli.main([str(repo)]) == 2
    assert "cannot list tracked files" in capsys.readouterr().err


def test_tracked_files_asks_git_for_the_whole_tracked_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not just the Markdown: the prose in scope is one filter over the tracked
    set, and resolving a path citation needs the other files."""
    captured: dict[str, list[str]] = {}

    class _Proc:
        stdout = "README.md\0packages/installer/src/installer/cli.py\0"

    def _run(argv: list[str], **_kwargs: object) -> _Proc:
        captured["argv"] = argv
        return _Proc()

    monkeypatch.setattr(subprocess, "run", _run)
    assert doc_lint_cli.tracked_files(tmp_path) == [
        Path("README.md"),
        Path("packages/installer/src/installer/cli.py"),
    ]
    assert captured["argv"][-1] == "-z"


def test_module_is_runnable_as_python_dash_m(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m installer.doc_lint_cli`` is the make-target invocation shape;
    pins the ``__main__`` guard."""
    repo = _repo(tmp_path, skills={"grilling": _RECORD + "# body\n"})
    (repo / "docs" / "specs").mkdir(parents=True)
    (repo / "README.md").write_text("Read the `grilling` skill.\n", encoding="utf-8")

    # ``run_module`` executes a fresh copy, so a patch on the imported module
    # object does not reach it — the seam has to be the shared ``subprocess``.
    class _Proc:
        stdout = "README.md\0"

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc())
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.argv", ["doc-lint"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.doc_lint_cli", run_name="__main__")
    assert exc_info.value.code == 0


def test_a_generated_path_git_ignores_is_not_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path a tool writes at runtime is documented prose about a generated
    artifact, not a stale citation, and nothing about the string tells the two
    apart. ``.gitignore`` already draws that line, so the answer comes from git
    rather than from a pattern matcher written here."""
    readme = Path("README.md")
    findings = [
        Finding(file=readme, line=3, citation="out/x.json", reason="p", target="out/x.json"),
        Finding(file=readme, line=4, citation="docs/gone.md", reason="p", target="docs/gone.md"),
        Finding(file=readme, line=5, citation="a-skill", reason="asset"),
    ]

    def _run(argv: list[str], **kwargs: object) -> object:
        assert argv[3] == "check-ignore"
        assert kwargs["input"] == "out/x.json\ndocs/gone.md"

        class _Proc:
            stdout = "out/x.json\n"

        return _Proc()

    monkeypatch.setattr(subprocess, "run", _run)
    kept = doc_lint_cli.drop_ignored(tmp_path, findings)
    assert [f.citation for f in kept] == ["docs/gone.md", "a-skill"]


def test_no_path_findings_means_no_git_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One batched call, and none at all when there is nothing to ask about."""

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError

    monkeypatch.setattr(subprocess, "run", _boom)
    asset = [Finding(file=Path("README.md"), line=1, citation="a-skill", reason="asset")]
    assert doc_lint_cli.drop_ignored(tmp_path, asset) == asset


def test_an_unanswerable_query_leaves_the_findings_standing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``check-ignore`` exits nonzero both when nothing matched and when it
    cannot answer, so the return code is not read — the safe direction is to
    report."""

    class _Proc:
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _Proc())
    findings = [
        Finding(file=Path("README.md"), line=1, citation="x/y.md", reason="p", target="x/y.md")
    ]
    assert doc_lint_cli.drop_ignored(tmp_path, findings) == findings
