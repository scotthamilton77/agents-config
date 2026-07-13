"""`viz pr <n>` end-to-end (spec test item 6 setup): estate → scene → HTML file."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedGitRunner, blob


def test_pr_emits_html_artifact_from_estate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    git = ScriptedGitRunner(
        ls_tree_rows=[blob("src/app.py", "aaa111"), blob("README.md", "bbb222")]
    )

    exit_code, envelope, stderr = run_cli(["pr", "1"], git_runner=git)

    assert exit_code == 0
    assert stderr == ""
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["pr"] == 1
    assert data["nodes"] == 2

    # Slice 1 resolves the estate at HEAD (pre-gh; slice 2 uses the head OID).
    assert git.calls == [("ls_tree", "HEAD")]

    # data.artifact is a real self-contained HTML file carrying the estate nodes.
    artifact = Path(str(data["artifact"]))
    assert artifact == tmp_path / ".viz" / "out" / "pr-1.html"
    assert artifact.is_file()
    html = artifact.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "src/app.py" in html
    assert "README.md" in html

    # The portable versioned sidecar ignores only out/.
    gitignore = tmp_path / ".viz" / ".gitignore"
    assert "out/" in gitignore.read_text().splitlines()


def _git(cwd: Path, *args: str) -> None:
    # A known binary (git) on test-literal args — the intentional-subprocess case.
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def test_pr_builds_against_real_git_with_default_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # No injected runner → main constructs the real SubprocessGitRunner and reads
    # the estate from an actual committed tree.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    monkeypatch.chdir(tmp_path)

    exit_code, envelope, stderr = run_cli(["pr", "3"])

    assert exit_code == 0
    assert stderr == ""
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    assert artifact == tmp_path / ".viz" / "out" / "pr-3.html"
    assert "hello.py" in artifact.read_text(encoding="utf-8")
