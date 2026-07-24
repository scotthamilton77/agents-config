"""The spec lint's CLI entry (S5-B6): a runnable ``spec-lint`` that
exits nonzero on a violation and 0 on a clean/missing/empty tree, driving a
deliberately malformed fixture spec red. The fixture lives under the test
tree, never under the repo's real docs/specs/."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from installer.spec_lint_cli import main


def _malformed_fixture(tmp_path: Path) -> Path:
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "2026-07-25-broken.md").write_text(
        "# Broken spec\n\nNo acceptance criteria heading here.\n", encoding="utf-8"
    )
    return tmp_path


def test_s5_b6_malformed_fixture_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _malformed_fixture(tmp_path)
    exit_code = main([str(repo_root)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "broken.md" in err
    assert "violation" in err


def test_s5_b5_clean_tree_exits_zero(tmp_path: Path) -> None:
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "2026-07-25-clean.md").write_text(
        "# Clean spec\n\n## Acceptance criteria\n\n- **AC1** it works.\n",
        encoding="utf-8",
    )
    assert main([str(tmp_path)]) == 0


def test_s5_b5_missing_docs_specs_exits_zero(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 0


def test_default_repo_root_is_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitting the positional arg lints ``<cwd>/docs/specs`` (S5-B5, no
    crash on a cwd with no such tree)."""
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0


def test_module_is_runnable_as_python_dash_m(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m installer.spec_lint_cli`` resolves and exits (the
    ``make spec-lint`` invocation shape); pins the ``__main__`` guard."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["spec-lint"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.spec_lint_cli", run_name="__main__")
    assert exc_info.value.code == 0
