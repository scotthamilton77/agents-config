"""PR reconciler — the two-source scalar drift alarm (spec test item 11).

Local git is authoritative for the file/commit *sets*; GitHub is a second witness
via un-truncated *scalar counts* (`changedFiles`, `commits.totalCount`), so the
join survives PRs of any size (no `first:100` list cap). Disagreement is a loud
`RECONCILER_DRIFT`; base/head OIDs still absent after a fetch is `SNAPSHOT_MISMATCH`.
Driven entirely through scripted gh/git fakes — the real parse runs, no subprocess.
"""

from __future__ import annotations

import pytest

from tests.fakes import ScriptedGhRunner, ScriptedGitRunner, gh_pr_meta_result, gh_pr_result
from vizsuite.adapters.git.runner import ModifiedFileRow
from vizsuite.envelope import ErrorCode, VizError
from vizsuite.extract.churn import FileChurn

_PRESENT = {"base000", "head111"}  # gh_pr_result defaults; both OIDs local by default


def test_file_count_drift_raises_reconciler_drift():
    from vizsuite.reconcile.pr_scope import reconcile

    gh = ScriptedGhRunner(gh_pr_result(changed_files=2, commit_count=1))
    git = ScriptedGitRunner(present_oids=set(_PRESENT), diff_files=["only_one.py"])

    with pytest.raises(VizError) as exc_info:
        reconcile(7, gh=gh, git=git)

    assert exc_info.value.code == ErrorCode.RECONCILER_DRIFT
    assert exc_info.value.detail["local"] == 1
    assert exc_info.value.detail["github_changed_files"] == 2


def test_commit_count_drift_raises_reconciler_drift():
    from vizsuite.reconcile.pr_scope import reconcile

    # file counts agree (1 == 1) but the commit counts disagree (1 local vs 2).
    gh = ScriptedGhRunner(gh_pr_result(changed_files=1, commit_count=2))
    git = ScriptedGitRunner(present_oids=set(_PRESENT), diff_files=["a.py"], rev_list_oids=["c1"])

    with pytest.raises(VizError) as exc_info:
        reconcile(7, gh=gh, git=git)

    assert exc_info.value.code == ErrorCode.RECONCILER_DRIFT
    assert exc_info.value.detail["local"] == 1
    assert exc_info.value.detail["github_commits"] == 2


def test_happy_path_returns_scope_with_net_churn():
    from vizsuite.reconcile.pr_scope import reconcile

    gh = ScriptedGhRunner(gh_pr_result(changed_files=2, commit_count=1))
    git = ScriptedGitRunner(
        present_oids=set(_PRESENT),
        diff_files=["a.py", "b.py"],
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="a.py", old_path="a.py", added=4, deleted=1),
            ModifiedFileRow(new_path="b.py", old_path=None, added=2, deleted=0),
        ],
    )

    scope = reconcile(7, gh=gh, git=git)

    assert scope.pr_number == 7
    assert scope.head_oid == "head111"
    assert scope.base_oid == "base000"
    assert scope.files == {
        "a.py": FileChurn(added=4, deleted=1),
        "b.py": FileChurn(added=2, deleted=0),
    }
    # churn walked the local (authoritative) commit set
    assert ("churn_for_commits", "c1") in git.calls


def test_scope_carries_pr_metadata_author_review_state_and_timestamps():
    from vizsuite.reconcile.pr_scope import reconcile

    gh = ScriptedGhRunner(
        result=gh_pr_result(changed_files=1, commit_count=1),
        meta_result=gh_pr_meta_result(author="octocat", review_state="APPROVED"),
    )
    git = ScriptedGitRunner(present_oids=set(_PRESENT), diff_files=["a.py"], rev_list_oids=["c1"])

    scope = reconcile(7, gh=gh, git=git)

    assert scope.meta.author == "octocat"
    assert scope.meta.review_state == "APPROVED"
    assert ("pr_meta", 7) in gh.calls


