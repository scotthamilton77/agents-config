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
from installer.core.surface_budget import ALWAYS_ON_TOKEN_CAP, SKILL_BODY_TOKEN_CAP

_RECORD = "---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"


def _repo(tmp_path: Path, *, skill: str, name: str = "tidy") -> Path:
    (tmp_path / ".installignore").write_text("AGENTS.md\n", encoding="utf-8")
    skill_dir = tmp_path / "src" / "user" / ".agents" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill, encoding="utf-8")
    return tmp_path


def test_clean_tree_exits_zero_and_prints_both_budgets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, skill=_RECORD + "short\n")

    assert main([str(repo)]) == 0

    out = capsys.readouterr().out
    assert f"cap {ALWAYS_ON_TOKEN_CAP} tokens" in out
    assert f"cap {SKILL_BODY_TOKEN_CAP} tokens" in out
    assert "skills/tidy" in out


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


def test_each_unattributable_entry_names_the_destination_it_was_heading_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bytes reaching the gate through the override channel carry no recorded
    origin. Bucketing them all under that absent origin reported every one of them
    as one anonymous artifact with a merged tool list; keyed on the gate's own
    label they stay distinct, and each says where it was going instead of nowhere.
    """
    from installer.core.content_lint import ContentLintResult, Unadmitted

    result = ContentLintResult(
        unadmitted=[
            Unadmitted(source=None, dest=Path("skills/foo"), tools=("claude",), fatal=False),
            Unadmitted(source=None, dest=Path("skills/bar"), tools=("gemini",), fatal=False),
        ]
    )
    monkeypatch.setattr("installer.content_lint_cli.lint_content", lambda *_a, **_k: result)

    assert main([str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "<merged entry at skills/foo, source unrecorded>" in out
    assert "<merged entry at skills/bar, source unrecorded>" in out
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
