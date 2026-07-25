"""Builders for model objects.

Every builder defaults to the boring case -- a clean, pushed, unmerged local
branch -- so each test states only the one fact it is about. A test that reads
`make_branch(merged=True)` is a test about merge handling; one that spells out
eleven fields is a test about nothing in particular.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gitclean.model import Branch, MergeEvidence, PullRequest, Survey, Worktree

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

_UNSET = "\x00unset"
"""Sentinel for timestamp arguments, because None is now a meaningful value:
`last_activity=None` means "git did not answer", which is a case tests must be
able to build. Defaulting on None would make that case unreachable."""


def iso(days_ago: float = 0) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def make_pr(
    *,
    number: int = 1,
    state: str = "OPEN",
    updated_at: str | None = None,
    head_oid: str = "0" * 40,
) -> PullRequest:
    # Defaults to the same SHA make_branch uses, so a PR built here covers its
    # branch's tip unless a test deliberately says otherwise.
    return PullRequest(
        number=number,
        state=state,
        url=f"https://example.test/pr/{number}",
        updated_at=updated_at if updated_at is not None else iso(1),
        head_oid=head_oid,
    )


def make_branch(
    name: str = "feat/thing",
    *,
    is_remote: bool = False,
    remote: str | None = None,
    last_activity: str | None = _UNSET,
    upstream: str | None = "origin/feat/thing",
    is_default: bool = False,
    is_current: bool = False,
    checked_out_at: str | None = None,
    unpushed_commits: int | None = 0,
    unmerged_commits: int | None = 1,
    merged: bool = False,
    merge_evidence: MergeEvidence = MergeEvidence.NONE,
    pr: PullRequest | None = None,
) -> Branch:
    return Branch(
        name=name,
        is_remote=is_remote,
        remote=remote,
        head="0" * 40,
        last_activity=iso(1) if last_activity == _UNSET else last_activity,
        upstream=upstream,
        is_default=is_default,
        is_current=is_current,
        checked_out_at=checked_out_at,
        unpushed_commits=unpushed_commits,
        unmerged_commits=unmerged_commits,
        merged=merged,
        merge_evidence=merge_evidence,
        pr=pr,
    )


def make_worktree(
    path: str = "/repo/wt",
    *,
    branch: str | None = "feat/thing",
    is_main: bool = False,
    locked: bool = False,
    prunable: bool = False,
    dirty_file_count: int | None = 0,
    untracked_file_count: int | None = 0,
    last_activity: str | None = _UNSET,
) -> Worktree:
    # Either count being None means git would not answer, which makes `dirty`
    # itself unknown -- the state a test reaches by passing None explicitly.
    unknown = dirty_file_count is None or untracked_file_count is None
    return Worktree(
        path=path,
        branch=branch,
        head="0" * 40,
        is_main=is_main,
        locked=locked,
        prunable=prunable,
        dirty=None if unknown else (dirty_file_count or 0) + (untracked_file_count or 0) > 0,
        dirty_file_count=dirty_file_count,
        untracked_file_count=untracked_file_count,
        last_activity=iso(1) if last_activity == _UNSET else last_activity,
    )


def make_survey(
    *,
    branches: tuple[Branch, ...] = (),
    worktrees: tuple[Worktree, ...] = (),
    current_branch: str | None = "main",
    base_ref: str = "origin/main",
    default_branch: str = "main",
    gh_error: str | None = None,
    warnings: tuple[str, ...] = (),
) -> Survey:
    return Survey(
        repo_root="/repo",
        git_common_dir="/repo/.git",
        base_ref=base_ref,
        default_branch=default_branch,
        current_branch=current_branch,
        gh_available=gh_error is None,
        gh_error=gh_error,
        worktrees=worktrees,
        branches=branches,
        warnings=warnings,
    )


@pytest.fixture
def now() -> datetime:
    return NOW
