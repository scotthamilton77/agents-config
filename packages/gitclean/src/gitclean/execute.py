"""Salvage, delete, verify. The only stage that changes anything.

Three commitments shape this module:

**Salvage is retained only where no reflog exists**, which is a ref on the
server. A local branch deleted with `-D` leaves its commits in the reflog for
git's configured expiry, and a worktree is removed by git itself, which refuses
while the tree holds anything uncommitted. Where salvage does run, it precedes
the deletion and a bundle that will not verify aborts it. Verifying is the
weaker half: a bundle of a remote-tracking ref verifies cleanly and clones back
an empty repository, so what the archive has to be is one the restore command
printed beside it actually opens.

**Every deletion is verified by re-asking git.** A zero exit code is a claim,
not a fact -- `git push --delete` in particular can exit 0 against a ref the
server kept. So the ref is queried again afterwards, and a survivor becomes an
anomaly rather than a line in the success list.

**Anomalies carry the transcript.** Whoever reads this output must be able to
remediate without re-running anything, so the argv, exit code, and both
streams of the surprising command travel with the finding.
"""

from __future__ import annotations

import hashlib
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gitclean.model import Anomaly, Deletion, Plan, SalvageRecord, Survey, Target, TargetKind
from gitclean.ports import CommandPort

SALVAGE_PREFIX = "gitclean-salvage"
"""Where the scratch branch a bundle is taken from lives. Namespaced so the
name a human would have used stays theirs, and so a ref left behind by an
interrupted run says plainly what made it."""


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    deletions: tuple[Deletion, ...]
    salvages: tuple[SalvageRecord, ...]
    anomalies: tuple[Anomaly, ...]
    salvage_dir: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "deletions": [d.as_json() for d in self.deletions],
            "salvages": [s.as_json() for s in self.salvages],
            "anomalies": [a.as_json() for a in self.anomalies],
            "salvage_dir": self.salvage_dir,
        }

    @property
    def ok(self) -> bool:
        return not self.anomalies


def git_argv(*command: str, name: str | None = None) -> list[str]:
    """The only place a name out of the repository is put into a git argv.

    A repo-derived name can be spelled exactly like an option. `refs/heads/-m`
    is a legal ref -- `git branch` will not create one, but `update-ref` will
    and a remote can push one -- and `git branch -D -m` is a rename, not a
    deletion. Two spellings survive that, and which one applies is a property
    of the name rather than of the caller, so it is decided here:

    - a full `refs/...` path, which no git command parses as an option, and
    - the `--` terminator, for names that have to stay short.

    Both exist because `bundle create` hands its arguments to rev-list, where
    `--` introduces a pathspec: terminating there yields `Refusing to create
    empty bundle` rather than protection. `branch -D` is the mirror image --
    it rejects a full ref path and takes only the short name -- so neither
    spelling covers every call site and neither can be the single rule.

    Passing through one constructor is what makes that impossible to forget: a
    new call site has nowhere else to put the name. Commands carrying no
    repo-derived name come through here too, so the rule is "every git call in
    this module", which a test can check -- rather than "every git call that a
    reader judged to carry a name", which is the judgement that missed two."""
    if name is None:
        return list(command)
    if name.startswith("refs/"):
        return [*command, name]
    return [*command, "--", name]


def slug(name: str) -> str:
    """Filesystem-safe, collision-free stand-in for a ref or path.

    The readable part alone is not injective: `origin/feat/a` and
    `origin-feat-a` flatten to the same string, as do `feat+x` and `feat-x`.
    Two targets sharing a filename means the second verified salvage silently
    overwrites the first and both deletions proceed -- one of them having
    destroyed the only copy. The digest restores injectivity; the readable
    prefix is kept so a human can still find their work."""
    cleaned = "".join(c if c.isalnum() or c in "-._" else "-" for c in name)
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned.strip('-') or 'target'}-{digest}"


def default_salvage_dir(survey_data: Survey, now: datetime) -> str:
    """Inside the common git dir: it is never committed, it is not inside any
    worktree being removed, and it travels with the repository."""
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return str(Path(survey_data.git_common_dir) / "gitclean-salvage" / stamp)


