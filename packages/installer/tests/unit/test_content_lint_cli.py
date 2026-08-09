"""The content lint's CLI edge: exit codes and what reaches which stream.

A fatal finding must land on stderr and exit 1; the budget numbers must print
regardless, since their whole purpose is to be read on a passing run.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from installer.content_lint_cli import main
from installer.core.merge.base import CollisionError
from installer.core.surface_budget import (
    ALWAYS_ON_TOKEN_CAP,
    SKILL_BODY_TOKEN_CAP,
    USER_CORE_TOKEN_CAP,
    USER_INVOKED_SKILL_BODY_TOKEN_CAP,
)

_RECORD = "---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"


def _repo(
    tmp_path: Path,
    *,
    skill: str,
    name: str = "tidy",
    tree: str = ".agents",
    payload: dict[str, str] | None = None,
) -> Path:
    """A repo root carrying one skill. ``tree`` picks the tool subdirectory, which
    decides whether a user-invoked declaration survives the projection."""
    (tmp_path / ".installignore").write_text("AGENTS.md\n", encoding="utf-8")
    skill_dir = tmp_path / "src" / "user" / tree / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill, encoding="utf-8")
    for filename, text in (payload or {}).items():
        target = skill_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


def test_clean_tree_exits_zero_and_prints_the_budget_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skill=_RECORD + "short\n")

    assert main([str(repo)]) == 0

    out = capsys.readouterr().out
    assert f"cap {ALWAYS_ON_TOKEN_CAP} tokens" in out
    # The core answers to a ceiling over twelve times tighter than the surface
    # cap, so its own number and its own ceiling both have to print: a core that
    # had doubled would otherwise leave the surface total looking comfortable.
    assert f"core {USER_CORE_TOKEN_CAP}" in out
    assert "(core 0," in out
    # Both ceilings on the header, and the one that applied on the body's own
    # line: with two caps in play a lone number says nothing about headroom.
    assert f"cap {SKILL_BODY_TOKEN_CAP} tokens" in out
    assert f"{USER_INVOKED_SKILL_BODY_TOKEN_CAP} when user-invoked" in out
    assert f"/ {SKILL_BODY_TOKEN_CAP}" in out
    assert "skills/tidy" in out


def test_a_user_invoked_skill_reports_against_the_raised_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A body between the two caps deploys, and the trend line says which ceiling
    let it through.

    The Claude-only tree is the fixture because that is where the looser ceiling
    is earned: the same declaration in the shared tree is stripped for three of
    four tools, and the body is measured against the strict cap on each of them.
    """
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    flagged = _RECORD.replace("---\n", "---\ndisable-model-invocation: true\n", 1)
    repo = _repo(tmp_path, skill=flagged + body, tree=".claude")

    assert main([str(repo)]) == 0
    assert f"/ {USER_INVOKED_SKILL_BODY_TOKEN_CAP}" in capsys.readouterr().out


def test_the_payload_block_prints_on_a_pass_and_changes_no_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A report, not a ceiling. It exists because a reader cannot otherwise see
    what a skill costs when they follow one of its pointers — and its header says
    there is no cap, so the number is not read as a third one."""
    repo = _repo(
        tmp_path,
        skill=_RECORD + "short\n",
        payload={"references/long.md": "p" * 40_000, "scripts/run.py": "c" * 4},
    )

    assert main([str(repo)]) == 0

    out = capsys.readouterr().out
    assert "no cap" in out
    assert "10000 prose" in out
    assert "references/long.md" in out
    assert "1 non-prose" in out


def test_a_skill_with_nothing_beside_its_body_prints_no_payload_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A line reading zero is noise in a report whose whole purpose is to show
    where the weight is."""
    repo = _repo(tmp_path, skill=_RECORD + "short\n")

    assert main([str(repo)]) == 0
    assert "reference payloads" not in capsys.readouterr().out


def test_over_cap_body_exits_one_and_names_the_skill_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skill=_RECORD + "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4))

    assert main([str(repo)]) == 1

    captured = capsys.readouterr()
    assert "skills/tidy" in captured.err
    assert "failure(s)" in captured.err


def test_record_less_under_src_user_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skill="# no front matter\n")

    assert main([str(repo)]) == 1
    assert "carries no admission record" in capsys.readouterr().err


def test_record_less_plugin_rule_is_announced_but_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skill=_RECORD + "short\n")
    rules = repo / "src" / "plugins" / "graphify" / ".agents" / "rules"
    rules.mkdir(parents=True)
    (rules / "graphify.md").write_text("# no record\n", encoding="utf-8")

    assert main([str(repo)]) == 0

    out = capsys.readouterr().out
    assert "not admitted (no record)" in out
    assert "will not deploy" in out


def test_each_record_less_entry_names_the_file_a_reader_has_to_edit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every entry prints the source file, including one that reached the gate
    through the directory-override channel: those bytes now name the file that
    supplied them, so nothing is reported as an anonymous destination a reader
    cannot open."""
    from installer.core.content_lint import ContentLintResult, Unadmitted

    result = ContentLintResult(
        unadmitted=[
            Unadmitted(
                source=Path("src/plugins/p/.agents/skills/foo/SKILL.md"),
                tools=("claude",),
                fatal=False,
            ),
            Unadmitted(
                source=Path("src/user/.agents/rules/bar.md"), tools=("gemini",), fatal=False
            ),
        ]
    )
    monkeypatch.setattr("installer.content_lint_cli.lint_content", lambda *_a, **_k: result)

    assert main([str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "src/plugins/p/.agents/skills/foo/SKILL.md" in out
    assert "src/user/.agents/rules/bar.md" in out
    assert "2 artifact(s)" in out


def test_missing_installignore_is_a_config_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The manifest is load-bearing exclusion policy, so its absence must surface as
    a clean exit 2 rather than a stack trace or a falsely clean tree."""
    (tmp_path / "src").mkdir()

    assert main([str(tmp_path)]) == 2
    assert ".installignore" in capsys.readouterr().err


def test_unstageable_src_is_a_named_failure_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two files claiming one destination means src/ cannot be staged at all. The
    lint's job is to name that content defect; a stack trace makes the reader
    decode it instead."""

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise CollisionError(Path("src/a.md"), Path("src/b.md"))

    monkeypatch.setattr("installer.content_lint_cli.lint_content", _explode)

    assert main([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "does not stage" in err
    assert "a.md" in err


def test_module_is_runnable_as_python_dash_m(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m installer.content_lint_cli`` is the make-target invocation shape;
    pins the ``__main__`` guard."""
    _repo(tmp_path, skill=_RECORD + "short\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["content-lint"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.content_lint_cli", run_name="__main__")
    assert exc_info.value.code == 0
