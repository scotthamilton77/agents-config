"""Repositories nobody imagined, swept and measured for what the sweep cost.

The enumerated matrix beside this file asserts one thing per row a reviewer had
to think of first, which is exactly its weakness: a defect living in a shape
nobody pictured passes the whole suite, and 98% branch coverage is no protection
against it. This builds the shapes instead of imagining them -- a repository
assembled from a random draw over a small alphabet of real git operations --
and then asks the oracle the only question that does not require knowing the
answer in advance: after a bare sweep, is every commit that was reachable still
reachable?

**Why that question needs no prediction.** A bare sweep -- ``--cleanup`` with no
target named on the command line -- deletes only what cleared all six of the
sweep's questions, and merge proof is the first of them. So the invariant does
not depend on which branches this particular draw made sweepable: whatever the
sweep took, it took on a merge proof, and a merge keeps the work. That is what
makes generating topologies tractable at all. Predicting the deletions would
mean reimplementing the tool in the test, and a reimplementation agrees with the
original about its own bugs.

**The one thing a bare sweep is allowed to strand, and why it is not an
exemption in the usual sense.** Two of the four merge tiers prove a merge that
copied the work rather than moving it: a squash merge and a cherry-pick both put
the branch's *content* on the trunk under new hashes and leave the original
commits held by nothing but the branch ref. Deleting that ref strands them, and
that is the deletion working -- it is what the tool exists to do. The allowance
is therefore not a judgement about gitclean's behaviour but a fact about the
generator's own history: it is the set of commits this test squashed or
cherry-picked onto the trunk itself, recorded as it did so, and intersected with
what actually became unreachable so a run that stranded none of them declares
nothing. Every commit outside that set is work with one copy, and a sweep that
strands one is a defect no matter what shape produced it. Guarding a remote is
unconditional: a bare sweep never deletes a ref on a server, so the bare
repositories are held to a genuinely empty allowance.

**What this does not reach, measured rather than assumed.** Breaking the
executor's last-ditch check -- the one asking whether any ref contains a
worktree's commit before removing it -- leaves every draw here passing, and that
is not a gap in the draws. A bare sweep never gets that far: a worktree holding
a commit no ref names carries no merge proof, so the first of the six questions
withholds it and the executor is never asked. That guard is reachable only by
naming the worktree, which is a deliberate authorisation and a path these draws
do not drive. Widening the alphabet will not change it; driving named targets
would, and that is a different harness.

**Why a seeded generator rather than a property-testing library.** Shrinking is
what a library buys, and it is replaceable here: every draw records the
operations it performed, and a failure prints the seed and that log, so the
repository can be rebuilt by hand or by rerunning one test id. Against that, a
library is a new dependency in a package whose gate audits its dependencies, and
a fixed seed list makes a CI run reproducible in a way a randomly-seeded one is
not. ``random.Random(seed)`` costs nothing and gives every seed its own test id.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from reachability import reachability_guard
from test_real_git import GitOnly, anomaly_lines, commit, git, report

from gitclean.cli import EXIT_ANOMALY, EXIT_OK
from gitclean.ports import SubprocessCommands

SEEDS = tuple(range(1, 29))
"""The corpus. Fixed, so a failure names a test id somebody else can rerun.

Twenty-eight is where every operation in the alphabet occurs in at least one
draw, which the corpus check asserts rather than trusts. Fewer left the
patch-id tier undrawn: cutting a branch, moving the trunk past it and then
choosing that one operation out of a dozen is a narrow path, and the way to
widen it is more draws rather than a generator that stacks the deck."""

OPERATIONS_PER_TOPOLOGY = (4, 9)
"""Inclusive bounds on the draw length.

Small on purpose. Every operation is real git and every topology ends in a real
sweep, so the corpus is paid for in wall clock against a suite that already runs
for the better part of a minute. Four operations is enough to put a branch, a
worktree and a merge in the same repository, which is where the interactions
live; the shapes that need ten are reached by having many draws rather than long
ones."""

A_FIXED_CLOCK = datetime(2026, 8, 1, tzinfo=UTC)
"""The run's idea of now.

