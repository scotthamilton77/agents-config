"""Domain model: what gitclean measures, and the one thing it concludes.

There is a single conclusion in here, and its narrowness is the safety
property. ``Target.merge_evidence`` records how -- or whether -- a merge was
proven, and ``Target.sweepable`` says whether that proof plus a handful of
measured facts lets an unattended sweep take the target. Everything else is
measurement: commit dates, file counts, upstream state, PR number and state.
No lifecycle verdict is derived from any of it. "Abandoned" is a claim about
whether a person still wants the work, and nothing in a repository measures
that.

Proving *deleting this is safe* is a total function over every repository
state that exists -- detached HEADs, prunable records, unmounted volumes, refs
named ``-m`` -- and a gap in it costs somebody's work. Proving *this is merged*
is partial: an unproven target simply appears in the report with ``withheld``
saying what stopped it, and a human who wants it gone names it. A gap there
costs a leftover branch.

A second commitment runs through the field types: **every fact read from git is
optional, and ``None`` means "the probe did not answer".** It does not mean
zero, clean, or absent. A tool that deletes things must be able to say "I do
not know", because the alternative -- defaulting an unanswered question to the
value that authorises deletion -- turns every transient git failure into data
loss. Judgement treats ``None`` as the conservative answer, never the
convenient one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TargetKind(StrEnum):
    WORKTREE = "worktree"
    BRANCH = "branch"
    REMOTE_BRANCH = "remote_branch"


class MergeEvidence(StrEnum):
    """How a merge was proven. Recorded because the *reason* is what a reader
    needs to trust a deletion -- and because ANCESTOR alone is the check that
    lies under squash merges."""

    PR_MERGED = "pr_merged"
    """gh reports a merged pull request for this head ref. Authoritative, and
    the only signal that survives a squash merge intact."""

    PR_CLOSED_UNMERGED = "pr_closed_unmerged"
    """gh reports the PR was closed without merging. A reported fact and
    nothing more: the commits are still only here, so this authorises no
    deletion. Reading it as one deleted branches whose PR was closed while the
    work continued on them."""

    ANCESTOR = "ancestor"
    """Reachable from the base tip. True merges only."""

    PATCH_EQUAL = "patch_equal"
    """Every commit has a patch-id already in base -- rebase or cherry-pick."""

    SQUASH_EQUAL = "squash_equal"
    """The branch's whole tree, replayed as one commit onto the merge base,
    has a patch-id present in base. This is what catches squash merges, which
    ANCESTOR and PATCH_EQUAL both miss."""

    NONE = "none"
    """No merge could be proven. Not the same as 'not merged' -- see the
    `gh_available` flag on the survey."""


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    state: str
    """OPEN | MERGED | CLOSED, verbatim from gh."""
    url: str
    updated_at: str
    head_oid: str = ""
    """The commit this PR's head ref pointed at. A PR's state describes *that*
    commit, not whatever the branch of the same name happens to point at now,
    so this is what binds the verdict to content."""

    def as_json(self) -> dict[str, object]:
        return {
            "number": self.number,
            "state": self.state,
            "url": self.url,
            "updated_at": self.updated_at,
            "head_oid": self.head_oid,
        }


@dataclass(frozen=True, slots=True)
class Worktree:
    path: str
    branch: str | None
    """None when detached HEAD."""
    head: str
    is_main: bool
    locked: bool
    prunable: bool
    dirty: bool | None
    """None when git could not stat the tree. Unknown, NOT clean -- an
    unreadable worktree is the one most likely to be holding something."""
    dirty_file_count: int | None
    untracked_file_count: int | None
    ignored_file_count: int | None
    """Reported, but deliberately NOT part of ``dirty``.

    Ignored content is overwhelmingly build detritus -- caches, virtualenvs,
    coverage files -- that regenerates for free. Treating it as work at risk
    would keep almost every finished worktree out of the sweep, replacing an
    automatic cleanup with a manual triage, which costs far more than it saves.

    The accepted trade: a sweep of an already-merged worktree deletes its
    ignored files too, so a `.env` living only there goes with it. The count is
    surfaced in the report and in the target's reasons so that consequence is
    visible before anyone runs cleanup."""
    last_activity: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "path": self.path,
            "branch": self.branch,
            "head": self.head,
            "is_main": self.is_main,
            "locked": self.locked,
            "prunable": self.prunable,
            "dirty": self.dirty,
            "dirty_file_count": self.dirty_file_count,
            "untracked_file_count": self.untracked_file_count,
            "ignored_file_count": self.ignored_file_count,
            "last_activity": self.last_activity,
        }


@dataclass(frozen=True, slots=True)
class Branch:
    name: str
    """Short name for a local branch (`feat/x`); `<remote>/<ref>` for a remote."""
    is_remote: bool
    remote: str | None
    head: str
    last_activity: str | None
    upstream: str | None
    is_default: bool
    is_current: bool
    checked_out_at: str | None
    """Path of the worktree holding this branch, if any."""
    unpushed_commits: int | None
    """Commits on this branch that its upstream does not have. None means the
    count was not obtained -- either there is no upstream to count against
    (see `upstream`, which distinguishes the two) or the count failed. Zero
    would claim "fully pushed" in both cases, which is a lie in both."""
    unmerged_commits: int | None
    """Commits not reachable from the base tip. None when the count failed --
    which must never be read as 'none, therefore merged'."""
    merged: bool
    merge_evidence: MergeEvidence
    pr: PullRequest | None
    pr_covers_tip: bool | None
    """Whether what the PR decided accounts for this tip. None when no PR was
    read, or when git would not place the two commits relative to each other --
    which is routine, since the merged commit is frequently absent locally once
    the remote branch is gone. False is git answering "no"; None is git not
    answering, and a report that prints the first sentence for the second case
    states a comparison nobody made."""
    probe_failures: tuple[str, ...]
    """The merge probes that errored instead of answering, in reader-facing
    prose.

    A tier that could not run leaves ``merge_evidence`` at ``none``, which
    reads as "nothing proved a merge" -- true, but indistinguishable from
    "every tier ran and none of them fired". These say which question went
    unasked, and they travel on the branch so the answer lands on its own row
    rather than only in the survey's warnings."""

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "is_remote": self.is_remote,
            "remote": self.remote,
            "head": self.head,
            "last_activity": self.last_activity,
            "upstream": self.upstream,
            "is_default": self.is_default,
            "is_current": self.is_current,
            "checked_out_at": self.checked_out_at,
            "unpushed_commits": self.unpushed_commits,
            "unmerged_commits": self.unmerged_commits,
            "merged": self.merged,
            "merge_evidence": self.merge_evidence.value,
            "pr": self.pr.as_json() if self.pr else None,
            "pr_covers_tip": self.pr_covers_tip,
            "probe_failures": list(self.probe_failures),
        }


