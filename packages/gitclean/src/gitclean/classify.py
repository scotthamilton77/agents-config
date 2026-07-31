"""Pure judgement: a Survey in, Targets out. No I/O, no subprocesses.

One judgement is made here, and it is narrow: may an unattended sweep delete
this? Everything that used to answer *is anyone still using this?* is gone,
because nothing in a repository measures that. Age measures commits, not
intent. A clean working tree measures files, not consent. Deriving a lifecycle
verdict from either produced confident answers to a question the data could not
settle, and those answers authorised deletions.

What is left is ``withheld_reason``: six measured questions, each with an
answer a reader can check. A target that clears all six is provably merged and
provably not the trunk, and a bare ``--cleanup`` takes it. A target that fails
any one of them is reported, carrying the answer that stopped it, and only a
human naming it deletes it.

**An unknown is never evidence for deletion.** Any field the read layer left as
``None`` is a question git declined to answer; it renders as a stated unknown
on that target's own row instead of resolving to the convenient value. The rule
is one-directional on purpose: it costs the occasional branch left uncleaned,
and the alternative costs work.
"""

from __future__ import annotations

from pathlib import Path

from gitclean.model import Branch, MergeEvidence, Survey, Target, TargetKind, Worktree

MERGE_PROOF = frozenset(
    {
        MergeEvidence.PR_MERGED,
        MergeEvidence.ANCESTOR,
        MergeEvidence.PATCH_EQUAL,
        MergeEvidence.SQUASH_EQUAL,
    }
)
"""The tiers that prove a merge, and the whole of what authorises an unattended
deletion. A PR closed without merging is not in here: closing a PR says a
person stopped wanting the change, not that its commits exist anywhere else."""


def worktree_id(path: str) -> str:
    return f"worktree:{path}"


def branch_id(name: str) -> str:
    return f"branch:{name}"


def remote_branch_id(name: str) -> str:
    return f"remote:{name}"


def unanswered_probes(branch: Branch, base_ref: str) -> tuple[str, ...]:
    """Reasons naming each count the read layer could not obtain.

    Kept beside the measurements rather than folded into the sweep rule so the
    audit trail cannot drift from the behaviour: a branch whose merge count
    never came back carries ``MergeEvidence.NONE``, which is exactly what the
    first question refuses."""
    unknown: list[str] = []
    if branch.unmerged_commits is None:
        unknown.append(f"could not count commits missing from {base_ref}; merge state unproven")
    if branch.upstream is not None and branch.unpushed_commits is None:
        unknown.append(
            f"could not count commits missing from {branch.upstream}; "
            f"nothing proves these commits are pushed"
        )
    if branch.last_activity is None:
        unknown.append("no commit timestamp; this branch's age is unknown")
    return tuple(unknown)


def _uncovered_pr_reason(branch: Branch) -> tuple[str, ...]:
    """Said out loud when declining a PR verdict is what kept a branch out of
    the sweep. Otherwise the branch quietly stops being sweepable and the
    reader is left comparing SHAs by hand to find out why.

    Suppressed when a lower tier proved the merge anyway: the PR verdict was
    declined, but the branch *is* merged, and a coverage complaint next to
    `merge proven by squash_equal` reads as a contradiction rather than an
    explanation."""
    pr = branch.pr
    if pr is None or pr.state not in {"MERGED", "CLOSED"}:
        return ()
    honoured = {MergeEvidence.PR_MERGED, MergeEvidence.PR_CLOSED_UNMERGED}
    if branch.merged or branch.merge_evidence in honoured or not pr.head_oid:
        return ()
    verb = "merged" if pr.state == "MERGED" else "closed"
    return (
        f"PR #{pr.number} was {verb} at {pr.head_oid[:8]}, which does not contain "
        f"this branch's tip {branch.head[:8]}; that decision does not cover what is here",
    )


def trunk(survey_data: Survey) -> tuple[frozenset[str], frozenset[str]]:
    """The ref names and the commits a sweep must never take: the default
    branch, whatever merges are measured against, and each one's counterpart
    across the remote boundary.

    Both halves are load-bearing. Names alone miss that counterpart -- `main`
    and `origin/main` are different strings for the same trunk, and the local
    one is an ancestor of the published one, which is a merge proof by the
    first question's own definition. Commits alone miss a trunk whose ref
    resolved but whose tip no surveyed branch happens to repeat.

    Matching a commit costs the occasional branch parked exactly on the trunk
    tip: it stays in the report instead of being swept. That is the direction
    to be wrong in."""
    remotes = {b.remote for b in survey_data.branches if b.remote}
    names: set[str] = set()
    for candidate in (survey_data.default_branch, survey_data.base_ref):
        prefix, _, rest = candidate.partition("/")
        local = rest if prefix in remotes and rest else candidate
        names.add(local)
        names.update(f"{remote}/{local}" for remote in remotes)
    commits = {b.head for b in survey_data.branches if b.name in names and b.head}
    return frozenset(names), frozenset(commits)