Nothing in the sweep's six questions is derived from age -- age measures commits
rather than intent, which is a rule this package states outright -- so the clock
only reaches the report's descriptive fields. Pinning it anyway keeps two runs
of the same seed byte-identical where they can be."""


# -- the model the planner reasons over ---------------------------------------


@dataclass
class BranchShape:
    """What the planner knows about a branch without asking git.

    ``holds_work`` is whether the branch's own files are still present at its
    tip. A branch that added a file and took it off again has a tip whose tree
    matches the merge base, and squashing or cherry-picking that produces an
    empty commit git declines to make -- so the planner has to know, and the
    only way to know without running git is to remember doing it."""

    name: str
    commits: int = 0
    files: tuple[str, ...] = ()
    merged: bool = False
    rewritten: bool = False
    holds_work: bool = True
    worktree: str | None = None
    published: tuple[str, ...] = ()
    trunk_at_base: int = 0


@dataclass
class WorktreeShape:
    """What the planner knows about a linked worktree.

    ``moved`` is the directory having been renamed out from under git rather
    than the worktree having been removed: the administrative record survives,
    git calls it prunable, and the tree and its commits are both still on
    disk."""

    name: str
    branch: str | None
    dirty: bool = False
    locked: bool = False
    moved: bool = False


@dataclass
class Step:
    """One operation, with every choice already made.

    Planning resolves the names so building can be a dumb interpreter: no
    randomness runs while git does, which is what lets the corpus check plan
    every seed without touching a disk."""

    op: str
    branch: str = ""
    worktree: str = ""
    remote: str = ""
    base: str = ""
    files: tuple[str, ...] = ()

    def __str__(self) -> str:
        parts = [self.op]
        parts += [p for p in (self.branch, self.worktree, self.remote) if p]
        parts += [f"from {self.base}"] if self.base else []
        parts += list(self.files)
        return " ".join(parts)


@dataclass
class Model:
    """The repository as the planner believes it to be.

    It is compared against the real repository after building, which is the
    check that the two halves have not drifted apart -- a builder that quietly
    stopped executing an operation would otherwise leave the corpus asserting
    less every release while every test still passed."""

    trunk: str = "main"
    trunk_commits: int = 1
    seq: int = 0
    branches: dict[str, BranchShape] = field(default_factory=dict)
    worktrees: dict[str, WorktreeShape] = field(default_factory=dict)
    remotes: list[str] = field(default_factory=list)

    def next_name(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}{self.seq}"

    def unmerged(self) -> list[BranchShape]:
        return [b for b in self.branches.values() if b.commits > 0 and not b.merged]

    def live_worktrees(self) -> list[WorktreeShape]:
        """The ones whose directory is still where git registered it. An
        operation that reaches into a moved-aside tree would be writing into a
        path that no longer exists."""
        return [w for w in self.worktrees.values() if not w.moved]


# -- the alphabet -------------------------------------------------------------
#
# Each entry is a question -- can this run against the model as it stands? --
# and a planner that emits the step and moves the model forward. The predicate
# is what keeps every draw a valid repository: an operation that cannot apply is
# never chosen, so no draw degenerates into a sequence of no-ops.


def _can_always(_model: Model) -> bool:
    return True


def _plan_commit_on_trunk(model: Model, _rng: random.Random) -> Step:
    model.trunk_commits += 1
    return Step("commit-on-trunk", files=(model.next_name("t") + ".txt",))


def _plan_branch_and_commit(model: Model, rng: random.Random) -> Step:
    """A branch off the trunk, sometimes off where the trunk used to be.

    Cutting from an older commit is what an ordinary branch looks like by the
    time anyone cleans up -- work started on Monday against a trunk that has
    moved since -- and it is also the only way a short draw reaches the
    patch-id tier at all. A replay onto the parent a commit was written against,
    carrying the same tree, comes back as the same object when the two happen
    inside one second of each other; a base the trunk has left behind
    guarantees a different parent, so the copy is a copy."""
    name = "feat/" + model.next_name("b")
    files = tuple(model.next_name("f") + ".txt" for _ in range(rng.randint(1, 2)))
    behind = model.trunk_commits > 1 and rng.random() < 0.5
    model.branches[name] = BranchShape(
        name=name,
        commits=len(files),
        files=files,
        trunk_at_base=model.trunk_commits - 1 if behind else model.trunk_commits,
    )
    return Step("branch-and-commit", branch=name, base="main~1" if behind else "", files=files)


def _can_merge(model: Model) -> bool:
    return bool(model.unmerged())


def _plan_merge_branch(model: Model, rng: random.Random) -> Step:
    branch = rng.choice(model.unmerged())
    branch.merged = True
    model.trunk_commits += 1
    return Step("merge-branch", branch=branch.name)


def _rewritable(model: Model) -> list[BranchShape]:
    """Branches a squash or a cherry-pick can be asked to replay.

    ``holds_work`` is the condition: replaying a branch whose net effect is
    nothing produces an empty commit, and git refuses to make one unasked."""
    return [b for b in model.unmerged() if b.holds_work]


def _can_rewrite(model: Model) -> bool:
    return bool(_rewritable(model))


def _plan_squash_merge_branch(model: Model, rng: random.Random) -> Step:
    branch = rng.choice(_rewritable(model))
    branch.merged = True
    branch.rewritten = True
    model.trunk_commits += 1
    return Step("squash-merge-branch", branch=branch.name)


def _pickable(model: Model) -> list[BranchShape]:
    """Cherry-picking is only a distinct shape once the trunk has moved on.

    Replayed onto the parent it was written against, with the same tree, a
    commit comes back as the same object -- ancestry then settles the merge and
    the topology collapses into one the plain-merge operation already makes."""
    return [b for b in _rewritable(model) if model.trunk_commits > b.trunk_at_base]


def _can_cherry_pick(model: Model) -> bool:
    return bool(_pickable(model))


def _plan_cherry_pick_branch(model: Model, rng: random.Random) -> Step:
    branch = rng.choice(_pickable(model))
    branch.merged = True
    branch.rewritten = True
    model.trunk_commits += branch.commits
    return Step("cherry-pick-branch", branch=branch.name)


def _backable(model: Model) -> list[BranchShape]:
    """A branch whose own work can be taken off again on the branch itself.

    It has to be checked out to do that, so a branch a worktree already holds is
    out: the main checkout cannot take a ref a linked tree is standing on."""
    return [b for b in _rewritable(model) if b.worktree is None]


def _can_back_out(model: Model) -> bool:
    return bool(_backable(model))


def _plan_back_out_branch_work(model: Model, rng: random.Random) -> Step:
    branch = rng.choice(_backable(model))
    branch.holds_work = False
    branch.commits += 1
    return Step("back-out-branch-work", branch=branch.name, files=branch.files)


def _plan_worktree_on_new_branch(model: Model, _rng: random.Random) -> Step:
    name = "feat/" + model.next_name("w")
    tree = model.next_name("wt-")
    a_file = model.next_name("f") + ".txt"
    model.branches[name] = BranchShape(
        name=name, commits=1, files=(a_file,), worktree=tree, trunk_at_base=model.trunk_commits
    )
    model.worktrees[tree] = WorktreeShape(name=tree, branch=name)
    return Step("worktree-on-new-branch", branch=name, worktree=tree, files=(a_file,))


def _plan_detached_worktree(model: Model, _rng: random.Random) -> Step:
    """A detached checkout at the trunk's tip: the control for the orphan case,
    where nothing is at risk and a refusal to remove it would be the tool
    declining the ordinary job it exists for."""
    tree = model.next_name("wt-")
    model.worktrees[tree] = WorktreeShape(name=tree, branch=None)
    return Step("detached-worktree", worktree=tree)


def _plan_orphan_commit_in_a_detached_worktree(model: Model, _rng: random.Random) -> Step:
    """The shape that costs a commit if anything goes wrong.

    A detached worktree committed into holds work no ref names, its tree is
    clean because the work is committed, and the record about to be removed is
    the only thing pointing at it. This is the case the oracle was built for."""
    tree = model.next_name("wt-")
    a_file = model.next_name("f") + ".txt"
    model.worktrees[tree] = WorktreeShape(name=tree, branch=None)
    return Step("orphan-commit-in-a-detached-worktree", worktree=tree, files=(a_file,))


def _editable(model: Model) -> list[WorktreeShape]:
    return [w for w in model.live_worktrees() if not w.dirty]


def _can_edit(model: Model) -> bool:
    return bool(_editable(model))


def _plan_edit_a_tracked_file(model: Model, rng: random.Random) -> Step:
    tree = rng.choice(_editable(model))
    tree.dirty = True
    return Step("edit-a-tracked-file", worktree=tree.name)


def _plan_leave_an_untracked_file(model: Model, rng: random.Random) -> Step:
    tree = rng.choice(_editable(model))
    tree.dirty = True
    return Step(
        "leave-an-untracked-file", worktree=tree.name, files=(model.next_name("u") + ".txt",)
    )


def _lockable(model: Model) -> list[WorktreeShape]:
    return [w for w in model.live_worktrees() if not w.locked]


def _can_lock(model: Model) -> bool:
    return bool(_lockable(model))


def _plan_lock_a_worktree(model: Model, rng: random.Random) -> Step:
    tree = rng.choice(_lockable(model))
    tree.locked = True
    return Step("lock-a-worktree", worktree=tree.name)


def _movable(model: Model) -> list[WorktreeShape]:
    return model.live_worktrees()


def _can_move(model: Model) -> bool:
    return bool(_movable(model))


def _plan_move_a_worktree_aside(model: Model, rng: random.Random) -> Step:
    tree = rng.choice(_movable(model))
    tree.moved = True
    return Step("move-a-worktree-aside", worktree=tree.name)


def _publishable(model: Model) -> list[tuple[str, BranchShape]]:
    """Which branch could go to which remote.

    ``origin`` is created first and always, because a repository whose trunk is
    published only by some other remote is a shape the tool deliberately stops
    on -- a real one, covered by a row in the enumerated matrix, and not what
    these draws are for. The second remote exists to put two of them in the
    same repository, which is where ref attribution can go wrong."""
    remotes = model.remotes or ["origin"]
    if len(model.remotes) == 1:
        remotes = [*model.remotes, "mirror"]
    return [(r, b) for r in remotes for b in model.branches.values() if r not in b.published]


def _can_publish(model: Model) -> bool:
    return bool(_publishable(model))


def _plan_publish_a_branch(model: Model, rng: random.Random) -> Step:
    remote, branch = rng.choice(_publishable(model))
    fresh = remote not in model.remotes
    if fresh:
        model.remotes.append(remote)
    branch.published = (*branch.published, remote)
    return Step("publish-a-branch", branch=branch.name, remote=remote)


def _published(model: Model) -> list[tuple[str, BranchShape]]:
    return [(r, b) for b in model.branches.values() for r in b.published]


def _can_drop_server_copy(model: Model) -> bool:
    return bool(_published(model))


def _plan_drop_the_server_copy(model: Model, rng: random.Random) -> Step:
    """Delete the branch on the server and leave this repository's cache of it
    alone, which is how a stale tracking ref happens: somebody else's cleanup
    ran, and nothing here has fetched since."""
    remote, branch = rng.choice(_published(model))
    branch.published = tuple(r for r in branch.published if r != remote)
    return Step("drop-the-server-copy", branch=branch.name, remote=remote)


def _plan_park_a_branch_on_the_trunk_tip(model: Model, _rng: random.Random) -> Step:
    """A branch cut from the trunk and never committed to. Ancestry proves it
    merged -- there is nothing on it to be unmerged -- so the only thing holding
    it back is that its tip is the trunk's."""
    name = "feat/" + model.next_name("p")
    model.branches[name] = BranchShape(name=name, merged=True, trunk_at_base=model.trunk_commits)
    return Step("park-a-branch-on-the-trunk-tip", branch=name)