@dataclass(frozen=True, slots=True)
class Target:
    """One deletable thing: what was measured about it, and whether an
    unattended sweep may take it."""

    id: str
    """Stable selector: `worktree:<path>`, `branch:<name>`, `remote:<r>/<ref>`."""
    kind: TargetKind
    name: str
    merge_evidence: MergeEvidence
    merge_proven: bool
    """True when the evidence is one of the tiers that actually prove a merge.

    Reported, not acted on: ``sweepable`` is what the sweep reads. This is the
    same question collapsed to one field for a caller filtering the envelope,
    and keeping it beside the tier rather than folded into it lets a reported
    fact -- a PR closed without merging -- travel without authorising
    anything."""
    sweepable: bool
    """True when a bare `--cleanup` may take this unattended."""
    withheld: str | None
    """When not sweepable, the measured reason, in the prose a reader would use
    to check it. Never a claim about whether anyone still wants the work."""
    reasons: tuple[str, ...]
    """Everything measured about this target, in reader-facing prose. The audit
    trail, and it stands whether or not the target is sweepable."""
    last_activity: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "merge_evidence": self.merge_evidence.value,
            "merge_proven": self.merge_proven,
            "sweepable": self.sweepable,
            "withheld": self.withheld,
            "reasons": list(self.reasons),
            "last_activity": self.last_activity,
        }


