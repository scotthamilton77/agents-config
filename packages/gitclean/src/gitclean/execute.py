"""Salvage, delete, verify. The only stage that changes anything.

Three commitments shape this module:

**Salvage precedes deletion, and a salvage that cannot be verified aborts the
deletion.** A bundle nobody checked is not a safety net. If `git bundle
verify` does not pass, the target is left alone and the failure is reported.

**Every deletion is verified by re-asking git.** A zero exit code is a claim,
not a fact -- `git push --delete` in particular can exit 0 against a ref the
server kept. So the ref is queried again afterwards, and a survivor becomes an
anomaly rather than a line in the success list.

**Anomalies carry the transcript.** Whoever reads this output must be able to
remediate without re-running anything, so the argv, exit code, and both
streams of the surprising command travel with the finding.
"""

from __future__ import annotations

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
    """Filesystem-safe stand-in for a ref or path."""
    cleaned = "".join(c if c.isalnum() or c in "-._" else "-" for c in name)
    return cleaned.strip("-") or "target"


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
        """Capture a dirty tree: tracked changes as a bundle, untracked files
        as copies. Returns False when nothing verifiable was captured."""
        wt = Path(target.name)
        dest = salvage_dir / slug(target.name)
        captured: list[str] = []

        stash = self._port.git(["stash", "create"], cwd=wt)
        if not stash.ok:
            self._record(
                "salvage",
                target.id,
                f"could not snapshot tracked changes in {target.name}",
                stash.transcript(),
            )
            return False
        sha = stash.out
        if sha:
            bundle = dest / "tracked-changes.bundle"
            self._port.write_text(dest / ".gitclean-keep", "")
            # `git bundle` packages REFS, not revisions: handed a bare SHA it
            # writes nothing and then refuses the empty result. So the stash
            # commit gets a temporary ref, which the bundle captures along with
            # its full history, leaving a self-contained clonable archive.
            temp_ref = f"refs/gitclean/salvage/{slug(target.name)}"
            pointed = self._port.git(["update-ref", temp_ref, sha], cwd=wt)
            if not pointed.ok:
                self._record(
                    "salvage",
                    target.id,
                    f"could not park a salvage ref for {target.name}",
                    pointed.transcript(),
                )
                return False
            created = self._port.git(["bundle", "create", str(bundle), temp_ref], cwd=wt)
            verified = (
                self._port.git(["bundle", "verify", str(bundle)], cwd=wt) if created.ok else created
            )
            # The ref exists only to give the bundle something to package; drop
            # it on every path so a failed salvage leaves no debris behind.
            self._port.git(["update-ref", "-d", temp_ref], cwd=wt)
            if not created.ok:
                self._record(
                    "salvage",
                    target.id,
                    f"bundle of tracked changes in {target.name} failed",
                    created.transcript(),
                )
                return False
            if not verified.ok:
                self._record(
                    "salvage",
                    target.id,
                    f"bundle written for {target.name} did not verify; deletion aborted",
                    verified.transcript(),
                )
                return False
            captured.append(f"tracked changes -> {bundle}")

        untracked = self._port.git(["ls-files", "--others", "--exclude-standard"], cwd=wt)
        if untracked.ok:
            for rel in (line.strip() for line in untracked.stdout.splitlines()):
                if rel:
                    self._port.copy_file(wt / rel, dest / "untracked" / rel)
                    captured.append(f"untracked {rel}")

        if not captured:
            self._record(
                "salvage",
                target.id,
                f"{target.name} was classified dirty but nothing could be captured",
                stash.transcript(),
            )
            return False

        self._salvages.append(
            SalvageRecord(
                target_id=target.id,
                kind="worktree",
                path=str(dest),
                verified=True,
                detail="; ".join(captured),
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

    def _delete_worktree(self, target: Target) -> Deletion:
        removal = self._port.git(["worktree", "remove", "--force", target.name], cwd=self._cwd)
        if not removal.ok:
            self._record(
                "delete",
                target.id,
                f"could not remove worktree {target.name}",
                removal.transcript(),
            )
            return _failed(target, "removal command failed")
        self._port.git(["worktree", "prune"], cwd=self._cwd)
        listing = self._port.git(["worktree", "list", "--porcelain"], cwd=self._cwd)
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
        removal = self._port.git(["branch", "-D", target.name], cwd=self._cwd)
        if not removal.ok:
            self._record(
                "delete", target.id, f"could not delete branch {target.name}", removal.transcript()
            )
            return _failed(target, "delete command failed")
        probe = self._port.git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{target.name}"], cwd=self._cwd
        )
        if probe.ok:
            self._record(
                "verify",
                target.id,
                f"refs/heads/{target.name} still resolves after `git branch -D`",
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
        remote, _, ref = target.name.partition("/")
        if not ref:
            self._record("delete", target.id, f"cannot split {target.name} into remote and ref", ())
            return _failed(target, "unparseable remote ref")
        removal = self._port.git(["push", remote, "--delete", ref], cwd=self._cwd)
        if not removal.ok:
            self._record(
                "delete",
                target.id,
                f"could not delete {ref} on {remote}",
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