ALPHABET: tuple[
    tuple[str, int, Callable[[Model], bool], Callable[[Model, random.Random], Step]], ...
] = (
    ("commit-on-trunk", 2, _can_always, _plan_commit_on_trunk),
    ("branch-and-commit", 1, _can_always, _plan_branch_and_commit),
    ("merge-branch", 4, _can_merge, _plan_merge_branch),
    ("squash-merge-branch", 4, _can_rewrite, _plan_squash_merge_branch),
    ("cherry-pick-branch", 4, _can_cherry_pick, _plan_cherry_pick_branch),
    ("back-out-branch-work", 1, _can_back_out, _plan_back_out_branch_work),
    ("worktree-on-new-branch", 1, _can_always, _plan_worktree_on_new_branch),
    ("detached-worktree", 1, _can_always, _plan_detached_worktree),
    (
        "orphan-commit-in-a-detached-worktree",
        1,
        _can_always,
        _plan_orphan_commit_in_a_detached_worktree,
    ),
    ("edit-a-tracked-file", 1, _can_edit, _plan_edit_a_tracked_file),
    ("leave-an-untracked-file", 1, _can_edit, _plan_leave_an_untracked_file),
    ("lock-a-worktree", 1, _can_lock, _plan_lock_a_worktree),
    ("move-a-worktree-aside", 1, _can_move, _plan_move_a_worktree_aside),
    ("publish-a-branch", 1, _can_publish, _plan_publish_a_branch),
    ("drop-the-server-copy", 1, _can_drop_server_copy, _plan_drop_the_server_copy),
    ("park-a-branch-on-the-trunk-tip", 1, _can_always, _plan_park_a_branch_on_the_trunk_tip),
)
"""Every shape the enumerated matrix reaches by hand, as operations that
compose. The matrix builds each row as a finished picture; these are the strokes
it was drawn with, and a draw puts them in an order nobody chose.

The weights buy interesting repositories out of a short draw. Nothing is
sweepable until something is merged, so under a flat draw most topologies were
repositories where the tool correctly declined everything -- safe, and asserting
almost nothing, because a run that deletes nothing satisfies the invariant
trivially. Weighting the three merge operations, and the trunk commit that
unlocks the patch-id tier, moved the corpus from five draws to fourteen where
the sweep has to take something. They are weights rather than a schedule: the
order stays the draw's."""


@dataclass(frozen=True)
class Recipe:
    """A planned topology: the operations, and the repository they describe."""

    seed: int
    steps: tuple[Step, ...]
    model: Model

    def story(self) -> str:
        """What a person needs to rebuild this repository by hand.

        This is what stands in for a property-testing library's shrinking: not a
        smaller failing case, but the exact one, spelled out well enough to
        reproduce without rerunning anything."""
        lines = "\n".join(f"  {n}. {step}" for n, step in enumerate(self.steps, start=1))
        return f"seed {self.seed} built this repository:\n{lines}"


def plan_topology(seed: int) -> Recipe:
    """Draw a topology. Pure: no git runs, nothing touches a disk.

    Keeping the draw separate from the build is what lets the corpus check
    inspect every seed for a fraction of a millisecond, and it removes the only
    way a generator can go quiet without anybody noticing -- an operation that
    silently fails to apply."""
    # The draw needs to be reproducible, not unguessable.
    rng = random.Random(seed)  # noqa: S311
    model = Model()
    steps: list[Step] = []
    for _ in range(rng.randint(*OPERATIONS_PER_TOPOLOGY)):
        applicable = [(name, weight, plan) for name, weight, can, plan in ALPHABET if can(model)]
        name, _weight, plan = rng.choices(applicable, weights=[w for _, w, _ in applicable])[0]
        step = plan(model, rng)
        assert step.op == name, f"{name} planned a step calling itself {step.op}"
        steps.append(step)
    return Recipe(seed=seed, steps=tuple(steps), model=model)


