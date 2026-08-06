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
and the alternative costs work. Where it stops is the unknown that nothing
turns on: a question another tier has already answered is not restated as open
beside that answer, because a row saying both is wrong whichever half a reader
believes.

One thing here is not judgement: ``Counterpart``. It restates a relation the
survey already read -- which worktree holds which branch, which branch tracks
which server ref -- onto the row that has to carry it, because the target rows
are what a reader groups into a table and the relation is what makes a group.
It is assembled here for want of a better seam: nothing about it is opinion,
but the target is built here, and the alternative is a consumer recovering it
from a reason sentence by splitting on a delimiter those names may contain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitclean.model import (
    Branch,
    Counterpart,
    MergeEvidence,
    Survey,
    Target,
    TargetKind,
    Worktree,
)

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


def holder_unmeasured(survey_data: Survey) -> bool:
    """Whether "no worktree holds this branch" is a statement this survey is in
    no position to make.

    ``Branch.checked_out_at`` is filled from the worktree listing, so a None
    there answers the question only when that listing described every tree it
    has. A listing that failed produces the same None, and so does one carrying
    a block nothing could parse -- and both then read as a branch free of any
    checkout, which is the reading that hands a tree somebody is standing in to
    a reader looking for something to delete."""
    return not survey_data.worktrees_known or bool(survey_data.dropped_worktrees)


@dataclass(frozen=True, slots=True)
class PairingIndex:
    """The membership questions ``branch_pairing`` and ``worktree_pairing`` ask
    repeatedly, answered once per classification instead of once per row.

    Membership is not identity. A local branch and a ref on the server may
    carry the same short name, so ``local_branch_names`` and
    ``remote_branch_names`` stay two sets rather than one, each built with the
    same ``is_remote`` split the scans they replace tested inline -- losing
    that split here would let a local branch answer for the server's copy of a
    name it merely happens to share."""

    worktree_paths: frozenset[str]
    local_branch_names: frozenset[str]
    remote_branch_names: frozenset[str]


def pairing_index(survey_data: Survey) -> PairingIndex:
    """Built once per classification and threaded down to every row, rather
    than rescanning ``survey_data.worktrees`` and ``survey_data.branches`` once
    per branch or worktree."""
    return PairingIndex(
        worktree_paths=frozenset(w.path for w in survey_data.worktrees),
        local_branch_names=frozenset(b.name for b in survey_data.branches if not b.is_remote),
        remote_branch_names=frozenset(b.name for b in survey_data.branches if b.is_remote),
    )


def counterpart_worktree(branch: Branch, survey_data: Survey, index: PairingIndex) -> Counterpart:
    """The worktree holding this branch, if the survey can say."""
    holder = branch.checked_out_at
    if holder is None:
        return Counterpart(
            relation="worktree", name=None, id=None, known=not holder_unmeasured(survey_data)
        )
    listed = holder in index.worktree_paths
    return Counterpart(
        relation="worktree",
        name=holder,
        id=worktree_id(holder) if listed else None,
        known=True,
    )


def tracks_a_server_ref(branch: Branch) -> bool:
    """Whether what this branch tracks is a copy on a server.

    Asked of the upstream's full refname, because the short one cannot answer
    it: `git branch --set-upstream-to=main` records a local branch as the
    upstream, and a local branch may itself be named `origin/main`. Both
    shorten to a string that reads like a published ref."""
    return bool(branch.upstream_ref and branch.upstream_ref.startswith("refs/remotes/"))


def counterpart_upstream(branch: Branch, index: PairingIndex) -> Counterpart:
    """This branch's copy on the server, as the branch itself records it.

    Tracking nothing and tracking another local branch are one answer here, and
    it is a measured one: nothing names a copy on a server. A local upstream is
    a pairing made on this disk -- it says where to count commits from, not
    where any of them were published -- so reporting it as a server counterpart
    would assert a ref nobody has seen, and would spend the third state below on
    a copy that does not exist. What the branch does track is still said out
    loud, in that row's reasons.

    A None upstream is measured rather than missing: this row exists because
    the ref read produced it, and that read said the branch tracks nothing.
    What a named upstream does not promise is that the server still has it -- a
    ref the remote has since dropped is named here and has no row, which is what
    the absent `id` says and the name beside it stops from reading as "never
    pushed"."""
    upstream = branch.upstream
    if upstream is None or not tracks_a_server_ref(branch):
        return Counterpart(relation="upstream", name=None, id=None, known=True)
    listed = upstream in index.remote_branch_names
    return Counterpart(
        relation="upstream",
        name=upstream,
        id=remote_branch_id(upstream) if listed else None,
        known=True,
    )


def branch_pairing(
    branch: Branch, survey_data: Survey, index: PairingIndex
) -> tuple[Counterpart, ...]:
    """Nothing for a server ref. No worktree can hold one and it tracks nothing
    itself, so both relations run the other way -- from the local branch that
    names it as its upstream, which is how it joins that branch's group."""
    if branch.is_remote:
        return ()
    return (counterpart_worktree(branch, survey_data, index), counterpart_upstream(branch, index))