def test_reverted_only_file_excluded_from_scope():
    from vizsuite.reconcile.pr_scope import reconcile

    # b.py was added then reverted inside the PR: present in the churn union, absent
    # from the net diff. It must not reach the scene or it would misdirect review heat.
    gh = ScriptedGhRunner(gh_pr_result(changed_files=1, commit_count=1))
    git = ScriptedGitRunner(
        present_oids=set(_PRESENT),
        diff_files=["a.py"],  # net set = {a.py}
        rev_list_oids=["c1"],
        churn_rows=[
            ModifiedFileRow(new_path="a.py", old_path="a.py", added=3, deleted=0),
            ModifiedFileRow(new_path="b.py", old_path="b.py", added=5, deleted=5),
        ],
    )

    scope = reconcile(7, gh=gh, git=git)

    assert set(scope.files) == {"a.py"}
    assert "b.py" not in scope.files


def test_big_pr_over_100_files_does_not_false_drift():
    from vizsuite.reconcile.pr_scope import reconcile

    # 150 net files with changedFiles=150 — a value a `first:100` list read would have
    # truncated to 100 and mis-flagged as drift. The scalar path is cap-immune.
    net = [f"src/f{i}.py" for i in range(150)]
    gh = ScriptedGhRunner(gh_pr_result(changed_files=150, commit_count=1))
    git = ScriptedGitRunner(present_oids=set(_PRESENT), diff_files=net, rev_list_oids=["c1"])

    scope = reconcile(7, gh=gh, git=git)

    assert scope.head_oid == "head111"  # built, no RECONCILER_DRIFT raised


def test_unfetchable_head_raises_snapshot_mismatch():
    from vizsuite.reconcile.pr_scope import reconcile

    # head absent locally and the PR fetch resolves nothing → refuse loudly, no scene.
    gh = ScriptedGhRunner(gh_pr_result(changed_files=1, commit_count=1))
    git = ScriptedGitRunner(
        present_oids={"base000"},  # base present, head absent
        fetch_brings=set(),  # fetch resolves nothing
        diff_files=["a.py"],
        rev_list_oids=["c1"],
    )

    with pytest.raises(VizError) as exc_info:
        reconcile(7, gh=gh, git=git)

    assert exc_info.value.code == ErrorCode.SNAPSHOT_MISMATCH
    assert "head111" in exc_info.value.detail["missing_oids"]
    # the PR-head fetch was attempted before giving up
    assert ("fetch_pr", "7") in git.calls


def test_unfetchable_base_raises_snapshot_mismatch():
    from vizsuite.reconcile.pr_scope import reconcile

    # `pull/<n>/head` never brings the base tip; the base ref must be fetched
    # separately, and if that resolves nothing the snapshot cannot be built.
    gh = ScriptedGhRunner(gh_pr_result(changed_files=1, commit_count=1))
    git = ScriptedGitRunner(
        present_oids={"head111"},  # head present, base absent
        fetch_brings=set(),
        diff_files=["a.py"],
        rev_list_oids=["c1"],
    )

    with pytest.raises(VizError) as exc_info:
        reconcile(7, gh=gh, git=git)

    assert exc_info.value.code == ErrorCode.SNAPSHOT_MISMATCH
    assert "base000" in exc_info.value.detail["missing_oids"]
    assert ("fetch_base", "main") in git.calls


def test_head_absent_then_fetched_reconciles():
    from vizsuite.reconcile.pr_scope import reconcile

    # head absent, but the PR fetch brings it → reconcile proceeds to success.
    gh = ScriptedGhRunner(gh_pr_result(changed_files=1, commit_count=1))
    git = ScriptedGitRunner(
        present_oids={"base000"},
        fetch_brings={"head111"},  # the fetch resolves the head OID
        diff_files=["a.py"],
        rev_list_oids=["c1"],
        churn_rows=[ModifiedFileRow(new_path="a.py", old_path="a.py", added=1, deleted=0)],
    )

    scope = reconcile(7, gh=gh, git=git)

    assert scope.head_oid == "head111"
    assert ("fetch_pr", "7") in git.calls