def withheld_reason(
    *,
    ref: str | None,
    commit: str,
    evidence: MergeEvidence,
    dirt: str | None,
    trunk_names: frozenset[str],
    trunk_commits: frozenset[str],
    default_branch_known: bool,
    is_remote: bool,
    is_invoking_worktree: bool,
) -> str | None:
    """Why an unattended sweep will not take this, or None when it may.

    Six questions, each answered from something measured rather than inferred,
    and the first that answers no is what the report shows. They are ordered by
    how specific the answer is: a branch nothing proved merged is told that,
    rather than told the repository has no verified trunk.

    ``ref`` is the branch under judgement -- None for a detached worktree --
    and ``commit`` is what it actually points at. A worktree is judged on the
    commit it holds whether or not a branch names that commit, so a detached
    checkout needs no rule of its own: an orphan commit has no merge proof, and
    the first question stops it for the same reason it stops any other."""
    if evidence not in MERGE_PROOF:
        return f"no merge proof for this commit (evidence: {evidence.value})"
    if not default_branch_known:
        return (
            "this repository's default branch could not be verified, so nothing here can "
            "be told apart from the trunk"
        )
    if ref is not None and ref in trunk_names:
        return "this is the trunk, or the ref every merge here is measured against"
    if commit in trunk_commits:
        # Deliberately a different sentence from the one above. A branch cut
        # from the trunk and never committed to sits exactly on its tip, and
        # telling its owner "this is the trunk" is false -- it is a different
        # ref that happens to point at the same commit. Both are held back,
        # but a report that misnames what it is looking at is the defect this
        # design exists to remove, so the two cases say what they mean.
        return (
            "this points at the trunk's tip, so deleting it cannot be told apart from "
            "deleting the trunk"
        )
    if dirt is not None:
        return dirt
    if is_remote:
        return "a ref on the server has no reflog, so it is deleted only when named"
    if is_invoking_worktree:
        return "this is the worktree the run is executing in"
    return None


def classify_branch(
    branch: Branch,
    survey_data: Survey,
    *,
    trunk_names: frozenset[str],
    trunk_commits: frozenset[str],
) -> Target:
    reasons: list[str] = []
    kind = TargetKind.REMOTE_BRANCH if branch.is_remote else TargetKind.BRANCH
    ident = remote_branch_id(branch.name) if branch.is_remote else branch_id(branch.name)
    proven = branch.merge_evidence in MERGE_PROOF

    if proven:
        reasons.append(f"merge proven by {branch.merge_evidence.value}")
    if branch.merge_evidence is MergeEvidence.PR_CLOSED_UNMERGED and branch.pr is not None:
        reasons.append(
            f"PR #{branch.pr.number} was closed without merging; its commits are still only here"
        )
    if branch.pr is not None and branch.pr.state == "OPEN":
        reasons.append(f"PR #{branch.pr.number} is open")
    reasons.extend(_uncovered_pr_reason(branch))
    if branch.checked_out_at:
        reasons.append(f"checked out at {branch.checked_out_at}")
    if branch.unmerged_commits:
        reasons.append(f"{branch.unmerged_commits} commit(s) not in {survey_data.base_ref}")
    if not branch.is_remote:
        if branch.upstream is None:
            reasons.append("no upstream: never pushed")
        elif branch.unpushed_commits:
            reasons.append(f"{branch.unpushed_commits} commit(s) not on {branch.upstream}")
    reasons.extend(unanswered_probes(branch, survey_data.base_ref))

    withheld = withheld_reason(
        ref=branch.name,
        commit=branch.head,
        evidence=branch.merge_evidence,
        dirt=None,
        trunk_names=trunk_names,
        trunk_commits=trunk_commits,
        default_branch_known=survey_data.default_branch_known,
        is_remote=branch.is_remote,
        is_invoking_worktree=False,
    )
    return Target(
        id=ident,
        kind=kind,
        name=branch.name,
        merge_evidence=branch.merge_evidence,
        merge_proven=proven,
        sweepable=withheld is None,
        withheld=withheld,
        reasons=tuple(reasons),
        last_activity=branch.last_activity,
    )


