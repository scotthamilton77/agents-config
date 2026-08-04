"""Builders for model objects.

Every builder defaults to the boring case -- a clean, pushed, unmerged local
branch -- so each test states only the one fact it is about. A test that reads
`make_branch(merged=True)` is a test about merge handling; one that spells out
eleven fields is a test about nothing in particular.

One default is worth knowing before it surprises you: every branch and worktree
is built at the same commit. That is what makes a worktree pick up its branch's
merge evidence for free, and it also means a survey containing the trunk marks
that shared commit as the trunk's, which keeps everything else out of the
sweep. A test about anything but the trunk gives its branches distinct `head`
values.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gitclean.model import Branch, MergeEvidence, NotOffered, PullRequest, Survey, Worktree

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
    ref: str | None = None,
    probe_ref: str | None = None,
    ref_name: str | None = None,
    head: str = "0" * 40,
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
    pr_covers_tip: bool | str | None = _UNSET,
    probe_failures: tuple[str, ...] = (),
) -> Branch:
    # A PR built against this branch covers its tip, and one built at another
    # commit does not -- which is git answering, not declining to. A test about
    # the containment probe failing passes None and means it.
    covers = (pr is not None and pr.head_oid == head) if pr_covers_tip == _UNSET else pr_covers_tip
    # The three spellings the survey recovers from the ref path and the
    # configured remote list, neither of which a builder has. Composing them
    # from `name` is the fixture stating where it means the ref to live -- the
    # safe direction, and the one a test overrides when the point of the test
    # is that the three come apart.
    namespace = "refs/remotes/" if is_remote else "refs/heads/"
    within = name.removeprefix(f"{remote}/") if is_remote and remote else name
    return Branch(
        name=name,
        ref=ref if ref is not None else f"{namespace}{name}",
        probe_ref=probe_ref if probe_ref is not None else name,
        ref_name=ref_name if ref_name is not None else within,
        is_remote=is_remote,
        remote=remote,
        head=head,
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
        pr_covers_tip=covers,
        probe_failures=probe_failures,
    )


def make_worktree(
    path: str = "/repo/wt",
    *,
    head: str = "0" * 40,
    branch: str | None = "feat/thing",
    is_main: bool = False,
    locked: bool = False,
    prunable: bool = False,
    dirty_file_count: int | None = 0,
    untracked_file_count: int | None = 0,
    ignored_file_count: int | None = 0,
    last_activity: str | None = _UNSET,
) -> Worktree:
    # Any count being None means git would not answer, which makes `dirty`
    # itself unknown -- the state a test reaches by passing None explicitly.
    # Ignored files are counted but excluded from `dirty`, mirroring survey.
    counts = (dirty_file_count, untracked_file_count, ignored_file_count)
    if prunable:
        # Not a convenience. git reports prunable when the recorded path is
        # merely unreachable, so the survey never runs `status` against it and
        # records no counts at all. A fixture that left them at zero would
        # describe a worktree the survey cannot produce -- and would hide a
        # reason string rendering "None modified file(s)" as though something
        # had been measured.
        counts = (None, None, None)
    dirty_file_count, untracked_file_count, ignored_file_count = counts
    unknown = any(c is None for c in counts)
    return Worktree(
        path=path,
        branch=branch,
        head=head,
        is_main=is_main,
        locked=locked,
        prunable=prunable,
        dirty=None if unknown else (dirty_file_count or 0) + (untracked_file_count or 0) > 0,
        dirty_file_count=dirty_file_count,
        untracked_file_count=untracked_file_count,
        ignored_file_count=ignored_file_count,
        last_activity=iso(1) if last_activity == _UNSET else last_activity,
    )


def make_survey(
    *,
    branches: tuple[Branch, ...] = (),
    worktrees: tuple[Worktree, ...] = (),
    current_branch: str | None = "main",
    # A full ref path, as the survey resolves it: the short spelling reaches a
    # local branch of that name first, so it is not what goes into an argv.
    base_ref: str = "refs/remotes/origin/main",
    default_branch: str = "main",
    default_branch_known: bool = True,
    gh_error: str | None = None,
    pr_evidence_gap: str | None = None,
    branches_known: bool = True,
    worktrees_known: bool = True,
    dropped_refs: int = 0,
    dropped_worktrees: int = 0,
    worktrees_framed: bool = True,
    unsplit_refs: int = 0,
    # The boring case is a repository with one remote called origin, which is
    # what `base_ref` above already assumes. A test about a remote whose name
    # contains a slash, or about a repository with none, says so here.
    remotes: tuple[str, ...] = ("origin",),
    remotes_known: bool = True,
    not_offered: tuple[NotOffered, ...] = (),
    warnings: tuple[str, ...] = (),
) -> Survey:
    return Survey(
        repo_root="/repo",
        git_common_dir="/repo/.git",
        base_ref=base_ref,
        default_branch=default_branch,
        default_branch_known=default_branch_known,
        current_branch=current_branch,
        gh_available=gh_error is None,
        gh_error=gh_error,
        pr_evidence_gap=pr_evidence_gap,
        worktrees=worktrees,
        branches=branches,
        branches_known=branches_known,
        worktrees_known=worktrees_known,
        dropped_refs=dropped_refs,
        dropped_worktrees=dropped_worktrees,
        worktrees_framed=worktrees_framed,
        unsplit_refs=unsplit_refs,
        remotes=remotes,
        remotes_known=remotes_known,
        not_offered=not_offered,
        warnings=warnings,
    )


@pytest.fixture
def now() -> datetime:
    return NOW
