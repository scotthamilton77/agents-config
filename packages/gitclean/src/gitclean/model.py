"""Domain model: what gitclean surveys, how it judges, and what it emits.

Two verdicts, deliberately orthogonal, because collapsing them is what makes
hand-rolled cleanup dangerous:

``Disposition`` answers *is this still live work?* -- a lifecycle question,
answered from PR state, worktree occupancy, and idle time.

``Risk`` answers *would deleting this destroy the only copy?* -- a data
question, answered from what content exists where. A branch can be abandoned
(nobody will finish it) and still carry the only copy of its commits; a branch
can be active and carry no risk at all because everything is pushed.

Cleanup keys on both: the default sweep takes only ``SAFE`` + ``NONE``, and
``Risk`` is what ``--force`` overrides -- never ``Disposition.PROTECTED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Disposition(StrEnum):
    """Lifecycle verdict for one deletable target."""

    PROTECTED = "protected"
    """Never deletable, with or without --force: the default branch, the
    branch currently checked out, the main worktree, or a locked worktree."""

    SAFE = "safe"
    """Merge is proven, or a PR closed it unmerged: nothing is waiting on it."""

    ACTIVE = "active"
    """An open PR, or a live worktree, or activity inside the idle window."""

    ABANDONED = "abandoned"
    """No PR, no merge evidence, idle past the window. Reported for a human
    decision -- never swept by a bare --cleanup."""


class Risk(StrEnum):
    """Data-loss verdict for one deletable target."""

    NONE = "none"
    """Deleting destroys no content that does not exist elsewhere."""

    RECOVERABLE = "recoverable"
    """Unique content, but a copy survives the deletion -- e.g. a local branch
    fully pushed to its upstream. Restorable without the salvage bundle."""

    DATA_LOSS = "data_loss"
    """The only copy. Refused without --force; salvaged before deletion."""


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
    """gh reports the PR was closed without merging: explicit human
    abandonment of the branch, which makes it sweepable."""

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

    def as_json(self) -> dict[str, object]:
        return {
            "number": self.number,
            "state": self.state,
            "url": self.url,
            "updated_at": self.updated_at,
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
    dirty: bool
    dirty_file_count: int
    untracked_file_count: int
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
            "last_activity": self.last_activity,
        }


@dataclass(frozen=True, slots=True)
class Branch:
    name: str
    """Short name for a local branch (`feat/x`); `<remote>/<ref>` for a remote."""
    is_remote: bool
    remote: str | None
    head: str
    last_activity: str
    upstream: str | None
    is_default: bool
    is_current: bool
    checked_out_at: str | None
    """Path of the worktree holding this branch, if any."""
    unpushed_commits: int
    """Commits on this branch that its upstream does not have. 0 when there is
    no upstream is a lie, so `upstream is None` is reported separately."""
    unmerged_commits: int
    """Commits not reachable from the base tip."""
    merged: bool
    merge_evidence: MergeEvidence
    pr: PullRequest | None

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
        }


@dataclass(frozen=True, slots=True)
class Target:
    """One deletable thing, with both verdicts and the reasoning behind them."""

    id: str
    """Stable selector: `worktree:<path>`, `branch:<name>`, `remote:<r>/<ref>`."""
    kind: TargetKind
    name: str
    disposition: Disposition
    risk: Risk
    reasons: tuple[str, ...]
    """Why this disposition and risk, in reader-facing prose. The audit trail."""
    last_activity: str | None
    salvage_needed: bool

    def as_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "disposition": self.disposition.value,
            "risk": self.risk.value,
            "reasons": list(self.reasons),
            "last_activity": self.last_activity,
            "salvage_needed": self.salvage_needed,
        }


@dataclass(frozen=True, slots=True)
class Survey:
    """Everything read from git and gh in one pass, before any judgement."""

    repo_root: str
    git_common_dir: str
    base_ref: str
    default_branch: str
    current_branch: str | None
    gh_available: bool
    gh_error: str | None
    """Populated when gh is present but the PR query failed. A survey with no
    PR data downgrades every merge verdict to git-only evidence, which cannot
    see squash merges -- so this is reported, never swallowed."""
    worktrees: tuple[Worktree, ...]
    branches: tuple[Branch, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "repo_root": self.repo_root,
            "git_common_dir": self.git_common_dir,
            "base_ref": self.base_ref,
            "default_branch": self.default_branch,
            "current_branch": self.current_branch,
            "gh_available": self.gh_available,
            "gh_error": self.gh_error,
            "worktrees": [w.as_json() for w in self.worktrees],
            "branches": [b.as_json() for b in self.branches],
        }


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
    """A target the automatic sweep dropped, and why.

    An automatic sweep that quietly does less than the caller assumes reads as
    "everything was cleaned" when it was not. Every omission is named here."""

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

    ``remedy`` names the flag, but a refusal is a finding, not a formality:
    the blocked targets are listed so the caller can drop them from the
    selection instead of reaching for --force."""

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
