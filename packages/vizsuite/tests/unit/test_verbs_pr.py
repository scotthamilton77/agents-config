"""`viz pr <n>` end-to-end (plan slices 2-3): reconcile → head-OID estate →
materialized snapshot → scc complexity → HTML.

Slice 2 replaced slice 1's ``HEAD`` estate with the reconciled PR head OID. Slice
3 adds the per-file heat plumbing: the verb materializes the head snapshot from
`git archive`, scc scans *that tempdir* (never the live checkout), the complexity
axis is scored, and the tempdir is torn down in a `finally`. The first two tests
fake every adapter; the last runs the real `SubprocessGitRunner` over a throwaway
repo with only `gh` and `scc` (external binaries) faked, proving the git wiring
end-to-end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import run_cli
from tests.fakes import (
    ScriptedGhRunner,
    ScriptedGitRunner,
    ScriptedSccRunner,
    blob,
    gh_pr_result,
    scc_result,
    tar_of,
)
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
        archive_tar_bytes=tar_of(
            {"src/app.py": "x = 1\n", "README.md": "# hi\n", ".critical-paths": "src/**\n"}
        ),
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 5, "README.md": 2}))

    exit_code, envelope, stderr = run_cli(["pr", "7"], git_runner=git, gh_runner=gh, scc_runner=scc)

    assert exit_code == 0
    assert stderr == ""
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["pr"] == 7
    assert data["nodes"] == 2  # the estate (whole tree at head), not just the net set
    assert data["scored_files"] == 2  # complexity scored both estate files scc recognized
    assert data["consequential_files"] == 1  # src/app.py matched the .critical-paths marker
    # slice 5: PR metadata garnish (author/review-state) is wired into the envelope.
    assert data["author"] == "octocat"
    assert data["review_state"] == "APPROVED"

    # The estate is resolved at the reconciled head OID — never the checkout's HEAD.
    assert ("ls_tree", "head111") in git.calls
    assert ("ls_tree", "HEAD") not in git.calls

    artifact = Path(str(data["artifact"]))
    assert artifact == tmp_path / ".viz" / "out" / "pr-7.html"
    html = artifact.read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "src/app.py" in html


def test_pr_materializes_snapshot_scans_scc_then_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Slice-3 plumbing: the verb materializes the head snapshot from `git archive`,
    # scc scans *that tempdir* (never the live checkout), and the tempdir is torn
    # down afterwards — a leaked snapshot dir is the failure this asserts against.
    monkeypatch.chdir(tmp_path)
    gh = ScriptedGhRunner(
        gh_pr_result(base_oid="base000", head_oid="head111", changed_files=1, commit_count=1)
    )
    git = ScriptedGitRunner(
        present_oids={"base000", "head111"},
        diff_files=["src/app.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="src/app.py", old_path="src/app.py", added=8, deleted=0)
        ],
        ls_tree_rows=[blob("src/app.py", "aaa111")],
        archive_tar_bytes=tar_of({"src/app.py": "x = 1\n"}),
    )
    scc = ScriptedSccRunner(scc_result({"src/app.py": 6}))

    exit_code, _envelope, _stderr = run_cli(
        ["pr", "9"], git_runner=git, gh_runner=gh, scc_runner=scc
    )

    assert exit_code == 0
    assert ("archive_tar", "head111") in git.calls  # snapshot at the resolved head OID
    assert len(scc.calls) == 1  # scc scanned exactly one dir
    scanned_dir = Path(scc.calls[0][1])
    assert not scanned_dir.exists()  # the snapshot tempdir was rmtree'd in the finally


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
    # Real SubprocessGitRunner over a two-commit repo — real archive+materialize —
    # with only gh and scc (external binaries) faked, using the real base/head OIDs
    # the reconciler must agree with.
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
    scc = ScriptedSccRunner(scc_result({"a.py": 3, "b.py": 1}))

    exit_code, envelope, stderr = run_cli(["pr", "5"], gh_runner=gh, scc_runner=scc)

    assert exit_code == 0
    assert stderr == ""
    data = envelope["data"]
    assert isinstance(data, dict)
    artifact = Path(str(data["artifact"]))
    html = artifact.read_text(encoding="utf-8")
    assert "a.py" in html
    assert "b.py" in html