# -- building the drawn repository --------------------------------------------


def _new_repository(root: Path) -> Path:
    """One commit on `main`, and `main` spelled out.

    A repository's initial branch comes from `init.defaultBranch`, which differs
    between one developer's machine and the next and between both and CI, so a
    fixture that lets the host decide is a fixture that passes in one place."""
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    commit(root, "README.md", "hello\n")
    return root


@dataclass
class Built:
    """A repository, and the two facts about it the assertions need.

    ``rewritten`` is recorded as the copies are made rather than derived
    afterwards, because afterwards is too late: once the sweep has deleted the
    branch, nothing in the repository can say which commits its work became."""

    repo: Path
    rewritten: set[str] = field(default_factory=set)
    remotes: dict[str, Path] = field(default_factory=dict)

    def worktree_path(self, name: str) -> Path:
        return self.repo.parent / name


def _unmerged_commits(repo: Path, branch: str) -> list[str]:
    """The branch's own commits, oldest first -- what a replay copies, and so
    what a deletion of the branch afterwards is entitled to strand."""
    return git(repo, "rev-list", "--reverse", f"main..{branch}").split()


def build(recipe: Recipe, root: Path) -> Built:
    """Replay a plan against real git.

    Every step is spelled the way the enumerated matrix spells it, because those
    spellings were arrived at by finding out what git actually does -- a
    `--squash` that needs its own commit, a detached add that defaults to HEAD,
    a server-side deletion done on the server so this side's cache goes stale
    rather than being cleaned up with it."""
    built = Built(repo=_new_repository(root / "repo"))
    repo = built.repo
    for step in recipe.steps:
        tree = built.worktree_path(step.worktree)
        if step.op == "commit-on-trunk":
            commit(repo, step.files[0])
            _publish_the_trunk(built)
        elif step.op == "branch-and-commit":
            git(repo, "checkout", "-q", "-b", step.branch, *([step.base] if step.base else []))
            for name in step.files:
                commit(repo, name)
            git(repo, "checkout", "-q", "main")
        elif step.op == "merge-branch":
            git(repo, "merge", "-q", "--no-ff", "-m", f"merge {step.branch}", step.branch)
            _publish_the_trunk(built)
        elif step.op == "squash-merge-branch":
            built.rewritten.update(_unmerged_commits(repo, step.branch))
            git(repo, "merge", "-q", "--squash", step.branch)
            git(repo, "commit", "-q", "-m", f"squashed {step.branch}")
            _publish_the_trunk(built)
        elif step.op == "cherry-pick-branch":
            picked = _unmerged_commits(repo, step.branch)
            built.rewritten.update(picked)
            git(repo, "cherry-pick", *picked)
            _publish_the_trunk(built)
        elif step.op == "back-out-branch-work":
            git(repo, "checkout", "-q", step.branch)
            git(repo, "rm", "-q", "--", *step.files)
            git(repo, "commit", "-q", "-m", f"back out {step.branch}")
            git(repo, "checkout", "-q", "main")
        elif step.op == "worktree-on-new-branch":
            git(repo, "worktree", "add", "-q", str(tree), "-b", step.branch)
            commit(tree, step.files[0])
        elif step.op == "detached-worktree":
            git(repo, "worktree", "add", "-q", "--detach", str(tree))
        elif step.op == "orphan-commit-in-a-detached-worktree":
            git(repo, "worktree", "add", "-q", "--detach", str(tree))
            commit(tree, step.files[0], "the only copy\n")
        elif step.op == "edit-a-tracked-file":
            (tree / "README.md").write_text("edited, never committed\n", encoding="utf-8")
        elif step.op == "leave-an-untracked-file":
            (tree / step.files[0]).write_text("never added\n", encoding="utf-8")
        elif step.op == "lock-a-worktree":
            git(repo, "worktree", "lock", str(tree))
        elif step.op == "move-a-worktree-aside":
            tree.rename(built.worktree_path(f"{step.worktree}-elsewhere"))
        elif step.op == "publish-a-branch":
            _publish(built, step.remote, step.branch)
        elif step.op == "drop-the-server-copy":
            git(built.remotes[step.remote], "update-ref", "-d", f"refs/heads/{step.branch}")
        elif step.op == "park-a-branch-on-the-trunk-tip":
            git(repo, "branch", step.branch)
        else:
            raise AssertionError(f"the builder has no case for {step.op}")
    return built


