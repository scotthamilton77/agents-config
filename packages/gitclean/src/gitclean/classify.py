"""Pure judgement: a Survey in, Targets out. No I/O, no subprocesses.

The rules here are the tool's opinion, so they are written to be argued with.
Two of them carry most of the weight:

**Uncommitted work is never abandoned.** A dirty worktree is ACTIVE no matter
how old its branch is. Age measures commits; it says nothing about a file
someone edited an hour ago on a branch untouched for a month, and treating
that tree as stale is how cleanup scripts eat work.

**A closed PR is a discard decision -- until it goes stale.** Closing a PR
unmerged is a human saying "drop this", which is what makes an unmerged branch
sweepable at all. But if commits landed on the branch *after* the PR closed,
the decision predates the work and no longer authorises anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from gitclean.model import (
    Branch,
    Disposition,
    MergeEvidence,
    Risk,
    Survey,
    Target,
    TargetKind,
    Worktree,
)
from gitclean.survey import idle_since

DEFAULT_IDLE_DAYS = 14

_MERGED_EVIDENCE = frozenset(
    {
        MergeEvidence.PR_MERGED,
        MergeEvidence.ANCESTOR,
        MergeEvidence.PATCH_EQUAL,
        MergeEvidence.SQUASH_EQUAL,
    }
)


def worktree_id(path: str) -> str:
    return f"worktree:{path}"


def branch_id(name: str) -> str:
    return f"branch:{name}"


def remote_branch_id(name: str) -> str:
    return f"remote:{name}"


def _discard_decision_is_current(branch: Branch) -> bool:
    """True when a closed-unmerged PR still speaks for the branch's contents.

    Commits pushed after the close mean the branch moved on since the human
    decided; the decision no longer covers what is there now."""
    if branch.merge_evidence is not MergeEvidence.PR_CLOSED_UNMERGED or branch.pr is None:
        return False
    if not branch.pr.updated_at or not branch.last_activity:
        return False
    return branch.last_activity <= branch.pr.updated_at


def classify_branch(
    branch: Branch,
    survey_data: Survey,
    *,
    now: datetime,
    idle_window: timedelta,
    local_names: frozenset[str],
) -> Target:
    reasons: list[str] = []
    kind = TargetKind.REMOTE_BRANCH if branch.is_remote else TargetKind.BRANCH
    ident = remote_branch_id(branch.name) if branch.is_remote else branch_id(branch.name)

    merged = branch.merge_evidence in _MERGED_EVIDENCE
    discarded = _discard_decision_is_current(branch)
    idle = idle_since(branch.last_activity, now, idle_window)

    if merged:
        reasons.append(f"merge proven by {branch.merge_evidence.value}")
    if branch.merge_evidence is MergeEvidence.PR_CLOSED_UNMERGED and branch.pr is not None:
        if discarded:
            reasons.append(f"PR #{branch.pr.number} closed unmerged; no commits since")
        else:
            reasons.append(
                f"PR #{branch.pr.number} closed unmerged, but the branch has commits "
                f"newer than the close -- the discard decision is stale"
            )
    if branch.pr is not None and branch.pr.state == "OPEN":
        reasons.append(f"PR #{branch.pr.number} is open")
    if branch.checked_out_at:
        reasons.append(f"checked out at {branch.checked_out_at}")
    if branch.unmerged_commits:
        reasons.append(f"{branch.unmerged_commits} commit(s) not in {survey_data.base_ref}")
    if not branch.is_remote:
        if branch.upstream is None:
            reasons.append("no upstream: never pushed")
        elif branch.unpushed_commits:
            reasons.append(f"{branch.unpushed_commits} commit(s) not on {branch.upstream}")

    disposition = _branch_disposition(
        branch, merged=merged, discarded=discarded, idle=idle, survey_data=survey_data
    )
    if disposition is Disposition.PROTECTED:
        reasons.append(_protected_reason(branch, survey_data))
    if disposition is Disposition.ABANDONED:
        reasons.append(f"no open PR, no merge evidence, idle since {branch.last_activity}")

    risk = _branch_risk(branch, merged=merged, discarded=discarded, local_names=local_names)
    if risk is not Risk.NONE:
        reasons.append(_risk_reason(branch, risk))

    return Target(
        id=ident,
        kind=kind,
        name=branch.name,
        disposition=disposition,
        risk=risk,
        reasons=tuple(reasons),
        last_activity=branch.last_activity,
        salvage_needed=risk is not Risk.NONE,
    )


def _protected_reason(branch: Branch, survey_data: Survey) -> str:
    if branch.is_default:
        return f"{branch.name} is the default branch"
    return f"{branch.name} is checked out in the current worktree ({survey_data.repo_root})"


def _risk_reason(branch: Branch, risk: Risk) -> str:
    if branch.is_remote:
        return (
            "deleting the remote ref discards commits the server keeps no reflog for"
            if risk is Risk.DATA_LOSS
            else "remote ref holds commits that survive only in the local copy"
        )
    return "commits here exist nowhere else; the reflog is the only fallback"


def _branch_disposition(
    branch: Branch,
    *,
    merged: bool,
    discarded: bool,
    idle: bool,
    survey_data: Survey,
) -> Disposition:
    if branch.is_default:
        return Disposition.PROTECTED
    if not branch.is_remote and branch.name == survey_data.current_branch:
        return Disposition.PROTECTED
    if branch.pr is not None and branch.pr.state == "OPEN":
        return Disposition.ACTIVE
    if merged or discarded:
        return Disposition.SAFE
    return Disposition.ABANDONED if idle else Disposition.ACTIVE


def _branch_risk(
    branch: Branch,
    *,
    merged: bool,
    discarded: bool,
    local_names: frozenset[str],
) -> Risk:
    if merged:
        return Risk.NONE
    if branch.is_remote:
        short = branch.name.split("/", 1)[1] if "/" in branch.name else branch.name
        if discarded:
            # A discarded branch whose local copy survives the deletion costs
            # nothing; without one, the server ref is the last copy and the
            # server keeps no reflog.
            return Risk.NONE if short in local_names else Risk.RECOVERABLE
        return Risk.DATA_LOSS
    if discarded:
        return Risk.NONE
    if branch.upstream is not None and branch.unpushed_commits == 0:
        return Risk.NONE
    return Risk.RECOVERABLE


def classify_worktree(
    worktree: Worktree,
    branch_targets: dict[str, Target],
    *,
    now: datetime,
    idle_window: timedelta,
) -> Target:
    reasons: list[str] = []
    ident = worktree_id(worktree.path)

    if worktree.is_main:
        reasons.append("main worktree: the repository itself")
        disposition, risk = Disposition.PROTECTED, Risk.NONE
    elif worktree.locked:
        reasons.append("locked; unlock it deliberately before it can be removed")
        disposition, risk = Disposition.PROTECTED, Risk.NONE
    elif worktree.prunable:
        reasons.append("directory is gone; only the administrative record remains")
        disposition, risk = Disposition.SAFE, Risk.NONE
    elif worktree.dirty:
        reasons.append(
            f"{worktree.dirty_file_count} modified and "
            f"{worktree.untracked_file_count} untracked file(s) exist only here -- "
            f"no commit, no reflog, no remote"
        )
        disposition, risk = Disposition.ACTIVE, Risk.DATA_LOSS
    else:
        # A clean worktree is a checkout and nothing more: removing it destroys
        # no content, so its risk is NONE and only its lifecycle is in question.
        # That question belongs to the branch it holds.
        risk = Risk.NONE
        held = branch_targets.get(branch_id(worktree.branch)) if worktree.branch else None
        if held is None:
            reasons.append("detached HEAD; no branch to inherit a verdict from")
            disposition = (
                Disposition.ABANDONED
                if idle_since(worktree.last_activity, now, idle_window)
                else Disposition.ACTIVE
            )
        else:
            disposition = (
                Disposition.ACTIVE
                if held.disposition is Disposition.PROTECTED
                else held.disposition
            )
            reasons.append(f"clean checkout of {worktree.branch} ({held.disposition.value})")

    return Target(
        id=ident,
        kind=TargetKind.WORKTREE,
        name=worktree.path,
        disposition=disposition,
        risk=risk,
        reasons=tuple(reasons),
        last_activity=worktree.last_activity,
        salvage_needed=risk is not Risk.NONE,
    )


def classify(
    survey_data: Survey,
    *,
    now: datetime,
    idle_days: int = DEFAULT_IDLE_DAYS,
) -> tuple[Target, ...]:
    """Every deletable target in the repo, judged. Order is worktrees first,
    then local branches, then remote branches -- the order deletion must
    follow, since a branch cannot be deleted while a worktree holds it."""
    idle_window = timedelta(days=idle_days)
    local_names = frozenset(b.name for b in survey_data.branches if not b.is_remote)

    branch_targets: dict[str, Target] = {}
    for branch in survey_data.branches:
        target = classify_branch(
            branch, survey_data, now=now, idle_window=idle_window, local_names=local_names
        )
        branch_targets[target.id] = target

    worktree_targets = [
        classify_worktree(w, branch_targets, now=now, idle_window=idle_window)
        for w in survey_data.worktrees
    ]

    locals_ = [t for t in branch_targets.values() if t.kind is TargetKind.BRANCH]
    remotes = [t for t in branch_targets.values() if t.kind is TargetKind.REMOTE_BRANCH]
    return (*worktree_targets, *locals_, *remotes)
