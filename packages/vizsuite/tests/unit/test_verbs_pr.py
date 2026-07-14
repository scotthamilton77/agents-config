"""`viz pr <n>` end-to-end (plan slice 2): reconcile → head-OID estate → HTML.

Slice 2 replaces slice 1's ``HEAD`` estate with the reconciled PR head OID: the
verb resolves/fetches the immutable base/head OIDs, reconciles local git's net
sets against GitHub's scalar counts, then builds the estate at the *head OID* (not
the operator's checkout). The first test fakes every adapter; the second runs the
real `SubprocessGitRunner` over a throwaway repo with only `gh` (the external
service) faked, proving the git wiring end-to-end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedGhRunner, ScriptedGitRunner, blob, gh_pr_result
from vizsuite.adapters.git.runner import ModifiedFileRow


def test_pr_reconciles_and_emits_html_from_head_estate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = ScriptedGitRunner(
        present_oids={"base000", "head111"},
        diff_files=["src/app.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=3, deleted=0)
        ],
        ls_tree_rows=[blob("src/app.py", "aaa111"), blob("README.md", "bbb222")],
    )

    exit_code, envelope, stderr = run_cli(["pr", "7"], git_runner=git, gh_runner=gh)

    assert exit_code == 0
    assert stderr == ""
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["pr"] == 7
    assert data["nodes"] == 2  # the estate (whole tree at head), not just the net set

    # The estate is resolved at the reconciled head OID — never the checkout's HEAD.
    assert ("ls_tree", "head111") in git.calls
    assert ("ls_tree", "HEAD") not in git.calls

    artifact = Path(str(data["artifact"]))
    assert artifact == tmp_path / ".viz" / "out" / "pr-7.html"
    html = artifact.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "src/app.py" in html


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607


def _rev_parse(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_pr_reconciles_against_real_git_with_fake_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Real SubprocessGitRunner over a two-commit repo; only gh (the external
    # service) is faked, with the real base/head OIDs the reconciler must agree with.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = _rev_parse(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "head")
    head = _rev_parse(tmp_path)
    monkeypatch.chdir(tmp_path)

    gh = ScriptedGhRunner(
        gh_pr_result(base_oid=base, head_oid=head, changed_files=2, commit_count=1)
    )

    exit_code, envelope, stderr = run_cli(["pr", "5"], gh_runner=gh)

    assert exit_code == 0
    assert stderr == ""
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    html = artifact.read_text(encoding="utf-8")
    assert "a.py" in html
    assert "b.py" in html