def _publish(built: Built, remote: str, branch: str) -> None:
    """Push a branch to a remote, creating the remote the first time.

    The trunk goes up with the first remote and only the first: the tool reads
    the default branch off `origin`, and publishing a second copy of it
    elsewhere is a different shape than these draws are asserting about."""
    if remote not in built.remotes:
        bare = built.repo.parent / f"{remote}.git"
        SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(bare)])
        built.remotes[remote] = bare
        git(built.repo, "remote", "add", remote, str(bare))
        if remote == "origin":
            git(built.repo, "push", "-q", "-u", remote, "main")
    git(built.repo, "push", "-q", remote, branch)


def _publish_the_trunk(built: Built) -> None:
    """Keep the server's trunk level with this one, every time this one moves.

    Not decoration -- it is what decides whether anything is merged at all. Once
    a repository has an `origin`, merges are measured against `origin/main`
    rather than against the local branch of that name, which is the right
    reading: the local one is a ref its owner may do anything to. A generator
    that merged locally and never pushed would therefore produce repositories
    where nothing is provably merged, every sweep declines everything, and every
    reachability assertion in the corpus passes by having watched a run that did
    nothing. It is also the honest shape: a merge in a repository with a server
    is usually a merge that happened on the server first."""
    if "origin" in built.remotes:
        git(built.repo, "push", "-q", "origin", "main")


