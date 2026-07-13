"""gh api graphql JSON → typed `PrView` (plan slice 2; test item 11 support).

`parse_pr_view` is the single place that turns the raw `gh api graphql` stdout
into vizsuite's `PrView`. The runner (`SubprocessGhRunner`) only shells out; every
shape decision — nonzero exit, non-JSON, a null/absent pull request, a missing
scalar — lands here as a loud typed `VizError(ADAPTER_FAILURE)`, never a silent
default (mirrors workcli's bd/parse drift discipline). These tests drive the parser
directly on scripted `GhResult`s, so no `gh` binary is ever touched.
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
) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "baseRefOid": base_oid,
                        "headRefOid": head_oid,
                        "baseRefName": base_ref,
                        "changedFiles": changed_files,
                        "commits": {"totalCount": commit_count},
                    }
                }
            }
        }
    )


def test_parses_oids_ref_and_scalar_counts():
    from vizsuite.adapters.gh.parse import parse_pr_view

    result = GhResult(returncode=0, stdout=_graphql_stdout(), stderr="")

    pr = parse_pr_view(result, pr_number=7)

    assert pr.base_oid == "base000"
    assert pr.head_oid == "head111"
    assert pr.base_ref == "main"
    assert pr.changed_files == 2
    assert pr.commit_count == 3


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
    }
    stdout = json.dumps({"data": {"repository": {"pullRequest": pull_request}}})
    result = GhResult(returncode=0, stdout=stdout, stderr="")

    with pytest.raises(VizError) as exc_info:
        parse_pr_view(result, pr_number=7)

    assert exc_info.value.code == ErrorCode.ADAPTER_FAILURE