def worktree_pairing(worktree: Worktree, index: PairingIndex) -> tuple[Counterpart, ...]:
    """The branch this worktree has checked out.

    Measured either way: the listing states outright whether a branch is
    checked out here, so None is git answering rather than declining. The row
    for that branch can still be missing -- with no ref read there are no
    branch rows at all -- and a named branch with no `id` says that, which is a
    different thing from a detached checkout."""
    if worktree.branch is None:
        return (Counterpart(relation="branch", name=None, id=None, known=True),)
    listed = worktree.branch in index.local_branch_names
    return (
        Counterpart(
            relation="branch",
            name=worktree.branch,
            id=branch_id(worktree.branch) if listed else None,
            known=True,
        ),
    )


def unanswered_probes(branch: Branch, base_ref: str, *, proven: bool) -> tuple[str, ...]:
    """Reasons naming each count the read layer could not obtain.

    Kept beside the measurements rather than folded into the sweep rule, so
    each unknown renders on the row of the branch it was missing from while
    the sweep goes on deciding from the evidence tier.

    The merge sentence is suppressed once something else proved the merge. An
    unanswered count does not imply ``MergeEvidence.NONE``: the tiers are
    independent reads -- a pull request is answered by the forge, this count by
    `rev-list` -- so a branch can carry authoritative proof while that one
    probe failed, and the row would then call the merge unproven beside the
    tier that proved it. The unknown that can withhold a deletion is one in the
    tier authorising it, and this is not that; what is dropped here changed no
    outcome and contradicted the proof next to it.

    The unpushed sentence is not suppressed on those grounds and must not be. A
    merge proves these commits reached the base ref; it says nothing about
    whether this branch's own upstream ever received them, so that unknown
    stays true beside any proof and stays worth saying."""
    unknown: list[str] = []
    if branch.unmerged_commits is None and not proven:
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
    explanation.

    A tip git would not place gets its own sentence. Both outcomes decline the
    PR tier, but only one of them compared the two commits, and reporting the
    comparison that never happened points the reader at a difference between
    SHAs that nothing established."""
    pr = branch.pr
    if pr is None or pr.state not in {"MERGED", "CLOSED"}:
        return ()
    honoured = {MergeEvidence.PR_MERGED, MergeEvidence.PR_CLOSED_UNMERGED}
    if branch.merged or branch.merge_evidence in honoured or not pr.head_oid:
        return ()
    verb = "merged" if pr.state == "MERGED" else "closed"
    if branch.pr_covers_tip is None:
        return (
            f"git would not say whether PR #{pr.number}'s head at {pr.head_oid[:8]} contains "
            f"this branch's tip {branch.head[:8]}; whether that decision covers what is here "
            f"is unknown",
        )
    return (
        f"PR #{pr.number} was {verb} at {pr.head_oid[:8]}, which does not contain "
        f"this branch's tip {branch.head[:8]}; that decision does not cover what is here",
    )


def missing_pr_evidence(survey_data: Survey, *, proven: bool, saw_pr: bool) -> tuple[str, ...]:
    """Said on the row of anything the PR read could not speak for.

    ``gh_error`` and ``pr_evidence_gap`` are repository-wide, and a reader
    scanning rows cannot tell that the tier which sees squash merges never ran
    for this one: the row shows evidence `none`, which is also what four
    tiers running and finding nothing looks like.

    Suppressed once something else proved the merge, where the gap changed no
    outcome and the sentence would only compete with the proof beside it."""
    if proven:
        return ()
    if survey_data.gh_error:
        return (f"no pull-request evidence was read for this commit -- {survey_data.gh_error}",)
    if survey_data.pr_evidence_gap and not saw_pr:
        return (f"a pull request for this may not have been read -- {survey_data.pr_evidence_gap}",)
    return ()


def trunk(survey_data: Survey) -> tuple[frozenset[str], frozenset[str]]:
    """The refs and the commits a sweep must never take: the default branch and
    its counterpart on every configured remote.

    Both halves are load-bearing. Refs alone miss a trunk whose ref resolved but
    whose tip no surveyed branch happens to repeat; commits alone miss the
    counterpart -- the local trunk is an ancestor of the published one, which is
    a merge proof by the first question's own definition.

    These are **full ref paths**, because a caller-facing name is not an
    identity. `origin/main` spells the server's copy of the trunk, and it
    equally spells a local branch of that name -- a legal ref, not the trunk,
    and one its owner is entitled to delete. A set of those strings holds both
    and cannot tell them apart, so it protects the second one too and says `this
    is the trunk` about it in the field a reader checks immediately before
    deleting something. Ref paths distinguish them; nothing else does.

    Composing the counterpart by joining a configured remote to the branch name
    is the same operation the survey refuses to invert, and it is sound in this
    direction: building a path out of two known pieces cannot go wrong the way
    splitting one string into two guesses can.

    The ref merges are measured against needs no entry of its own: it is the
    default branch either locally or on `origin`, so it is already here
    whenever `origin` is a configured remote -- and when it is not, the survey
    could not say which remote its path belongs to and never offered it.

    Matching a commit costs the occasional branch parked exactly on the trunk
    tip: it stays in the report instead of being swept. That is the direction
    to be wrong in."""
    refs = {f"refs/heads/{survey_data.default_branch}"}
    refs.update(
        f"refs/remotes/{remote}/{survey_data.default_branch}" for remote in survey_data.remotes
    )
    commits = {b.head for b in survey_data.branches if b.ref in refs and b.head}
    return frozenset(refs), frozenset(commits)


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

    ``ref`` is the **full path** of the ref under judgement -- None for a
    detached worktree -- and ``commit`` is what it actually points at. Full
    paths, because this is where the trunk is recognised and a caller-facing
    name is not an identity: `origin/main` names the server's trunk and a local
    branch somebody made, and only one of those is the trunk. A worktree is
    judged on the commit it holds whether or not a branch names that commit, so
    a detached checkout needs no rule of its own: an orphan commit has no merge
    proof, and the first question stops it for the same reason it stops any
    other."""
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
    index: PairingIndex,
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
    reasons.extend(missing_pr_evidence(survey_data, proven=proven, saw_pr=branch.pr is not None))
    if branch.checked_out_at:
        reasons.append(f"checked out at {branch.checked_out_at}")
    elif not branch.is_remote and holder_unmeasured(survey_data):
        # Said out loud because the alternative is silence, and silence here
        # renders exactly like a branch nothing has checked out.
        reasons.append(
            "whether a worktree holds this branch was not established; the worktree listing "
            "did not describe every tree it has, so this is unknown rather than none"
        )
    if branch.unmerged_commits:
        reasons.append(f"{branch.unmerged_commits} commit(s) not in {survey_data.base_ref}")
    if not branch.is_remote:
        if branch.upstream is None:
            reasons.append("no upstream: never pushed")
        else:
            if not tracks_a_server_ref(branch):
                # The pairing above reports no server counterpart for this, which
                # is the truthful answer and also an absence -- and an absence is
                # indistinguishable from a branch that simply has no upstream.
                # The reader is told which one they are looking at here.
                reasons.append(
                    f"tracks the local branch {branch.upstream}, not a ref on a server; "
                    f"nothing here says whether these commits were pushed anywhere"
                )
            if branch.unpushed_commits:
                reasons.append(f"{branch.unpushed_commits} commit(s) not on {branch.upstream}")
    reasons.extend(unanswered_probes(branch, survey_data.base_ref, proven=proven))
    reasons.extend(branch.probe_failures)

    withheld = withheld_reason(
        ref=branch.ref,
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
        pairing=branch_pairing(branch, survey_data, index),
        merge_evidence=branch.merge_evidence,
        merge_proven=proven,
        sweepable=withheld is None,
        withheld=withheld,
        reasons=tuple(reasons),
        last_activity=branch.last_activity,
        # Carried forward rather than recovered from `name` downstream. The
        # survey is where the configured remote list was in hand, so it is the
        # only place the split could be made honestly; everything after this
        # would be guessing at a slash.
        remote=branch.remote if branch.is_remote else None,
        ref_name=branch.ref_name if branch.is_remote else None,
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
    index: PairingIndex,
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
    if not survey_data.branches_known:
        reasons.append(
            "no ref could be read in this repository, so nothing could have proved the commit "
            "it holds merged"
        )
    reasons.extend(missing_pr_evidence(survey_data, proven=evidence in MERGE_PROOF, saw_pr=False))
    if worktree.last_activity is None:
        reasons.append("no commit timestamp; this worktree's age is unknown")
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
    elif worktree.ignored_file_count is None:
        # A count nobody took renders exactly like a measured zero -- as
        # silence -- and the reader is then told nothing about what a sweep of
        # this tree would take with it.
        reasons.append(
            "how many ignored files would be deleted with it was not measured; a .env living "
            "only here would go unannounced"
        )

    withheld = withheld_reason(
        # A worktree only ever holds a local branch, so composing its path is
        # exact -- the direction that cannot go wrong.
        ref=None if worktree.branch is None else f"refs/heads/{worktree.branch}",
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
        pairing=worktree_pairing(worktree, index),
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
    index = pairing_index(survey_data)
    branch_targets = [
        classify_branch(
            b, survey_data, trunk_names=trunk_names, trunk_commits=trunk_commits, index=index
        )
        for b in survey_data.branches
    ]
    worktree_targets = [
        classify_worktree(
            w, survey_data, trunk_names=trunk_names, trunk_commits=trunk_commits, index=index
        )
        for w in survey_data.worktrees
    ]
    locals_ = [t for t in branch_targets if t.kind is TargetKind.BRANCH]
    remotes = [t for t in branch_targets if t.kind is TargetKind.REMOTE_BRANCH]
    return (*worktree_targets, *locals_, *remotes)