def held_dirt(worktree: Worktree) -> str | None:
    """What this tree holds that exists nowhere else, or None when git said
    plainly that it holds nothing.

    Only a measured zero clears this, and `prunable` is not one. git reports
    prunable when the recorded path is merely unreachable from here -- moved
    aside, or on a volume nothing has mounted -- and the tree, with its
    afternoon of uncommitted work, is sitting intact wherever it went."""
    if worktree.prunable:
        return (
            "git reports this worktree prunable, which means only that its recorded path is "
            "unreachable from here; whether it holds uncommitted work is unknown"
        )
    if worktree.dirty is None:
        return "git could not read this tree's status, so what it holds is unknown"
    if worktree.dirty:
        return (
            f"{worktree.dirty_file_count} modified and {worktree.untracked_file_count} "
            f"untracked file(s) exist only here -- no commit, no reflog, no remote"
        )
    return None


def commit_proof(commit: str, branches: tuple[Branch, ...]) -> MergeEvidence:
    """Merge evidence for a commit, whatever ref happens to name it.

    A worktree's HEAD is its branch's tip when it has a branch and a bare
    commit when it does not, so asking about the commit answers the attached
    and the detached case with the same question. Nothing is inherited: a
    worktree does not take a verdict from the branch it holds, it takes the
    evidence about the commit that branch points at -- which is the commit the
    worktree holds. A commit no ref proves merged has no proof, and that is an
    answer rather than a gap."""
    return next(
        (
            b.merge_evidence
            for b in branches
            if b.head == commit and b.merge_evidence in MERGE_PROOF
        ),
        MergeEvidence.NONE,
    )


def classify_worktree(
    worktree: Worktree,
    survey_data: Survey,
    *,
    trunk_names: frozenset[str],
    trunk_commits: frozenset[str],
) -> Target:
    evidence = commit_proof(worktree.head, survey_data.branches)
    dirt = held_dirt(worktree)
    short = worktree.head[:8] or "an unknown commit"

    reasons: list[str] = [
        f"holds {worktree.branch} at {short}" if worktree.branch else f"detached HEAD at {short}"
    ]
    if worktree.branch is None and worktree.last_activity:
        # Said out loud because the number is not what its name suggests. A
        # detached checkout has no branch to date it from, so the date is the
        # commit's -- and a worktree created a minute ago at a two-year-old tag
        # reads as two years idle. Nothing decides anything on it any more, but
        # a reader who saw only the date would draw the conclusion the old
        # lifecycle verdict used to draw for them.
        reasons.append(
            f"dated {worktree.last_activity[:10]} from the commit it holds, "
            f"which is not when this checkout was made or last touched"
        )
    if worktree.is_main:
        reasons.append("the repository's main worktree")
    if worktree.locked:
        reasons.append("locked; git refuses to remove it until it is unlocked")
    if evidence in MERGE_PROOF:
        reasons.append(f"the commit it holds is merged, proven by {evidence.value}")
    if dirt is not None:
        reasons.append(dirt)
    # Named on every worktree that carries any, sweepable or not: ignored
    # content does not keep a worktree out of the sweep, so this reason is the
    # only place the reader learns it is about to go.
    if worktree.ignored_file_count:
        reasons.append(
            f"{worktree.ignored_file_count} ignored file(s) would be deleted with it "
            f"(caches and virtualenvs regenerate; a .env living only here would not)"
        )

    withheld = withheld_reason(
        ref=worktree.branch,
        commit=worktree.head,
        evidence=evidence,
        dirt=dirt,
        trunk_names=trunk_names,
        trunk_commits=trunk_commits,
        default_branch_known=survey_data.default_branch_known,
        is_remote=False,
        is_invoking_worktree=Path(worktree.path) == Path(survey_data.repo_root),
    )
    return Target(
        id=worktree_id(worktree.path),
        kind=TargetKind.WORKTREE,
        name=worktree.path,
        merge_evidence=evidence,
        merge_proven=evidence in MERGE_PROOF,
        sweepable=withheld is None,
        withheld=withheld,
        reasons=tuple(reasons),
        last_activity=worktree.last_activity,
    )


def classify(survey_data: Survey) -> tuple[Target, ...]:
    """Every deletable target in the repo, measured. Order is worktrees first,
    then local branches, then remote branches -- the order deletion must
    follow, since a branch cannot be deleted while a worktree holds it."""
    trunk_names, trunk_commits = trunk(survey_data)
    branch_targets = [
        classify_branch(b, survey_data, trunk_names=trunk_names, trunk_commits=trunk_commits)
        for b in survey_data.branches
    ]
    worktree_targets = [
        classify_worktree(w, survey_data, trunk_names=trunk_names, trunk_commits=trunk_commits)
        for w in survey_data.worktrees
    ]
    locals_ = [t for t in branch_targets if t.kind is TargetKind.BRANCH]
    remotes = [t for t in branch_targets if t.kind is TargetKind.REMOTE_BRANCH]
    return (*worktree_targets, *locals_, *remotes)