class Executor:
    def __init__(self, port: CommandPort, survey_data: Survey, *, cwd: Path | None = None) -> None:
        self._port = port
        self._survey = survey_data
        self._cwd = cwd
        self._anomalies: list[Anomaly] = []
        self._salvages: list[SalvageRecord] = []

    # -- salvage ------------------------------------------------------------

    def _salvage_remote_branch(self, target: Target, salvage_dir: Path) -> bool:
        """Bundle a server ref before deleting it. The one place salvage is
        still earned: `push --delete` is irreversible for everyone fetching and
        the server keeps no reflog, so there is no undo to fall back on.

        What is bundled is a branch this run makes and then removes, not the
        remote-tracking ref itself. A bundle of `refs/remotes/<remote>/<name>`
        holds no head: `git bundle verify` passes on it and `git clone` of it
        produces an empty repository, so the archive that authorised the
        deletion turns out to hold nothing anyone can take back. `git branch`
        refuses a name already in use, which stops the scratch ref from trading
        the server's copy for somebody else's work.

        Bundling the full history rather than `base..branch` costs disk and
        buys a bundle that clones standalone -- the right trade when the
        alternative is unrecoverable work."""
        ref = target.name
        bundle = salvage_dir / f"{slug(ref)}.bundle"
        branch = f"{SALVAGE_PREFIX}/{slug(ref)}"
        self._port.write_text(salvage_dir / ".gitclean-keep", "")

        copied = self._port.git(
            git_argv("branch", "--no-track", branch, name=f"refs/remotes/{ref}"), cwd=self._cwd
        )
        if not copied.ok:
            self._record(
                "salvage",
                target.id,
                f"could not take a local copy of {ref} to bundle; deletion aborted",
                copied.transcript(),
            )
            return False
        try:
            return self._bundle(target, bundle, branch)
        finally:
            # Unconditional: a scratch branch left behind is a branch nobody
            # created showing up in the next report, and on the failure paths
            # it is the deletion's abort that leaves it there.
            discarded = self._port.git(git_argv("branch", "-D", name=branch), cwd=self._cwd)
            if not discarded.ok:
                self._record(
                    "salvage",
                    target.id,
                    f"the scratch branch {branch} this run created could not be removed; "
                    f"it holds the same commits as the bundle and is safe to delete",
                    discarded.transcript(),
                )

    def _bundle(self, target: Target, bundle: Path, branch: str) -> bool:
        """Write the archive and record the route back out of it."""
        written = self._port.git(
            git_argv("bundle", "create", str(bundle), name=f"refs/heads/{branch}"), cwd=self._cwd
        )
        if not written.ok:
            self._record(
                "salvage", target.id, f"bundle of {target.name} failed", written.transcript()
            )
            return False
        verified = self._port.git(git_argv("bundle", "verify", str(bundle)), cwd=self._cwd)
        if not verified.ok:
            self._record(
                "salvage",
                target.id,
                f"bundle written for {target.name} did not verify; deletion aborted",
                verified.transcript(),
            )
            return False
        self._salvages.append(
            SalvageRecord(
                target_id=target.id,
                kind="remote_branch",
                path=str(bundle),
                verified=True,
                # Quoted because it is meant to be run, not read: a repository
                # path with a space in it would otherwise print a command that
                # restores the wrong thing or nothing at all.
                detail="restore with: git clone "
                f"{shlex.quote(str(bundle))} -b {shlex.quote(branch)}",
            )
        )
        return True

    # -- delete + verify ----------------------------------------------------

    def _commit_only_this_worktree_holds(self, target: Target) -> str:
        """The commit that removing this worktree would strand, or "".

        git's refusals are the safety story for a named worktree, and they have
        exactly one gap: they know about *uncommitted* content and nothing
        about a commit made inside the worktree on no branch. That tree is
        clean, so git removes it without complaint -- and the commit's only
        reachability goes with it, because the administrative record being
        deleted is what held HEAD, and the per-worktree reflog dies in the same
        step. No ref, no reflog, no undo.

        So the question git cannot answer is asked of git directly: does any
        ref contain this commit? Not "does it look abandoned", not "is the
        tree clean" -- reachability, which is the thing that actually decides
        whether deleting is recoverable. A worktree on a branch answers yes
        through that branch and is unaffected.

        A probe that does not answer is treated as a stranding. The cost of
        being wrong that way is a worktree someone removes by hand; the cost
        of being wrong the other way is the commit."""
        head = next((w.head for w in self._survey.worktrees if w.path == target.name), "")
        if not head:
            return ""
        refs = self._port.git(
            git_argv("for-each-ref", "--count=1", f"--contains={head}"), cwd=self._cwd
        )
        return "" if refs.ok and refs.out else head

    def _delete_worktree(self, target: Target) -> Deletion:
        """Remove the worktree and let git's own interlocks stand.

        No --force, ever. git refuses to remove a worktree holding modified or
        untracked files, or one that is locked, or the main working tree, and
        each refusal knows something this process does not: what that directory
        holds right now, rather than when the survey read it. Overriding them
        would mean re-implementing every one of those checks here, in a
        language that cannot see the filesystem the way git just did.

        A caller who has read git's complaint and still wants the tree gone can
        run one `git worktree remove --force` themselves. That costs them a
        command and costs this tool nothing it can get wrong.

        Ignored files do not trigger the refusal, so removing a finished
        worktree full of caches is unaffected.

        There is one thing git's refusals do not cover, and it is added below
        rather than assumed away."""
        stranded = self._commit_only_this_worktree_holds(target)
        if stranded:
            self._record(
                "delete",
                target.id,
                f"removing {target.name} would strand commit {stranded[:8]}, which no ref "
                f"contains; nothing was deleted. Keep it with "
                f"`git branch <name> {stranded[:8]}` and re-run, or discard it deliberately "
                f"with `git worktree remove --force {target.name}`",
                (),
            )
            return _failed(target, f"would strand commit {stranded[:8]}")
        removal = self._port.git(git_argv("worktree", "remove", name=target.name), cwd=self._cwd)
        if not removal.ok:
            self._record(
                "delete",
                target.id,
                f"git refused to remove worktree {target.name}; its own message is in the "
                f"transcript below, and nothing was deleted",
                removal.transcript(),
            )
            return _failed(target, "removal command failed")
        # No `worktree prune` here. It clears the administrative records of
        # every worktree whose directory has gone missing, and those were never
        # planned targets: the executor acts on what the plan named, and
        # nothing else. `worktree remove` takes this one's record with it.
        listing = self._port.git(git_argv("worktree", "list", "--porcelain"), cwd=self._cwd)
        if not listing.ok:
            # Absence of the worktree in output that was never produced is not
            # evidence of anything. Unverified is its own outcome, distinct
            # from verified-gone.
            self._record(
                "verify",
                target.id,
                f"could not confirm {target.name} is gone; the removal reported success",
                listing.transcript(),
            )
            return _failed(target, "deletion unverified")
        still_there = any(
            line.strip() == f"worktree {target.name}" for line in listing.stdout.splitlines()
        )
        if still_there:
            self._record(
                "verify",
                target.id,
                f"worktree {target.name} still appears in `git worktree list` after removal",
                listing.transcript(),
            )
            return _failed(target, "still present after removal")
        return Deletion(
            target_id=target.id,
            kind=target.kind,
            name=target.name,
            deleted=True,
            verified=True,
            detail="worktree removed",
        )

    def _delete_branch(self, target: Target) -> Deletion:
        removal = self._port.git(git_argv("branch", "-D", name=target.name), cwd=self._cwd)
        if not removal.ok:
            self._record(
                "delete", target.id, f"could not delete branch {target.name}", removal.transcript()
            )
            return _failed(target, "delete command failed")
        # `show-ref --verify` cannot answer this: it exits nonzero both when the
        # ref is absent and when the command itself failed, so "gone" and
        # "broken" are the same signal. `for-each-ref` exits 0 either way and
        # answers in stdout, which separates them.
        ref = f"refs/heads/{target.name}"
        probe = self._port.git(
            git_argv("for-each-ref", "--format=%(refname)", name=ref), cwd=self._cwd
        )
        if not probe.ok:
            self._record(
                "verify",
                target.id,
                f"could not confirm {ref} is gone; the delete reported success",
                probe.transcript(),
            )
            return _failed(target, "deletion unverified")
        if any(line.strip() == ref for line in probe.stdout.splitlines()):
            self._record(
                "verify",
                target.id,
                f"{ref} still resolves after `git branch -D`",
                probe.transcript(),
            )
            return _failed(target, "ref survived deletion")
        return Deletion(
            target_id=target.id,
            kind=target.kind,
            name=target.name,
            deleted=True,
            verified=True,
            detail="local ref deleted",
        )

    def _delete_remote_branch(self, target: Target) -> Deletion:
        """Delete the server's ref, but only if the server still holds what we
        judged.

        Everything decided about a remote branch was decided from
        `refs/remotes/<remote>/<ref>` -- a local cache, last refreshed at
        whatever `git fetch` ran most recently. A colleague pushing to that
        branch an hour ago is invisible here, and a bare `push --delete` would
        take the ref away regardless, destroying work this run never saw.

        The lease makes the server check for us: the delete is accepted only
        while the ref still points at the commit the survey judged, and is
        rejected as stale otherwise."""
        remote, _, ref = target.name.partition("/")
        if not ref:
            self._record("delete", target.id, f"cannot split {target.name} into remote and ref", ())
            return _failed(target, "unparseable remote ref")
        expected = next(
            (b.head for b in self._survey.branches if b.is_remote and b.name == target.name),
            "",
        )
        if not expected:
            self._record(
                "delete",
                target.id,
                f"no surveyed commit for {target.name}, so the server ref cannot be "
                f"checked against what was judged; refusing to delete it blind",
                (),
            )
            return _failed(target, "no lease value")
        removal = self._port.git(
            git_argv("push", f"--force-with-lease={ref}:{expected}", remote, "--delete", name=ref),
            cwd=self._cwd,
        )
        if not removal.ok:
            self._record(
                "delete",
                target.id,
                f"could not delete {ref} on {remote}; if this was rejected as stale, "
                f"{remote} has moved past {expected[:8]} since the survey read it -- "
                f"fetch and re-run so the new commits are judged too",
                removal.transcript(),
            )
            return _failed(target, "push --delete failed")
        ref_path = f"refs/heads/{ref}"
        probe = self._port.git(
            git_argv("ls-remote", "--heads", remote, name=ref_path), cwd=self._cwd
        )
        if not probe.ok:
            self._record(
                "verify",
                target.id,
                f"could not confirm {ref} is gone from {remote}; the delete reported success",
                probe.transcript(),
            )
            return _failed(target, "deletion unverified")
        # `ls-remote` takes a pattern, and it matches on path-component
        # boundaries: an unrelated `a/feat/x` on the same server answers a
        # question asked about `feat/x`. Reading that as survival turns a
        # deletion git performed into a reported failure, so the refname column
        # settles it -- the same exact comparison the local path makes.
        if any(line.split("\t")[-1].strip() == ref_path for line in probe.stdout.splitlines()):
            self._record(
                "verify",
                target.id,
                f"{ref} still exists on {remote} after `git push --delete` reported success",
                probe.transcript(),
            )
            return _failed(target, "remote ref survived deletion")
        # No `remote prune` here. It drops every tracking ref under
        # refs/remotes/<remote> that the server no longer has, which is a
        # sweep of refs this run never planned and never judged.
        return Deletion(
            target_id=target.id,
            kind=target.kind,
            name=target.name,
            deleted=True,
            verified=True,
            detail=f"{ref} deleted on {remote}",
        )

    def _record(
        self, stage: str, target_id: str, message: str, transcript: tuple[str, ...]
    ) -> None:
        self._anomalies.append(
            Anomaly(stage=stage, target_id=target_id, message=message, transcript=transcript)
        )

    @staticmethod
    def _strand(target: Target, stranded: set[str]) -> None:
        if target.kind is TargetKind.WORKTREE:
            stranded.add(target.name)

    # -- drive --------------------------------------------------------------

    def run(self, plan: Plan) -> ExecutionReport:
        deletions: list[Deletion] = []
        salvage_dir = Path(plan.salvage_dir) if plan.salvage_dir else None
        # Worktrees are ordered first, so by the time a branch comes up its
        # holder's fate is known. A branch whose worktree survived cannot be
        # deleted -- attempting it anyway buys a git error that reads as a new
        # problem instead of the consequence of the one already reported.
        stranded: set[str] = set()

        for target in plan.targets:
            if target.kind is TargetKind.BRANCH:
                holder = next(
                    (b.checked_out_at for b in self._survey.branches if b.name == target.name),
                    None,
                )
                if holder and holder in stranded:
                    deletions.append(
                        _failed(target, f"skipped: its worktree {holder} was not removed")
                    )
                    continue

            # A server ref is the only thing here with no undo behind it, so it
            # is the only thing that is bundled first.
            salvage_first = target.kind is TargetKind.REMOTE_BRANCH

            if plan.dry_run:
                deletions.append(
                    Deletion(
                        target_id=target.id,
                        kind=target.kind,
                        name=target.name,
                        deleted=False,
                        verified=False,
                        detail="dry run: would delete"
                        + (" after salvage" if salvage_first else ""),
                    )
                )
                continue

            if salvage_first:
                if salvage_dir is None:
                    self._record(
                        "salvage",
                        target.id,
                        f"{target.name} needs salvage but no salvage directory was resolved",
                        (),
                    )
                    deletions.append(_failed(target, "no salvage directory"))
                    continue
                if not self._salvage_remote_branch(target, salvage_dir):
                    deletions.append(_failed(target, "salvage failed; deletion skipped"))
                    continue

            if target.kind is TargetKind.WORKTREE:
                outcome = self._delete_worktree(target)
                if not outcome.deleted:
                    self._strand(target, stranded)
                deletions.append(outcome)
            elif target.kind is TargetKind.BRANCH:
                deletions.append(self._delete_branch(target))
            else:
                deletions.append(self._delete_remote_branch(target))

        return ExecutionReport(
            deletions=tuple(deletions),
            salvages=tuple(self._salvages),
            anomalies=tuple(self._anomalies),
            salvage_dir=plan.salvage_dir,
        )


def _failed(target: Target, detail: str) -> Deletion:
    return Deletion(
        target_id=target.id,
        kind=target.kind,
        name=target.name,
        deleted=False,
        verified=False,
        detail=detail,
    )
