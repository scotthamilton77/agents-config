"""The invariant every mutating run is measured against.

An example-based test only ever asserts the topology its author already
imagined, which is how a suite at 98% branch coverage still shipped defects
that destroyed commits. This asserts the property instead: snapshot every
commit reachable from a ref before the run, and afterwards demand that each one
still is. A run that strands a commit nobody thought to write a test about
fails the test that never mentions it.

Reachable means *reachable from a ref*, and the enumeration is deliberate:
``rev-list --all`` plus the HEAD of every linked worktree, because a detached
worktree's HEAD is reachable only through that worktree's administrative
record, and a run that removes the record strands the commit. The reflog is
deliberately not counted. It is the undo mechanism rather than evidence of
survival -- it expires on git's own schedule, and counting it would excuse
every deletion this tool could ever make.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from gitclean.ports import SubprocessCommands


def _git(repo: Path, *args: str) -> str:
    """A probe that did not answer cannot be read as 'nothing was lost'."""
    result = SubprocessCommands().git(list(args), cwd=repo)
    if not result.ok:
        raise AssertionError(f"reachability probe failed: git {' '.join(args)}\n{result.stderr}")
    return result.stdout


def _worktree_heads(repo: Path) -> list[str]:
    """The HEAD of every worktree, main and linked.

    A bare repository reports no HEAD line, and a worktree whose directory has
    been moved aside still reports one -- its record, and the commit that
    record holds, are exactly what a prune destroys."""
    return [
        line.split(" ", 1)[1].strip()
        for line in _git(repo, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("HEAD ")
    ]


def reachable(repo: Path) -> set[str]:
    """Every commit reachable from some ref or worktree HEAD."""
    return set(_git(repo, "rev-list", "--all", *_worktree_heads(repo)).split())


def _describe(repo: Path, oid: str) -> str:
    """The subject line, so a failure names the work rather than a hash. The
    object usually still exists when this runs -- unreachable is not gone."""
    result = SubprocessCommands().git(["show", "-s", "--format=%h %s", oid], cwd=repo)
    return result.out if result.ok else oid


@dataclass
class Exemptions:
    """Unreachability a test declares deliberate.

    Two forms, both blunt on purpose. Name the commits, or name a bundle and
    let a real restore say which commits it holds. Anything else is data loss.
    """

    named: set[str] = field(default_factory=set)
    restored: set[str] = field(default_factory=set)

    def expect_unreachable(self, *oids: str) -> None:
        """Declare that these commits are meant to be stranded by this run."""
        self.named.update(oid.strip() for oid in oids if oid.strip())

    def proven_by_bundle(self, bundle: Path) -> None:
        """Restore the bundle and take whatever comes back as exempt.

        The exemption is the restore, not the claim: a bundle that clones back
        empty -- which is what a bundle holding only a remote-tracking ref does
        -- proves nothing, and the commits it was supposed to hold stay counted
        as lost. A bundle that will not clone at all proves less than that, and
        one that clones back nothing is reported here rather than three lines
        later as commits nobody can account for."""
        with tempfile.TemporaryDirectory(prefix="gitclean-restore-") as scratch:
            clone = Path(scratch) / "restored"
            result = SubprocessCommands().git(["clone", "-q", str(bundle), str(clone)])
            if not result.ok:
                raise AssertionError(f"salvage {bundle} did not clone back\n{result.stderr}")
            came_back = set(_git(clone, "rev-list", "--all").split())
            assert came_back, (
                f"salvage {bundle} cloned back an empty repository, so it excuses nothing"
            )
            self.restored |= came_back


@contextmanager
def reachability_guard(repo: Path) -> Iterator[Exemptions]:
    """Fail the enclosing test if the block stranded a commit.

    Nothing runs on the way out of a failing block: a test that already failed
    should report its own assertion, not a second one about the wreckage."""
    exemptions = Exemptions()
    before = reachable(repo)
    yield exemptions
    after = reachable(repo)

    lost = before - after - exemptions.named - exemptions.restored
    assert not lost, (
        f"{len(lost)} commit(s) in {repo} were reachable before this run and are reachable "
        f"from no ref after it, with no salvage holding them:\n"
        + "\n".join(f"  {_describe(repo, oid)}" for oid in sorted(lost))
    )
    stale = exemptions.named & after
    assert not stale, (
        f"exempted as deliberately stranded, but still reachable: {sorted(stale)} -- a stale "
        f"exemption excuses whatever this run destroys next"
    )