# -- the assertions -----------------------------------------------------------


@contextmanager
def _reported_with(story: str) -> Iterator[None]:
    """Attach the operation log to whatever fails inside.

    The oracle's own failure message names commits, which says what was lost but
    not what built the thing that lost it. A generated case is unreadable
    without its recipe, so the recipe travels with every assertion in the
    block."""
    try:
        yield
    except AssertionError as failure:
        raise AssertionError(f"{failure}\n\n{story}") from failure


def _reachable_branches(repo: Path) -> set[str]:
    return set(
        git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split("\n")
    ) - {""}


def _registered_worktrees(repo: Path) -> set[str]:
    """The paths git holds records for, minus the main checkout.

    Read from the record rather than from the filesystem: a worktree whose
    directory was moved aside still has one, and it is the record -- not the
    directory -- that a removal destroys."""
    paths = [
        line.split(" ", 1)[1].strip()
        for line in git(repo, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    ]
    return {Path(p).name for p in paths[1:]}


def _commits(repo: Path) -> set[str]:
    """Every commit some ref or worktree HEAD holds, which is the oracle's own
    definition -- asked again here so the allowance can be narrowed to the
    commits this run actually stranded rather than the ones it was permitted
    to."""
    heads = [
        line.split(" ", 1)[1].strip()
        for line in git(repo, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("HEAD ")
    ]
    return set(git(repo, "rev-list", "--all", *heads).split())


def _must_be_swept(model: Model) -> set[str]:
    """The branches a bare sweep has no ground to refuse.

    Deliberately an under-approximation, and deliberately narrow: it is here so
    a draw that swept nothing cannot pass by asserting nothing, not to
    re-derive the tool's judgement. A branch carrying commits, proven merged by
    a merge this test performed, with no worktree standing on it, clears all six
    questions -- it is not the trunk, its tip is not the trunk's because every
    merge here writes a commit of its own, and a branch nothing is checked out
    on has no working tree to be dirty. Anything a worktree holds is left out
    whatever its state, because that is where the refusals live."""
    return {
        b.name for b in model.branches.values() if b.merged and b.commits > 0 and b.worktree is None
    }


@pytest.mark.parametrize("seed", SEEDS, ids=lambda seed: f"seed-{seed}")
def test_a_bare_sweep_over_a_generated_repository_strands_no_work(
    seed: int, tmp_path: Path
) -> None:
    """The property, over a repository nobody designed.

    Three claims, in the order they matter. Nothing that was reachable stops
    being reachable, except commits this test itself copied onto the trunk under
    new hashes. No server loses anything at all. And the sweep did enough for
    the first two to mean something -- a run that deleted nothing satisfies any
    reachability assertion ever written."""
    recipe = plan_topology(seed)
    built = build(recipe, tmp_path)
    repo = built.repo
    story = recipe.story()

    with _reported_with(story):
        assert _reachable_branches(repo) == {"main", *recipe.model.branches}
        assert _registered_worktrees(repo) == set(recipe.model.worktrees)

        with ExitStack() as guards:
            guard = guards.enter_context(reachability_guard(repo))
            for bare in built.remotes.values():
                guards.enter_context(reachability_guard(bare))
            before = _commits(repo)
            payload = report(repo, "--cleanup", now=A_FIXED_CLOCK, port=GitOnly())
            guard.expect_unreachable(*(built.rewritten & (before - _commits(repo))))

        assert payload["_exit"] in (EXIT_OK, EXIT_ANOMALY), anomaly_lines(payload)
        deleted = {d["name"] for d in payload["execution"]["deletions"] if d["deleted"]}  # type: ignore[index]
        assert _must_be_swept(recipe.model) <= deleted


def test_the_corpus_keeps_producing_repositories_worth_sweeping() -> None:
    """A generator that quietly stops generating leaves a suite that passes.

    Planning is pure, so the whole corpus can be inspected without building it,
    and this asks the questions that would go unanswered if a predicate started
    refusing or an operation stopped being reachable: does every operation in
    the alphabet occur somewhere, does the corpus collectively produce branches,
    worktrees and a remote, and does every single draw leave something for a
    sweep to have an opinion about."""
    recipes = [plan_topology(seed) for seed in SEEDS]
    performed = {step.op for recipe in recipes for step in recipe.steps}
    alphabet = {name for name, _, _, _ in ALPHABET}

    assert performed == alphabet, (
        f"the corpus never performs {sorted(alphabet - performed)}, so those operations are "
        f"asserted about by nothing"
    )
    assert sum(len(r.model.branches) for r in recipes) >= len(SEEDS)
    assert sum(len(r.model.worktrees) for r in recipes) >= len(SEEDS) // 2
    assert any(r.model.remotes for r in recipes)
    assert all(r.model.branches or r.model.worktrees for r in recipes), (
        "a draw that creates neither a branch nor a worktree is a repository the sweep "
        "has nothing to say about"
    )
    acting = [r for r in recipes if _must_be_swept(r.model)]
    assert len(acting) >= len(SEEDS) // 3, (
        f"only {len(acting)} of {len(SEEDS)} draws contain anything the sweep is obliged to "
        f"take, so most of the corpus would be watching a run that does nothing and "
        f"reporting that it lost nothing"
    )
