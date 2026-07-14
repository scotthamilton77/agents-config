"""gh api graphql JSON → typed `PrView` (plan slice 2/5; test item 11 support).

`parse_pr_view` is the single place that turns the raw `gh api graphql` stdout
into vizsuite's `PrView` — one round-trip carries both the drift-critical scalar
join (OIDs, base ref, changed-files/commit counts) and the PR-metadata garnish
(author/review-state/timestamps), so `reconcile()` never needs a second gh
subprocess call. The runner (`SubprocessGhRunner`) only shells out; every shape
decision — nonzero exit, non-JSON, a null/absent pull request, a missing scalar
— lands here as a loud typed `VizError(ADAPTER_FAILURE)`, never a silent
default (mirrors workcli's bd/parse drift discipline). These tests drive the
parser directly on scripted `GhResult`s, so no `gh` binary is ever touched.
"""

from __future__ import annotations

import json

import pytest

from vizsuite.adapters.gh.runner import GhResult
from vizsuite.envelope import ErrorCode, VizError


def _graphql_stdout(
    *,
    base_oid: str = "base000",
    head_oid: str = "head111",
    base_ref: str = "main",
    changed_files: int = 2,
    commit_count: int = 3,
    author: str = "octocat",
    review_decision: str | None = "APPROVED",
    created_at: str = "2026-07-01T00:00:00Z",
    updated_at: str = "2026-07-02T00:00:00Z",
    merged_at: str | None = None,
    name_with_owner: str = "octocat/hello-world",
) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "nameWithOwner": name_with_owner,
                    "pullRequest": {
                        "baseRefOid": base_oid,
                        "headRefOid": head_oid,
                        "baseRefName": base_ref,
                        "changedFiles": changed_files,
                        "commits": {"totalCount": commit_count},
                        "author": {"login": author},
                        "reviewDecision": review_decision,
                        "createdAt": created_at,
                        "updatedAt": updated_at,
                        "mergedAt": merged_at,
                    },
                }
            }
        }
    )


def test_parses_oids_ref_scalar_counts_and_meta_in_one_round_trip():
    from vizsuite.adapters.gh.parse import parse_pr_view

    result = GhResult(returncode=0, stdout=_graphql_stdout(), stderr="")

    pr = parse_pr_view(result, pr_number=7)

    assert pr.base_oid == "base000"
    assert pr.head_oid == "head111"
    assert pr.base_ref == "main"
    assert pr.changed_files == 2
    assert pr.commit_count == 3
    assert pr.meta.author == "octocat"
    assert pr.meta.review_state == "APPROVED"
    assert pr.meta.created_at == "2026-07-01T00:00:00Z"
    assert pr.meta.updated_at == "2026-07-02T00:00:00Z"
    assert pr.meta.merged_at is None
    assert pr.meta.repo_nwo == "octocat/hello-world"


def test_null_review_decision_normalizes_to_none_sentinel():
    from vizsuite.adapters.gh.parse import parse_pr_view

    result = GhResult(returncode=0, stdout=_graphql_stdout(review_decision=None), stderr="")

    pr = parse_pr_view(result, pr_number=7)

    assert pr.meta.review_state == "NONE"


def test_nonzero_gh_exit_is_adapter_failure():
    from vizsuite.adapters.gh.parse import parse_pr_view

    result = GhResult(returncode=1, stdout="", stderr="gh: not authenticated")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=7)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE
    # the PR number and gh's own stderr survive into the error detail for triage
    assert exc_info.value.detail["pr_number"] == 7
    assert "not authenticated" in str(exc_info.value.detail["stderr"])


def test_non_json_stdout_is_adapter_failure():
    from vizsuite.adapters.gh.parse import parse_pr_view

    result = GhResult(returncode=0, stdout="not json at all", stderr="")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=7)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE


def test_null_pull_request_is_adapter_failure():
    # graphql returns pullRequest: null for a number that resolves to no PR.
    from vizsuite.adapters.gh.parse import parse_pr_view

    stdout = json.dumps({"data": {"repository": {"pullRequest": None}}})
    result = GhResult(returncode=0, stdout=stdout, stderr="")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=999)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE
    assert exc_info.value.detail["pr_number"] == 999


def test_missing_scalar_field_is_adapter_failure():
    from vizsuite.adapters.gh.parse import parse_pr_view

    pull_request = {
        "baseRefOid": "b",
        "headRefOid": "h",
        "baseRefName": "main",
        # changedFiles omitted — a drifted gh shape must alarm, not default to 0
        "commits": {"totalCount": 1},
        "author": {"login": "octocat"},
        "reviewDecision": "APPROVED",
        "createdAt": "x",
        "updatedAt": "y",
        "mergedAt": None,
    }
    stdout = json.dumps({"data": {"repository": {"pullRequest": pull_request}}})
    result = GhResult(returncode=0, stdout=stdout, stderr="")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=7)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE


def test_missing_name_with_owner_is_adapter_failure():
    from vizsuite.adapters.gh.parse import parse_pr_view

    pull_request = {
        "baseRefOid": "b",
        "headRefOid": "h",
        "baseRefName": "main",
        "changedFiles": 1,
        "commits": {"totalCount": 1},
        "author": {"login": "octocat"},
        "reviewDecision": "APPROVED",
        "createdAt": "x",
        "updatedAt": "y",
        "mergedAt": None,
    }
    # nameWithOwner omitted from repository — a drifted gh shape must alarm.
    stdout = json.dumps({"data": {"repository": {"pullRequest": pull_request}}})
    result = GhResult(returncode=0, stdout=stdout, stderr="")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=7)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE


def test_missing_meta_scalar_field_is_adapter_failure():
    from vizsuite.adapters.gh.parse import parse_pr_view

    pull_request = {
        "baseRefOid": "b",
        "headRefOid": "h",
        "baseRefName": "main",
        "changedFiles": 1,
        "commits": {"totalCount": 1},
        "reviewDecision": "APPROVED",
        "createdAt": "x",
        "updatedAt": "y",
        "mergedAt": None,
        # author omitted — a drifted gh shape must alarm, not default
    }
    stdout = json.dumps({"data": {"repository": {"pullRequest": pull_request}}})
    result = GhResult(returncode=0, stdout=stdout, stderr="")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=7)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE
