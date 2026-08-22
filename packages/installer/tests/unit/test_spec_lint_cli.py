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


_OWES_A_LEDGER = """# A spec

## Acceptance criteria

- **AC1** It works.

## Continuations

- feat: Do the thing — AC: AC1.
"""


def test_init_evidence_backfills_a_ledgerless_spec_and_leaves_it_clean(tmp_path: Path) -> None:
    """The generation path the rule ships with. Without it, turning the rule on
    means hand-writing a row per criterion across a 62-criterion spec, and the
    parser that already knows the AC universe can do it."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    spec = specs_dir / "2026-07-25-owes.md"
    spec.write_text(_OWES_A_LEDGER, encoding="utf-8")

    assert main([str(tmp_path), "--init-evidence"]) == 0
    assert "- AC1 | open" in spec.read_text(encoding="utf-8")
    assert main([str(tmp_path)]) == 0


def test_init_evidence_leaves_an_existing_ledger_alone(tmp_path: Path) -> None:
    """Re-running it must not clobber a row an author filled in — the generator
    is a backfill, not a reset."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    spec = specs_dir / "2026-07-25-owes.md"
    spec.write_text(_OWES_A_LEDGER, encoding="utf-8")
    main([str(tmp_path), "--init-evidence"])
    filled = spec.read_text(encoding="utf-8").replace(
        "- AC1 | open", "- AC1 | observed: #1 2026-08-22 scotthamilton77"
    )
    spec.write_text(filled, encoding="utf-8")

    assert main([str(tmp_path), "--init-evidence"]) == 0
    assert spec.read_text(encoding="utf-8") == filled