@dataclass(frozen=True, slots=True)
class Survey:
    """Everything read from git and gh in one pass, before any judgement."""

    repo_root: str
    git_common_dir: str
    base_ref: str
    default_branch: str
    default_branch_known: bool
    """False when the name above is a guess nothing confirmed.

    A run that cannot resolve the trunk cannot tell it apart from cruft, so
    while this is False nothing is swept unattended. Naming a target still
    works: the caller knows what they are pointing at."""
    current_branch: str | None
    gh_available: bool
    gh_error: str | None
    """Populated when gh is present but the PR query failed. A survey with no
    PR data downgrades every merge verdict to git-only evidence, which cannot
    see squash merges -- so this is reported, never swallowed."""
    pr_evidence_gap: str | None
    """Populated when PR data was read but is known to be short of complete --
    a truncated list, an entry gh described in terms this does not parse.

    Distinct from ``gh_error``, which means there is no PR data at all. This
    one says the index answers for some branches and not others, and nothing
    in it identifies which, so every branch it could not speak for says so on
    its own row."""
    worktrees: tuple[Worktree, ...]
    branches: tuple[Branch, ...]
    branches_known: bool
    """False when the ref read itself failed.

    ``branches`` is then empty, and an empty list of refs is also what a
    repository with nothing but a trunk produces. The difference matters to
    every worktree row: with no refs read, nothing *could* have proved the
    commit a worktree holds merged, and the row has to say that rather than
    report an absence of proof as though the question had been asked."""
    warnings: tuple[str, ...] = ()
    """Every probe that did not answer, in reader-facing prose.

    A survey that could not read part of the repository is still a survey --
    it just describes less than the caller assumes. Discarding these is how a
    report becomes confidently incomplete, so they travel with the data and
    are hoisted to the top of the output envelope."""

    def as_json(self) -> dict[str, object]:
        return {
            "repo_root": self.repo_root,
            "git_common_dir": self.git_common_dir,
            "base_ref": self.base_ref,
            "default_branch": self.default_branch,
            "default_branch_known": self.default_branch_known,
            "current_branch": self.current_branch,
            "gh_available": self.gh_available,
            "gh_error": self.gh_error,
            "pr_evidence_gap": self.pr_evidence_gap,
            "warnings": list(self.warnings),
            "worktrees": [w.as_json() for w in self.worktrees],
            "branches": [b.as_json() for b in self.branches],
            "branches_known": self.branches_known,
        }

    def all_warnings(self) -> tuple[str, ...]:
        """Every degradation in one list, gh included.

        ``gh_error`` stays a distinct field because "PR data is missing" has a
        specific consequence -- squash merges become invisible -- that a reader
        may want to branch on. This is the flat channel for a reader who only
        needs to know that something did not answer."""
        return (*((self.gh_error,) if self.gh_error else ()), *self.warnings)


@dataclass(frozen=True, slots=True)
class Anomaly:
    """An unexpected result, carried back with enough context to remediate.

    ``transcript`` is the verbatim argv + stdout + stderr of the command that
    surprised us. It is the whole point of the type: an agent reading this
    must not have to re-run anything to know what happened."""

    stage: str
    target_id: str | None
    message: str
    transcript: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "target_id": self.target_id,
            "message": self.message,
            "transcript": list(self.transcript),
        }


@dataclass(frozen=True, slots=True)
class SalvageRecord:
    target_id: str
    kind: str
    path: str
    verified: bool
    detail: str

    def as_json(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "kind": self.kind,
            "path": self.path,
            "verified": self.verified,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Deletion:
    target_id: str
    kind: TargetKind
    name: str
    deleted: bool
    verified: bool
    detail: str

    def as_json(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "kind": self.kind.value,
            "name": self.name,
            "deleted": self.deleted,
            "verified": self.verified,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Skipped:
    """A target the sweep selected and then dropped, and why.

    Distinct from ``Target.withheld``, which says why a target never entered
    the sweep at all. This is the narrower case: the target qualified, and
    something about the rest of the plan pushed it back out -- a branch whose
    holding worktree is not also going. A run that quietly does less than the
    caller assumes reads as "everything was cleaned" when it was not, so every
    such omission is named here."""

    target_id: str
    name: str
    reason: str

    def as_json(self) -> dict[str, object]:
        return {"target_id": self.target_id, "name": self.name, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Plan:
    """A resolved intention to delete, ordered so dependants go first."""

    targets: tuple[Target, ...]
    salvage_dir: str | None
    dry_run: bool
    skipped: tuple[Skipped, ...] = field(default_factory=tuple)

    def as_json(self) -> dict[str, object]:
        return {
            "targets": [t.as_json() for t in self.targets],
            "salvage_dir": self.salvage_dir,
            "dry_run": self.dry_run,
            "skipped": [s.as_json() for s in self.skipped],
        }


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refusal to proceed, and exactly what would let the caller proceed.

    Refusals are few and narrow, because a named target is an authorisation
    rather than a proposal. What is left answers something the caller could not
    have answered themselves -- a name matching nothing, a name matching two
    things, a deletion git itself will reject. ``blocked`` lists the targets so
    they can be dropped from the selection rather than argued with."""

    code: str
    message: str
    blocked: tuple[Target, ...] = field(default_factory=tuple)
    remedy: str = ""

    def as_json(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "blocked": [t.as_json() for t in self.blocked],
            "remedy": self.remedy,
        }
