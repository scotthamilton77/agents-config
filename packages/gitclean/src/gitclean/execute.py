"""Salvage, delete, verify. The only stage that changes anything.

Three commitments shape this module:

**Salvage precedes deletion, and a salvage that cannot be verified aborts the
deletion.** An archive nobody opened is not a safety net. A branch is bundled
and the bundle verified; a worktree is archived and the archive read back and
found non-empty. If either check does not pass, the target is left alone and
the failure is reported.

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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gitclean.model import Anomaly, Deletion, Plan, SalvageRecord, Survey, Target, TargetKind
from gitclean.ports import CommandPort


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

    def _salvage_worktree(self, target: Target, salvage_dir: Path) -> bool:
        """Archive the whole tree as it stands, then prove the archive readable.

        One tar replaces what used to be a stash, a temporary ref, a bundle and
        a file-by-file copy. Each of those had its own way of losing content --
        the copy followed symlinks and could not see ignored files, and the
        stash captured only what git already tracked -- and none of them
        captured what is actually at risk, which is the directory."""
        archive = salvage_dir / f"{slug(target.name)}.tar.gz"
        created = self._port.create_archive(Path(target.name), archive)
        if not created.ok:
            self._record(
                "salvage",
                target.id,
                f"could not archive {target.name}; deletion aborted",
                created.transcript(),
            )
            return False

        listing = self._port.list_archive(archive)
        if not listing.ok:
            self._record(
                "salvage",
                target.id,
                f"archive written for {target.name} could not be read back; deletion aborted",
                listing.transcript(),
            )
            return False
        entries = [line for line in listing.stdout.splitlines() if line.strip() not in ("", "./")]
        if not entries:
            # tar happily writes an archive of nothing and reads it back
            # without complaint, so a clean exit code is not proof of capture.
            self._record(
                "salvage",
                target.id,
                f"archive of {target.name} is empty; nothing was captured, so nothing is deleted",
                listing.transcript(),
            )
            return False

        self._salvages.append(
            SalvageRecord(
                target_id=target.id,
                kind="worktree",
                path=str(archive),
                verified=True,
                detail=f"{len(entries)} entries; restore with: tar -xzf {archive} -C <dir>",
            )
        )
        return True

    def _salvage_branch(self, target: Target, salvage_dir: Path) -> bool:
        """Bundle the whole branch. Bundling the full history rather than
        `base..branch` costs disk and buys a bundle that clones standalone --
        the right trade when the alternative is unrecoverable work."""
        ref = target.name
        bundle = salvage_dir / f"{slug(ref)}.bundle"
        self._port.write_text(salvage_dir / ".gitclean-keep", "")
        created = self._port.git(["bundle", "create", str(bundle), ref], cwd=self._cwd)
        if not created.ok:
            self._record("salvage", target.id, f"bundle of {ref} failed", created.transcript())
            return False
        verified = self._port.git(["bundle", "verify", str(bundle)], cwd=self._cwd)
        if not verified.ok:
            self._record(
                "salvage",
                target.id,
                f"bundle written for {ref} did not verify; deletion aborted",
                verified.transcript(),
            )
            return False
        self._salvages.append(
            SalvageRecord(
                target_id=target.id,
                kind="branch",
                path=str(bundle),
                verified=True,
                detail=f"restore with: git clone {bundle} -b {ref.split('/')[-1]}",
            )
        )
        return True

    def _salvage(self, target: Target, salvage_dir: Path) -> bool:
        if target.kind is TargetKind.WORKTREE:
            return self._salvage_worktree(target, salvage_dir)
        return self._salvage_branch(target, salvage_dir)

    # -- delete + verify ----------------------------------------------------

    def _delete_worktree(self, target: Target, *, salvaged: bool) -> Deletion:
        """Remove the worktree, forcing only when an archive exists to fall
        back on.

        git refuses to remove a worktree holding modified or untracked files.
        That refusal is the last thing standing between a tree that went dirty
        *after* the survey read it and its destruction, and passing --force
        unconditionally spends it -- in a tool whose whole premise is
        re-surveying so it acts on current state. So --force is passed only
        where salvage already captured the contents; otherwise git's own check
        runs, and its complaint surfaces as an anomaly carrying the transcript.

        Ignored files do not trigger that refusal, so the ordinary sweep of a
        finished worktree full of caches is unaffected."""
        argv = ["worktree", "remove", *(["--force"] if salvaged else []), "--", target.name]
        removal = self._port.git(argv, cwd=self._cwd)
        if not removal.ok:
            self._record(
                "delete",
                target.id,
                f"could not remove worktree {target.name}"
                + (
                    ""
                    if salvaged
                    else "; it holds changes that were not there when it was surveyed, "
                    "so nothing was archived and nothing was deleted"
                ),
                removal.transcript(),
            )
            return _failed(target, "removal command failed")
        self._port.git(["worktree", "prune"], cwd=self._cwd)
        listing = self._port.git(["worktree", "list", "--porcelain"], cwd=self._cwd)
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
            detail="worktree removed and pruned",
        )

    def _delete_branch(self, target: Target) -> Deletion:
        # `--` because the name is repo-derived, and `refs/heads/-m` is a legal
        # ref: `git branch` will not create one, but `update-ref` will and a
        # remote can push one. Without the terminator git reads the name as a
        # switch and the deletion fails with a usage error nobody can act on.
        removal = self._port.git(["branch", "-D", "--", target.name], cwd=self._cwd)
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
        probe = self._port.git(["for-each-ref", "--format=%(refname)", ref], cwd=self._cwd)
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
            ["push", f"--force-with-lease={ref}:{expected}", remote, "--delete", "--", ref],
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
        probe = self._port.git(["ls-remote", "--heads", remote, ref], cwd=self._cwd)
        if not probe.ok:
            self._record(
                "verify",
                target.id,
                f"could not confirm {ref} is gone from {remote}; the delete reported success",
                probe.transcript(),
            )
            return _failed(target, "deletion unverified")
        if probe.out:
            self._record(
                "verify",
                target.id,
                f"{ref} still exists on {remote} after `git push --delete` reported success",
                probe.transcript(),
            )
            return _failed(target, "remote ref survived deletion")
        self._port.git(["remote", "prune", remote], cwd=self._cwd)
        return Deletion(
            target_id=target.id,
            kind=target.kind,
            name=target.name,
            deleted=True,
            verified=True,
            detail=f"{ref} deleted on {remote} and pruned locally",
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

            if plan.dry_run:
                deletions.append(
                    Deletion(
                        target_id=target.id,
                        kind=target.kind,
                        name=target.name,
                        deleted=False,
                        verified=False,
                        detail="dry run: would delete"
                        + (" after salvage" if target.salvage_needed else ""),
                    )
                )
                continue

            salvaged = False
            if target.salvage_needed:
                if salvage_dir is None:
                    self._record(
                        "salvage",
                        target.id,
                        f"{target.name} needs salvage but no salvage directory was resolved",
                        (),
                    )
                    deletions.append(_failed(target, "no salvage directory"))
                    self._strand(target, stranded)
                    continue
                if not self._salvage(target, salvage_dir):
                    deletions.append(_failed(target, "salvage failed; deletion skipped"))
                    self._strand(target, stranded)
                    continue
                salvaged = True

            if target.kind is TargetKind.WORKTREE:
                outcome = self._delete_worktree(target, salvaged=salvaged)
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
