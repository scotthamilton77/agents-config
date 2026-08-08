"""gitclean against real git, in throwaway repositories.

Everything above ``ports.py`` is tested against ``ScriptedCommands``, which
pins the code to the author's beliefs about git's output. That is the right
trade for the judgement rules, and the wrong one for the claims this tool
makes about git itself -- most of all the squash-merge detector, the entire
reason the package exists, which those tests only ever showed a transcript
somebody wrote by hand.

So these build actual repositories and run the actual CLI over them. They are
hermetic: every repo lives in a tmp directory, and ``has_gh`` is forced off so
nothing reaches the network. PR-state evidence is not exercised here -- it has
no git-side behaviour to get wrong, and the unit suite covers it.

Every test that lets gitclean touch a repository runs inside
``reachability_guard``. Its assertions are about the topology the author had in
mind; the guard is about every commit in the repository, including the ones
nobody thought of.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from reachability import reachability_guard

from gitclean.cli import EXIT_ANOMALY, EXIT_OK, EXIT_REFUSED, main
from gitclean.execute import Executor
from gitclean.model import MergeEvidence, Plan, Target, TargetKind
from gitclean.ports import CommandPort, CommandResult, SubprocessCommands
from gitclean.survey import survey as run_survey


class GitOnly(SubprocessCommands):
    """The real port with gh switched off.

    A tmp repository has no GitHub remote, so a live `gh pr list` would fail
    anyway -- but it would fail slowly, and differently depending on whether
    the machine running the suite happens to have gh installed and
    authenticated. Declaring it absent makes these runs identical everywhere."""

    def has_gh(self) -> bool:
        return False


def git(repo: Path, *args: str) -> str:
    """Run git for test setup, insisting it worked.

    Setup goes through the same port as production so a broken argv fails here
    rather than being quietly absorbed."""
    result = SubprocessCommands().git(list(args), cwd=repo)
    if not result.ok:
        raise AssertionError(f"setup command failed: git {' '.join(args)}\n{result.stderr}")
    return result.out


def commit(repo: Path, name: str, content: str = "x") -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", "--", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one commit on `main` and nothing else."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    commit(root, "README.md", "hello\n")
    return root


class Recording(GitOnly):
    """The real port, keeping the argv of everything it ran.

    Asserting on the return value cannot answer "did this run reach the
    server": a `push --delete` that failed, or one whose outcome the report
    folded into a count, reads the same as one that never happened. The
    transcript says what was actually issued."""

    def __init__(self) -> None:
        super().__init__()
        self.transcript: list[tuple[str, ...]] = []

    def git(self, args: Sequence[str], *, cwd: Path | None = None) -> CommandResult:
        self.transcript.append(("git", *args))
        return super().git(args, cwd=cwd)


def remotes_asked(transcript: list[tuple[str, ...]]) -> list[str]:
    """Every remote an `ls-remote` in this transcript was pointed at.

    Two questions reach a remote by that command and they are spelled
    differently: the survey asks one what it still advertises
    (`ls-remote --heads -- <remote>`), and the deletion asks after a single ref
    on it (`ls-remote --heads <remote> <ref>`). The remote is the first
    argument that is not an option in both, which is what this reads -- a fixed
    position is not something the two spellings share."""
    return [
        next(arg for arg in call[call.index("ls-remote") + 1 :] if not arg.startswith("-"))
        for call in transcript
        if "ls-remote" in call
    ]


def report(
    repo: Path, *args: str, now: datetime | None = None, port: CommandPort | None = None
) -> dict[str, object]:
    """Run the CLI in-process and return the parsed envelope."""
    out = StringIO()
    code = main(
        list(args) or ["--report"],
        port=port if port is not None else GitOnly(),
        cwd=repo,
        now=now or datetime.now(UTC),
        out=out,
    )
    payload = json.loads(out.getvalue())
    payload["_exit"] = code
    return payload


def find(payload: dict[str, object], target_id: str) -> dict[str, object]:
    targets = payload["targets"]
    assert isinstance(targets, list)
    match = next((t for t in targets if t["id"] == target_id), None)
    assert match is not None, f"{target_id} not in {[t['id'] for t in targets]}"
    return match


def refusals(payload: dict[str, object]) -> list[dict[str, object]]:
    """The objections a cleanup raised, each about one name the caller gave.

    Read out of the plan rather than out of the envelope's `refusal` field.
    That field is the run having nothing to act on at all, and a cleanup no
    longer produces one: the names that resolved cleanly are still deleted, so
    there is always a plan."""
    plan = payload["plan"]
    assert isinstance(plan, dict)
    entries = plan["refused"]
    assert isinstance(entries, list)
    assert all(isinstance(entry, dict) for entry in entries), entries
    return entries


def anomaly_lines(payload: dict[str, object]) -> str:
    execution = payload["execution"]
    assert isinstance(execution, dict)
    return "\n".join(
        line
        for entry in execution["anomalies"]
        for line in (entry["message"], *entry["transcript"])
    )


# -- the squash-merge detector ------------------------------------------------


def test_a_real_squash_merge_is_detected(repo: Path) -> None:
    """The claim the whole package rests on, against a squash merge git
    actually performed.

    `git branch --merged` cannot see this: the squashed commit on main shares
    no patch-id with either branch commit and the tip is an ancestor of
    nothing. Two commits are used deliberately -- with one, patch-id
    equivalence would settle it and the squash tier would never run."""
    git(repo, "checkout", "-q", "-b", "feat/squashed")
    commit(repo, "one.txt")
    commit(repo, "two.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/squashed")
    git(repo, "commit", "-q", "-m", "squashed feat")

    assert "feat/squashed" not in git(repo, "branch", "--merged", "main")

    with reachability_guard(repo):  # a report changes nothing
        payload = report(repo)
    branches = payload["repo"]
    assert isinstance(branches, dict)
    feat = next(b for b in branches["branches"] if b["name"] == "feat/squashed")

    assert feat["merge_evidence"] == "squash_equal"
    assert feat["merged"] is True
    assert find(payload, "branch:feat/squashed")["sweepable"] is True


def test_a_genuinely_unmerged_branch_is_not_swept(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feat/live")
    commit(repo, "unique.txt")
    git(repo, "checkout", "-q", "main")

    with reachability_guard(repo):
        payload = report(repo)
    target = find(payload, "branch:feat/live")

    assert target["sweepable"] is False
    assert "no merge proof" in str(target["withheld"])
    assert payload["summary"]["sweepable_now"] == 0  # type: ignore[index]


def test_a_squash_merged_branch_is_actually_deleted(repo: Path) -> None:
    """End to end: prove it, plan it, delete it, and re-ask git. The one
    capability that justifies bypassing git's own `branch -d` refusal, which
    cannot see a squash merge and so would never clean anything."""
    git(repo, "checkout", "-q", "-b", "feat/done")
    first = commit(repo, "a.txt")
    second = commit(repo, "b.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/done")
    git(repo, "commit", "-q", "-m", "squashed")

    assert not SubprocessCommands().git(["branch", "-d", "feat/done"], cwd=repo).ok

    with reachability_guard(repo) as guard:
        payload = report(repo, "--cleanup")
        # A squash rewrites the work into one new commit on main, so these two
        # are stranded by design -- that is what the sweep exists to remove.
        guard.expect_unreachable(first, second)

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/done") == ""
    deletions = payload["execution"]["deletions"]  # type: ignore[index]
    assert [d["name"] for d in deletions] == ["feat/done"]
    assert deletions[0]["verified"] is True


# -- the trunk ----------------------------------------------------------------


def _with_remote(repo: Path, tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    # `-b main` rather than letting the machine decide: a bare repo's HEAD comes
    # from `init.defaultBranch`, so on a host that never set it HEAD names a
    # `master` this fixture then never creates. Publishing it is what
    # `remote set-head -a` reads, and it fails outright with no branch there.
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(bare)])
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


def test_the_trunk_is_never_swept_although_it_is_provably_merged(
    repo: Path, tmp_path: Path
) -> None:
    """Measured, not imagined: once main is pushed, `main` is an ancestor of
    `origin/main`, so `branch:main` carries merge evidence `ancestor` and merge
    evidence alone hands the trunk to the sweep. `main` and `origin/main` are
    also different strings for the same trunk, which is why the check is not a
    name comparison."""
    _with_remote(repo, tmp_path)

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    trunk = find(payload, "branch:main")
    assert trunk["merge_evidence"] == MergeEvidence.ANCESTOR.value
    assert trunk["merge_proven"] is True
    assert trunk["sweepable"] is False
    assert "trunk" in str(trunk["withheld"])
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/main") != ""


def test_naming_the_branch_you_are_standing_on_gets_gits_own_refusal(repo: Path) -> None:
    """Naming a target is an authorisation, so nothing here re-derives whether
    it is wise. git will not delete a branch a worktree holds, and its message
    -- read off the disk as the deletion is attempted, and naming the worktree
    -- is what the caller gets, with the argv that produced it."""
    git(repo, "checkout", "-q", "-b", "feat/parked")
    commit(repo, "parked.txt")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", "feat/parked")

    assert payload["_exit"] == EXIT_ANOMALY
    assert refusals(payload) == []
    said = anomaly_lines(payload)
    assert "cannot delete branch" in said
    assert str(repo) in said
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feat/parked"
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/parked") != ""


def test_a_neighbouring_repository_is_never_surveyed(tmp_path: Path, repo: Path) -> None:
    """Scope is the current repository. A sibling checkout sharing a parent
    directory is somebody else's work."""
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    git(neighbour, "init", "-q", "-b", "main")
    git(neighbour, "config", "user.email", "test@example.invalid")
    git(neighbour, "config", "user.name", "Test")
    commit(neighbour, "theirs.txt")
    git(neighbour, "checkout", "-q", "-b", "their/secret-branch")

    # The neighbour is guarded too: not surveying it and not touching it are
    # separate claims, and only the second one is about somebody else's work.
    with reachability_guard(repo), reachability_guard(neighbour):
        payload = report(repo)

    names = [t["name"] for t in payload["targets"]]  # type: ignore[union-attr]
    assert not any("secret" in str(n) for n in names)
    assert not any(str(neighbour) in str(n) for n in names)


# -- worktrees ----------------------------------------------------------------


def _worktree(repo: Path, name: str, branch: str) -> Path:
    path = repo.parent / name
    git(repo, "worktree", "add", "-q", str(path), "-b", branch)
    return path


def test_a_worktree_whose_path_holds_a_newline_is_surveyed_and_removed_whole(
    repo: Path, tmp_path: Path
) -> None:
    """A path may contain a newline, and `worktree list --porcelain` emits it
    raw rather than escaping it -- verified here against git rather than
    against a belief about git.

    Split that listing on newlines and the worktree is recorded under a path
    cut short at the newline, with nothing counted as lost. Naming the real
    path then matches nothing, and the run says there is nothing to delete
    about a tree that is sitting there."""
    path = tmp_path / "wt\nnewline"
    git(repo, "worktree", "add", "-q", str(path), "-b", "feat/odd")
    listing = git(repo, "worktree", "list", "--porcelain")
    assert f"worktree {path}" in listing  # git escapes nothing; the newline is raw

    surveyed = report(repo)
    repository = surveyed["repo"]
    assert isinstance(repository, dict)
    assert str(path) in [w["path"] for w in repository["worktrees"]]
    assert repository["dropped_worktrees"] == 0

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", str(path))

    assert payload["_exit"] == EXIT_OK, anomaly_lines(payload)
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert plan["absent"] == []
    deletion = payload["execution"]["deletions"][0]  # type: ignore[index]
    assert (deletion["deleted"], deletion["verified"]) == (True, True)
    assert not path.exists()
    assert str(path) not in git(repo, "worktree", "list", "--porcelain")


def test_a_run_inside_a_worktree_whose_path_holds_a_newline_does_not_sweep_itself(
    repo: Path, tmp_path: Path
) -> None:
    """The path arrives whole from the worktree listing, which is framed with
    NUL -- and as `rev-parse --show-toplevel`, which is not framed at all and
    has no `-z` to ask for. Read that answer a line at a time and the run
    records itself as living at `.../wt`, the two spellings stop matching, and
    both guards on the worktree the process is executing in miss it.

    Nothing else is left to catch it: the branch below is provably merged, the
    tree is clean, and the `--no-ff` keeps it off the trunk's tip -- so the
    guard that knows this is the working directory is the last one standing,
    and a bare sweep with it disabled removes the ground it is standing on."""
    path = tmp_path / "wt\nnl"
    git(repo, "worktree", "add", "-q", str(path), "-b", "feat/odd")
    commit(path, "odd.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/odd", "feat/odd")

    with reachability_guard(repo):
        payload = report(path, "--cleanup")

    surveyed = payload["repo"]
    assert isinstance(surveyed, dict)
    assert surveyed["repo_root"] == str(path)
    target = find(payload, f"worktree:{path}")
    # Merge-proven and clean, so the sentence has to be the specific one.
    assert target["merge_proven"] is True
    assert target["sweepable"] is False
    assert "executing in" in str(target["withheld"])
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert [d for d in execution["deletions"] if d["deleted"]] == []
    assert (path / "odd.txt").exists()


def test_a_dirty_worktree_named_outright_is_left_to_git_to_refuse(repo: Path) -> None:
    """No flag here turns git's dirt check off, and adding one would mean
    re-implementing in Python what git has just read off the disk. The refusal
    surfaces verbatim and the work is still on the filesystem."""
    work = _worktree(repo, "wt-dirty", "feat/wt")
    (work / "README.md").write_text("edited but never committed\n", encoding="utf-8")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", str(work))

    assert payload["_exit"] == EXIT_ANOMALY
    assert work.exists()
    assert (work / "README.md").read_text(encoding="utf-8").startswith("edited")
    assert "contains modified or untracked files" in anomaly_lines(payload)


def test_a_worktree_holding_only_ignored_files_still_sweeps(repo: Path) -> None:
    """The settled trade, against real git: ignored content is reported but
    does not keep a finished worktree out of the sweep. Treating caches as work
    at risk would put a manual triage in front of every automatic cleanup."""
    (repo / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    git(repo, "add", "--", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore caches")

    work = _worktree(repo, "wt-cached", "feat/cached")
    commit(work, "feature.txt")
    (work / ".cache").mkdir()
    (work / ".cache" / "blob").write_text("regenerates for free\n", encoding="utf-8")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/cached", "feat/cached")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    assert payload["_exit"] == EXIT_OK
    assert not work.exists()
    target = find(payload, f"worktree:{work}")
    assert target["sweepable"] is True
    assert any("ignored file" in r for r in target["reasons"])  # type: ignore[union-attr]


def test_a_worktree_holding_uncommitted_work_survives_a_bare_sweep(repo: Path) -> None:
    """The commit it holds is merged, so the first question waves it through.
    What stops it is the working tree: an untracked file exists nowhere else,
    and an unattended run must leave it standing rather than deciding for the
    person using it. The counts go in the report so they can."""
    work = _worktree(repo, "wt-live", "feat/live-wt")
    commit(work, "done.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/live-wt", "feat/live-wt")
    (work / "in-progress.txt").write_text("uncommitted\n", encoding="utf-8")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    assert payload["_exit"] == EXIT_OK
    assert work.exists()
    assert (work / "in-progress.txt").exists()
    target = find(payload, f"worktree:{work}")
    assert target["merge_proven"] is True
    assert target["sweepable"] is False
    assert "1 untracked file(s)" in str(target["withheld"])


def test_naming_a_detached_worktree_removes_it_and_says_what_that_cost(repo: Path) -> None:
    """The gap in "git's own refusals are enough", and what is done about it.

    They cover uncommitted content. They say nothing about a commit made
    inside the worktree on no branch: that tree is clean, git removes it
    without complaint, and the record it deletes is the only thing that held
    HEAD -- the per-worktree reflog goes with it. No ref, no reflog.

    Naming a target is an authorisation to delete a checkout, and the caller
    owns what that spends. So the removal happens, and the row for it names the
    commit that is now reachable from nothing and the one command that keeps
    it. The guard is told about that commit by name, because a run that strands
    one silently is what it exists to catch."""
    work = repo.parent / "wt-orphan"
    git(repo, "worktree", "add", "-q", "--detach", str(work))
    only = commit(work, "only.txt", "the only copy\n")

    with reachability_guard(repo) as exemptions:
        exemptions.expect_unreachable(only)
        payload = report(repo, "--cleanup", f"worktree:{work}")

    assert payload["_exit"] == EXIT_OK, anomaly_lines(payload)
    assert not work.exists()
    assert git(repo, "for-each-ref", "--count=1", f"--contains={only}") == ""
    deletion = payload["execution"]["deletions"][0]  # type: ignore[index]
    assert (deletion["deleted"], deletion["verified"]) == (True, True)
    assert only[:8] in str(deletion["detail"])
    assert "git branch" in str(deletion["detail"])


def test_a_bare_sweep_will_not_touch_a_worktree_holding_an_orphan_commit(repo: Path) -> None:
    """The same repository, with nobody naming anything. The narrowing above is
    the named path's alone: a commit no ref contains carries no merge proof, so
    the sweep withholds the tree long before any of this is reached, and the
    commit is still there afterwards with the guard given no exemption to
    excuse it."""
    work = repo.parent / "wt-orphan-swept"
    git(repo, "worktree", "add", "-q", "--detach", str(work))
    only = commit(work, "only.txt", "the only copy\n")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    assert payload["_exit"] == EXIT_OK
    assert work.exists()
    assert git(repo, "rev-parse", "--verify", f"{only}^{{commit}}") == only
    assert find(payload, f"worktree:{work}")["sweepable"] is False


def test_naming_a_worktree_whose_commit_a_branch_holds_costs_nothing(repo: Path) -> None:
    """The disclosure is about reachability, not about being detached. A commit
    some branch contains survives the removal, so the row for it says only that
    the worktree was removed -- otherwise every ordinary cleanup would carry a
    warning about work that is in no danger, and the one that matters would
    read as more of the same."""
    work = _worktree(repo, "wt-kept", "feat/kept")
    commit(work, "kept.txt")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", f"worktree:{work}")

    assert payload["_exit"] == EXIT_OK
    assert not work.exists()
    assert payload["execution"]["deletions"][0]["detail"] == "worktree removed"  # type: ignore[index]


def test_the_worktree_the_run_executes_in_is_never_deleted(repo: Path) -> None:
    """Removing it deletes the process's own working directory, and every git
    call after that fails against a path that is no longer there -- failures
    that read as unrelated problems rather than as this one."""
    work = _worktree(repo, "wt-self", "feat/self")
    commit(work, "self.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/self", "feat/self")

    with reachability_guard(repo):
        swept = report(work, "--cleanup")
        named = report(work, "--cleanup", f"worktree:{work}")

    assert work.exists()
    assert swept["_exit"] == EXIT_OK
    assert "executing in" in str(find(swept, f"worktree:{work}")["withheld"])
    assert named["_exit"] == EXIT_REFUSED
    refused = refusals(named)
    assert [r["code"] for r in refused] == ["E_INVOKING_WORKTREE"]
    assert str(work) in str(refused[0]["message"])


def test_a_refusal_beside_a_merged_branch_still_leaves_the_branch_deleted(repo: Path) -> None:
    """Partial execution, asked of git rather than of the run's own report.

    Two names in one command: `feat/done`, provably merged, and the worktree
    the process is executing in, which can never go while it is standing there.
    Aborting the selection over the second would spend the first as well, and
    the caller's remedy would be to re-run with the offender removed -- a round
    trip over a name the tool has already worked out it cannot act on.

    Both halves have to be true at once, and each is what stops the other being
    read wrong: a caller who sees only exit 1 must not conclude the deletion
    did not happen, and one who sees only the deletion must not conclude the
    command was carried out. So the branch is looked for in git afterwards,
    not in the envelope that has an interest in the answer."""
    git(repo, "checkout", "-q", "-b", "feat/done")
    commit(repo, "done.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/done", "feat/done")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", "feat/done", f"worktree:{repo}")

    assert payload["_exit"] == EXIT_REFUSED, anomaly_lines(payload)
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/done") == ""
    assert repo.exists()
    assert str(repo) in git(repo, "worktree", "list", "--porcelain")
    assert [r["code"] for r in refusals(payload)] == ["E_INVOKING_WORKTREE"]


def test_a_worktree_that_goes_dirty_after_the_survey_is_left_alone(repo: Path) -> None:
    """The window this tool re-surveys to close, forced open.

    The plan was built when the tree was clean, so nothing was archived.
    Reality says the tree has changes. `worktree remove` without --force is the
    only thing left that can notice, which is why it is never spent."""
    work = _worktree(repo, "wt-race", "feat/race")
    survey_data = run_survey(GitOnly(), cwd=repo)
    assert not isinstance(survey_data, str)

    # ... and now the agent that owns this worktree writes a file.
    (work / "urgent.txt").write_text("work that exists nowhere else\n", encoding="utf-8")

    stale = Target(
        id=f"worktree:{work}",
        kind=TargetKind.WORKTREE,
        name=str(work),
        merge_evidence=MergeEvidence.ANCESTOR,
        merge_proven=True,
        sweepable=True,
        withheld=None,
        reasons=(),
        last_activity=None,
    )
    with reachability_guard(repo):
        outcome = Executor(GitOnly(), survey_data, cwd=repo).run(
            Plan(targets=(stale,), salvage_dir=None, dry_run=False)
        )

    assert not outcome.ok
    assert work.exists()
    assert (work / "urgent.txt").read_text(encoding="utf-8").startswith("work that exists")
    assert "git refused to remove worktree" in outcome.anomalies[0].message
    assert any("--force" in line for line in outcome.anomalies[0].transcript)


# -- the pairing a reader groups rows by --------------------------------------
#
# The values worth crossing this with are the ones a naive recovery divides on.
# Three are exercised below -- a worktree path containing the separator a
# reason sentence uses, a remote whose own name contains the slash in
# `<remote>/<ref>`, and a newline inside a worktree path. One is deliberately
# absent:
#
# - a branch name containing a space, because git will not make one. `git branch
#   'feat with space'` is refused as an invalid ref name, so no repository can
#   present the value and a test would be asserting against git's own rules.


def test_the_pairing_holds_for_a_path_no_sentence_can_be_split_on(
    repo: Path, tmp_path: Path
) -> None:
    """Why the pairing is a field and not a sentence.

    `checked out at /a/b at rest` contains two ` at `s, and the only reader
    that recovers the path is one that never split it. A directory named this
    way is unusual; a directory whose name contains a word this tool happens to
    use in a reason is not, and the row it mis-keys reports the wrong worktree
    while looking exactly like a measurement.

    Real git, because the point is what git accepts as a path and as a ref."""
    _with_remote(repo, tmp_path)
    work = repo.parent / "wt at rest"
    git(repo, "worktree", "add", "-q", str(work), "-b", "feat/paired")
    commit(work, "paired.txt")
    git(work, "push", "-q", "-u", "origin", "feat/paired")

    with reachability_guard(repo):  # a report changes nothing
        payload = report(repo)

    branch = find(payload, "branch:feat/paired")
    assert branch["pairing"] == {
        "worktree": {"name": str(work), "id": f"worktree:{work}", "known": True},
        "upstream": {
            "name": "origin/feat/paired",
            "id": "remote:origin/feat/paired",
            "known": True,
        },
    }
    assert find(payload, f"worktree:{work}")["pairing"] == {
        "branch": {"name": "feat/paired", "id": "branch:feat/paired", "known": True}
    }
    assert find(payload, "remote:origin/feat/paired")["pairing"] == {}

    # The route the field replaces, run against the same row: the reason names
    # the path and gives a splitter no way to tell where it ends.
    prose = next(r for r in branch["reasons"] if str(r).startswith("checked out at"))
    assert str(prose).split(" at ")[1] != str(work)


def test_a_branch_tracking_a_ref_this_tool_will_not_target_still_names_it(
    repo: Path, tmp_path: Path
) -> None:
    """`main` tracks `origin/main`, and the server's copy of the trunk is
    deliberately not offered as a target. So the upstream is named with no row
    to follow -- which is a third answer, and dropping the name to reach one of
    the other two would report the trunk as never pushed."""
    _with_remote(repo, tmp_path)

    with reachability_guard(repo):
        payload = report(repo)

    assert find(payload, "branch:main")["pairing"]["upstream"] == {
        "name": "origin/main",
        "id": None,
        "known": True,
    }


def test_a_branch_tracking_a_local_branch_is_given_no_copy_on_the_server(repo: Path) -> None:
    """The upstream a branch records is not always a ref a remote publishes.

    `git branch --set-upstream-to=main feat/local` is a pairing made entirely on
    this disk, and this repository has no remote at all -- so a row claiming a
    server counterpart here names something that exists nowhere. Real git,
    because the whole question is what git records for that command: shortened,
    the upstream is `main`, which is indistinguishable from a ref a remote
    called `main` publishes."""
    git(repo, "checkout", "-q", "-b", "feat/local")
    commit(repo, "local.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "--set-upstream-to=main", "feat/local")

    with reachability_guard(repo):  # a report changes nothing
        payload = report(repo)

    survey_data = payload["repo"]
    assert isinstance(survey_data, dict)
    branches = survey_data["branches"]
    assert isinstance(branches, list)
    row = next(b for b in branches if b["name"] == "feat/local")
    # What git recorded, which is what the pairing has to be read from: the
    # short name says `main` for either kind of upstream, the full one does not.
    assert row["upstream"] == "main"
    assert row["upstream_ref"] == "refs/heads/main"

    target = find(payload, "branch:feat/local")
    assert target["pairing"]["upstream"] == {"name": None, "id": None, "known": True}
    # And the row is not silent about the tracking it declines to publish, which
    # is what would leave it reading like a branch that tracks nothing.
    assert any("tracks the local branch main" in str(r) for r in target["reasons"])
    assert not any("never pushed" in str(r) for r in target["reasons"])


def test_the_pairing_holds_when_the_remote_s_own_name_holds_a_slash(
    repo: Path, tmp_path: Path
) -> None:
    """The other delimiter, and the one a name is genuinely allowed to contain.

    `git remote add team/origin <url>` is accepted, so the slash in
    `<remote>/<ref>` is not a boundary anything can be split at: recovering the
    server copy of `feat/slashed` by cutting `team/origin/feat/slashed` at the
    first slash asks after a remote called `team` and a ref that is not there.

    Nothing here splits it. The upstream a branch records and the short name
    the server ref carries are compared whole, so the row is keyed by the name
    git printed rather than by a guess about where it divides."""
    bare = tmp_path / "server.git"
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(bare)])
    git(repo, "remote", "add", "team/origin", str(bare))
    git(repo, "push", "-q", "-u", "team/origin", "main")
    git(repo, "checkout", "-q", "-b", "feat/slashed")
    commit(repo, "slashed.txt")
    git(repo, "push", "-q", "-u", "team/origin", "feat/slashed")
    git(repo, "checkout", "-q", "main")
    git(repo, "fetch", "-q", "team/origin")

    with reachability_guard(repo):
        payload = report(repo)

    pairing = find(payload, "branch:feat/slashed")["pairing"]
    assert isinstance(pairing, dict)
    assert pairing["upstream"] == {
        "name": "team/origin/feat/slashed",
        "id": "remote:team/origin/feat/slashed",
        "known": True,
    }
    # And the id is a row rather than a string that resembles one: a pairing
    # that names a counterpart nothing in the report describes is the state
    # `id: null` exists to report, so a non-null one has to resolve.
    assert find(payload, "remote:team/origin/feat/slashed")["name"] == "team/origin/feat/slashed"


def test_the_pairing_holds_for_a_path_holding_a_newline(repo: Path, tmp_path: Path) -> None:
    """Proving the pairing for this value takes two things at once: `-z`
    framing, which keeps a newline inside the worktree listing whole, and the
    pairing fields themselves. Neither alone says the relation holds for this
    value -- without the framing a truncated path and an untruncated one key the
    same rows either way, and a test written against that would pin the
    truncation rather than the relation.

    So the pairing is asked to key both directions by a path that contains the
    one character `worktree list --porcelain` prints raw and does not frame with
    anything but `-z`."""
    _with_remote(repo, tmp_path)
    work = tmp_path / "wt\nnewlined"
    git(repo, "worktree", "add", "-q", str(work), "-b", "feat/newlined")
    commit(work, "newlined.txt")
    git(work, "push", "-q", "-u", "origin", "feat/newlined")

    with reachability_guard(repo):  # a report changes nothing
        payload = report(repo)

    branch = find(payload, "branch:feat/newlined")
    assert branch["pairing"] == {
        "worktree": {"name": str(work), "id": f"worktree:{work}", "known": True},
        "upstream": {
            "name": "origin/feat/newlined",
            "id": "remote:origin/feat/newlined",
            "known": True,
        },
    }
    assert find(payload, f"worktree:{work}")["pairing"] == {
        "branch": {"name": "feat/newlined", "id": "branch:feat/newlined", "known": True}
    }


def test_a_detached_worktree_says_it_holds_no_branch_rather_than_saying_nothing(
    repo: Path,
) -> None:
    """git's listing answers this outright, so the row carries a measured none
    -- distinguishable from a branch that went unread, which is the whole
    reason the entry carries `known` as well as a name."""
    work = repo.parent / "wt-loose"
    git(repo, "worktree", "add", "-q", "--detach", str(work))

    with reachability_guard(repo):
        payload = report(repo)

    assert find(payload, f"worktree:{work}")["pairing"] == {
        "branch": {"name": None, "id": None, "known": True}
    }


# -- remote deletion ----------------------------------------------------------


def test_a_bare_sweep_never_deletes_a_server_ref(repo: Path, tmp_path: Path) -> None:
    """A merged remote branch qualifies on evidence and is still left alone.
    Deleting it is irreversible for everyone fetching it and the server keeps
    no reflog, so it takes an explicit name every time."""
    bare = _with_remote(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "feat/pushed")
    commit(repo, "pushed.txt")
    git(repo, "push", "-q", "-u", "origin", "feat/pushed")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/pushed", "feat/pushed")
    # Pushed, so the server's own trunk contains it: the remote ref is merged by
    # the same evidence the local branch is, and only the rule about server refs
    # separates them.
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")

    with reachability_guard(repo), reachability_guard(bare):
        payload = report(repo, "--cleanup")

    assert payload["_exit"] == EXIT_OK
    assert "feat/pushed" in git(repo, "ls-remote", "--heads", "origin", "feat/pushed")
    target = find(payload, "remote:origin/feat/pushed")
    assert target["merge_proven"] is True
    assert target["sweepable"] is False
    assert "server" in str(target["withheld"])


def _push_only_copy(repo: Path, branch: str) -> str:
    """Publish a commit and step off the branch, leaving the server holding a
    copy this run is about to delete."""
    git(repo, "checkout", "-q", "-b", branch)
    head = commit(repo, f"{branch.replace('/', '-')}.txt", "the only copy\n")
    git(repo, "push", "-q", "-u", "origin", branch)
    git(repo, "checkout", "-q", "main")
    return head


def test_a_salvaged_server_ref_restores_by_the_command_the_tool_printed(
    repo: Path, tmp_path: Path
) -> None:
    """The one deletion with no undo behind it, and the bundle is the whole of
    the safety net -- so the net is tested by using it.

    The restore command is not read for plausibility, it is executed exactly as
    printed, and the commit the server lost has to come back out of it. A
    bundle holding only a remote-tracking ref satisfies `bundle verify` and
    clones back an empty repository, which is why verifying the archive is not
    the same as proving the restore."""
    bare = _with_remote(repo, tmp_path)
    only = _push_only_copy(repo, "feat/gone")

    # The server is what is guarded: `push --delete` is what this run performs,
    # and the server keeps no reflog to take it back with.
    with reachability_guard(bare) as guard:
        payload = report(repo, "--cleanup", "origin/feat/gone")
        salvages = payload["execution"]["salvages"]  # type: ignore[index]
        assert len(salvages) == 1, payload["execution"]
        guard.proven_by_bundle(Path(str(salvages[0]["path"])))

    assert payload["_exit"] == EXIT_OK
    assert "feat/gone" not in git(repo, "ls-remote", "--heads", "origin")

    printed = str(salvages[0]["detail"]).split("restore with: ", 1)[1]
    argv = shlex.split(printed)
    assert argv[0] == "git"
    into = tmp_path / "restore"
    into.mkdir()
    restore = SubprocessCommands().git(argv[1:], cwd=into)
    assert restore.ok, f"the printed restore command failed:\n{printed}\n{restore.stderr}"

    clone = next(path for path in into.iterdir() if path.is_dir())
    assert only in git(clone, "rev-list", "--all").split()
    assert git(clone, "cat-file", "-p", f"{only}:feat-gone.txt") == "the only copy"


def test_a_server_ref_the_remote_already_dropped_is_never_offered(
    repo: Path, tmp_path: Path
) -> None:
    """What a forge that deletes a branch when its PR merges leaves behind: a
    tracking ref under refs/remotes naming a branch the server no longer has.
    That stale ref is the only thing that ever made this a target, and the
    survey asks the server rather than believing it.

    The ref is dropped *inside the bare repository*, which is what a forge
    tidying up after a merge does and is the only way to reach this state:
    `push --delete` from the clone updates the tracking ref on the way out, so
    the clone would know. Deleting it server-side leaves
    `refs/remotes/origin/feat/vanished` behind untouched, which is the input
    this is about, and the assertion below is there because a setup that
    quietly cleaned the cache would test nothing.

    Real git, because this is also what proves `ls-remote --heads --` is an
    argv git accepts. The terminator is there for option safety -- it stops a
    remote named like a flag being read as one -- and not for the repository
    position, which git will fill from a path whatever precedes it; what keeps
    the probe pointed at a real remote is that the name came from the
    configured remote list. Either way a spelling git rejected would fail every
    probe, and a failed probe reports every server ref as still there, so this
    would pass while measuring nothing."""
    bare = _with_remote(repo, tmp_path)
    _push_only_copy(repo, "feat/vanished")
    git(bare, "update-ref", "-d", "refs/heads/feat/vanished")
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/origin/feat/vanished")

    payload = report(repo, "--cleanup", "origin/feat/vanished")

    assert payload["_exit"] == EXIT_REFUSED
    refusal = refusals(payload)[0]
    assert refusal["code"] == "E_NOT_A_TARGET"
    assert "no longer advertises refs/heads/feat/vanished" in str(refusal["message"])
    assert "fetch --prune origin" in str(refusal["message"])
    assert "remote:origin/feat/vanished" not in [t["id"] for t in payload["targets"]]  # type: ignore[union-attr]
    # Nothing was spent finding that out, and the tracking ref is still here:
    # gitclean does not prune what a fetch created.
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert execution["anomalies"] == []
    assert execution["salvages"] == []
    assert execution["deletions"] == []
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/origin/feat/vanished")


def test_the_salvage_ref_does_not_outlive_the_run(repo: Path, tmp_path: Path) -> None:
    """Bundling needs a ref under refs/heads to bundle, and one left behind
    would surface in the next report as a branch nobody created."""
    bare = _with_remote(repo, tmp_path)
    _push_only_copy(repo, "feat/temp")

    before = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    # The server is what this run deletes from, so the server is what the
    # oracle watches. The commit leaves the bare repository deliberately, and
    # the bundle is the only thing entitled to excuse that -- proven by a real
    # restore, not by the run's own say-so.
    with reachability_guard(bare) as guard:
        payload = report(repo, "--cleanup", "origin/feat/temp")
        salvages = payload["execution"]["salvages"]  # type: ignore[index]
        assert len(salvages) == 1, payload["execution"]
        guard.proven_by_bundle(Path(str(salvages[0]["path"])))

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads") == before


def _shallow_clone(bare: Path, into: Path) -> Path:
    """A depth-1 clone -- what a CI checkout is, and the cheapest repository
    whose history stops at a boundary `git bundle create` will pack right past.

    `--no-single-branch` so the feature ref is fetched too: a clone holding
    only the default branch has nothing to salvage."""
    result = SubprocessCommands().git(
        ["clone", "-q", "--depth", "1", "--no-single-branch", f"file://{bare}", str(into)]
    )
    assert result.ok, result.stderr
    return into


def test_a_bundle_that_will_not_restore_does_not_authorise_the_deletion(
    repo: Path, tmp_path: Path
) -> None:
    """The salvage has to survive being used, not just being inspected.

    `git bundle verify` asks whether the archive applies to *the repository it
    is run in*, which is the one that already holds every object. In a shallow
    clone that question gets a clean yes -- the bundle is reported okay, with a
    complete history -- while `git clone` of the same file dies with `remote
    did not send all necessary objects` and leaves no directory behind. The
    boundary commit's parent is packed by neither: it is grafted away locally
    and absent from the archive.

    So the weaker check passes on a bundle that restores nothing, and it was
    the check standing in front of the one deletion with no undo. Here the
    restore is attempted for real, it fails, and the server keeps its ref."""
    bare = _with_remote(repo, tmp_path)
    only = _push_only_copy(repo, "feat/gone")
    shallow = _shallow_clone(bare, tmp_path / "shallow")

    # No exemption: nothing may leave the server, because nothing can bring it
    # back.
    with reachability_guard(bare):
        payload = report(shallow, "--cleanup", "origin/feat/gone")

    assert payload["_exit"] == EXIT_ANOMALY
    assert "refs/heads/feat/gone" in git(bare, "for-each-ref", "--format=%(refname)")
    assert only in git(bare, "rev-list", "--all").split()

    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert execution["salvages"] == [], "an unrestorable bundle is not a verified salvage"
    assert execution["deletions"][0]["deleted"] is False  # type: ignore[index]

    salvage = next(Path(str(execution["salvage_dir"])).glob("*.bundle"))
    weaker = SubprocessCommands().git(["bundle", "verify", str(salvage)], cwd=shallow)
    assert weaker.ok, "the reproduction needs the check this replaced to still pass"

    anomaly = execution["anomalies"][0]  # type: ignore[index]
    assert anomaly["stage"] == "salvage"
    assert "restore" in anomaly["message"]
    assert any("clone" in line for line in anomaly["transcript"])


def test_an_unrelated_sibling_ref_is_not_read_as_the_deletion_having_failed(
    repo: Path, tmp_path: Path
) -> None:
    """`ls-remote <remote> feat/x` matches path-component tails, so `a/feat/x`
    on the same server answers a question about `feat/x`. The deletion git
    performed then reports as a verification failure, and the run exits
    nonzero over work that went exactly as asked."""
    bare = _with_remote(repo, tmp_path)
    only = _push_only_copy(repo, "feat/x")
    git(repo, "push", "-q", "origin", f"{only}:refs/heads/a/feat/x")

    # No exemption: the sibling ref is what keeps the commit reachable, so the
    # oracle passing here is the assertion that deleting one of two refs to a
    # commit costs nothing.
    with reachability_guard(bare):
        payload = report(repo, "--cleanup", "origin/feat/x")

    assert payload["_exit"] == EXIT_OK, anomaly_lines(payload)
    assert payload["execution"]["deletions"][0]["verified"] is True  # type: ignore[index]
    remaining = git(repo, "ls-remote", "--heads", "origin")
    assert "refs/heads/a/feat/x" in remaining
    assert "\trefs/heads/feat/x" not in remaining


# -- names recovered from framing, not from a delimiter ------------------------


def test_a_remote_whose_name_holds_a_slash_is_never_split_at_the_wrong_one(
    repo: Path, tmp_path: Path
) -> None:
    """`git remote add team/origin <url>` is accepted, so the slash in
    `<remote>/<ref>` is a delimiter the remote's own name is allowed to
    contain. Splitting at the first one yields the remote `team`.

    That is not merely wrong, it is quiet: git takes a *path* wherever it
    expects a remote, so a sibling directory called `team` that happens to be a
    repository answers the pre-delete probe -- successfully, with an empty ref
    list, about a repository nobody named. An empty answer there means the
    branch is already gone, so the run would report a live branch as nothing to
    do and exit clean. The decoy below is that directory, sitting exactly where
    the broken split reaches."""
    bare = tmp_path / "server.git"
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(bare)])
    git(repo, "remote", "add", "team/origin", str(bare))
    git(repo, "push", "-q", "-u", "team/origin", "main")
    git(repo, "checkout", "-q", "-b", "feat/gone")
    only = commit(repo, "feat-gone.txt", "the only copy\n")
    git(repo, "push", "-q", "-u", "team/origin", "feat/gone")
    git(repo, "checkout", "-q", "main")
    git(repo, "fetch", "-q", "team/origin")

    # The trap: a repository at the path `ls-remote team ...` would open,
    # holding nothing, which is what makes its answer look like absence.
    decoy = repo / "team"
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(decoy)])

    surveyed = report(repo)
    branches = surveyed["repo"]
    assert isinstance(branches, dict)
    feat = next(b for b in branches["branches"] if b["name"] == "team/origin/feat/gone")
    assert feat["remote"] == "team/origin"
    assert feat["ref_name"] == "feat/gone"
    # The server's copy of the trunk is recognised as such: recovering the ref
    # name needs the remote's name to end in the right place.
    excluded = {n["name"]: str(n["reason"]) for n in branches["not_offered"]}
    assert "trunk" in excluded["team/origin/main"]

    port = Recording()
    with reachability_guard(bare) as guard:
        out = StringIO()
        code = main(
            ["--cleanup", "team/origin/feat/gone"],
            port=port,
            cwd=repo,
            now=datetime.now(UTC),
            out=out,
        )
        payload = json.loads(out.getvalue())
        guard.proven_by_bundle(Path(str(payload["execution"]["salvages"][0]["path"])))

    assert code == EXIT_OK
    deletion = payload["execution"]["deletions"][0]
    # The wrong answer's signature: `already_absent` on a branch the server
    # holds.
    assert deletion["already_absent"] is False
    assert deletion["deleted"] is True
    assert "feat/gone" not in git(repo, "ls-remote", "--heads", "team/origin")
    assert only not in git(bare, "rev-list", "--all").split()

    # Every remote git was given is the configured name, never its first
    # component -- and the decoy was never opened.
    named = remotes_asked(port.transcript)
    assert named and set(named) == {"team/origin"}
    assert git(decoy, "for-each-ref", "--format=%(refname)") == ""


def test_a_ref_reachable_only_through_a_custom_refspec_belongs_to_who_fetches_it(
    repo: Path, tmp_path: Path
) -> None:
    """A fetch refspec chooses where refs land, and it may choose a path that
    spells another remote's name. `+refs/heads/*:refs/remotes/origin/*` on a
    remote called `upstream` is legal, and puts upstream's branches under
    `refs/remotes/origin/` while nothing called `origin` is involved at all.

    Matching configured names against the path answers `origin` here, which is
    a remote this repository does not have. What the path cannot say, the
    refspec can, so the refspec is what is asked."""
    bare = tmp_path / "upstream.git"
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(bare)])
    git(repo, "remote", "add", "upstream", str(bare))
    git(repo, "config", "remote.upstream.fetch", "+refs/heads/*:refs/remotes/origin/*")
    git(repo, "push", "-q", "upstream", "main")
    git(repo, "checkout", "-q", "-b", "feat/live")
    only = commit(repo, "feat-live.txt", "the only copy\n")
    git(repo, "push", "-q", "upstream", "feat/live")
    git(repo, "checkout", "-q", "main")
    git(repo, "fetch", "-q", "upstream")

    surveyed = report(repo)
    branches = surveyed["repo"]
    assert isinstance(branches, dict)
    feat = next(b for b in branches["branches"] if b["name"] == "origin/feat/live")
    assert feat["remote"] == "upstream"
    assert feat["ref_name"] == "feat/live"

    port = Recording()
    with reachability_guard(bare) as guard:
        out = StringIO()
        code = main(
            ["--cleanup", "remote:origin/feat/live"],
            port=port,
            cwd=repo,
            now=datetime.now(UTC),
            out=out,
        )
        payload = json.loads(out.getvalue())
        guard.proven_by_bundle(Path(str(payload["execution"]["salvages"][0]["path"])))

    assert code == EXIT_OK
    deletion = payload["execution"]["deletions"][0]
    # The wrong answer's signature: `already_absent` on a branch the server
    # holds, settled by asking a remote that never had it.
    assert deletion["already_absent"] is False
    assert deletion["deleted"] is True
    assert "feat/live" not in git(repo, "ls-remote", "--heads", "upstream")
    assert only not in git(bare, "rev-list", "--all").split()

    # Every remote git was handed is the one that fetches the ref, never the
    # one the path happens to spell.
    named = remotes_asked(port.transcript)
    assert named and set(named) == {"upstream"}


def test_two_remotes_fetching_into_one_path_is_refused_rather_than_misattributed(
    repo: Path, tmp_path: Path
) -> None:
    """The configuration that makes attribution unanswerable: `origin` present
    and fetching normally, `upstream` configured to fetch into the same
    namespace, and the branch live only on upstream. Nothing can say which of
    them holds a given ref there.

    The worst available answer is to attribute it to `origin`, find nothing,
    and report a live branch as already gone while prescribing a prune that
    would drop its tracking ref. A refusal costs a round trip; that answer
    costs the ref."""
    origin_bare = tmp_path / "origin.git"
    upstream_bare = tmp_path / "upstream.git"
    for path in (origin_bare, upstream_bare):
        SubprocessCommands().git(["init", "-q", "--bare", "-b", "main", str(path)])
    git(repo, "remote", "add", "origin", str(origin_bare))
    git(repo, "remote", "add", "upstream", str(upstream_bare))
    git(repo, "config", "remote.upstream.fetch", "+refs/heads/*:refs/remotes/origin/*")
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feat/live")
    only = commit(repo, "feat-live.txt", "the only copy\n")
    git(repo, "push", "-q", "upstream", "feat/live")
    git(repo, "checkout", "-q", "main")
    git(repo, "fetch", "-q", "upstream")

    surveyed = report(repo)
    branches = surveyed["repo"]
    assert isinstance(branches, dict)
    assert "origin/feat/live" not in [b["name"] for b in branches["branches"]]
    excluded = {n["name"]: str(n["reason"]) for n in branches["not_offered"]}
    assert "origin, upstream" in excluded["origin/feat/live"]

    out = StringIO()
    code = main(
        ["--cleanup", "origin/feat/live"],
        port=Recording(),
        cwd=repo,
        now=datetime.now(UTC),
        out=out,
    )

    # Loud, and the branch is still there -- not a clean exit reporting a
    # deletion nobody could have performed.
    assert code == EXIT_REFUSED
    assert only in git(upstream_bare, "rev-list", "--all").split()
    assert "feat/live" in git(repo, "ls-remote", "--heads", "upstream")


@pytest.mark.parametrize("remote", ["origin", "team", "team/origin"])
def test_a_trunk_published_by_the_only_remote_is_found_whatever_it_is_called(
    repo: Path, tmp_path: Path, remote: str
) -> None:
    """Asking `refs/remotes/origin/HEAD` and then a local main/master finds no
    tier at all for a trunk published only through a differently-named remote:
    nothing is verified, the ref merges would be measured against does not
    resolve either, and the tool is inert in that repository. The branch below
    is genuinely merged -- the setup insists on it -- and two of these three
    rows would leave it alone.

    The remote's name is the only thing varying, and none of it matters: the
    question is asked of whichever remotes are configured. The slash in
    `team/origin` earns its own row because a remote name may contain one, so a
    path under `refs/remotes/` does not say on its own where the name stops. The
    `origin` row is the control for the ordinary case."""
    bare = tmp_path / "server.git"
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "trunk", str(bare)])
    git(repo, "branch", "-m", "main", "trunk")
    git(repo, "remote", "add", remote, str(bare))
    git(repo, "push", "-q", "-u", remote, "trunk")
    git(repo, "checkout", "-q", "-b", "feat")
    commit(repo, "feat.txt")
    git(repo, "checkout", "-q", "trunk")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat", "feat")
    git(repo, "push", "-q", remote, "trunk")
    git(repo, "fetch", "-q", remote)
    git(repo, "remote", "set-head", remote, "-a")
    # Raises unless feat really is merged: without this the sweep below could be
    # passing on the ordinary no-merge-proof answer rather than on the trunk.
    git(repo, "merge-base", "--is-ancestor", "feat", "trunk")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    repo_block = payload["repo"]
    assert isinstance(repo_block, dict)
    assert repo_block["default_branch_known"] is True
    assert repo_block["default_branch"] == "trunk"
    # And measured against that remote's copy of it, not against a spelling
    # assembled out of a name no repository is obliged to use.
    assert repo_block["base_ref"] == f"refs/remotes/{remote}/trunk"
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert {d["target_id"] for d in execution["deletions"] if d["deleted"]} == {"branch:feat"}
    # The trunk itself is still here: found means protected, not swept.
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/trunk") != ""


def test_remotes_that_disagree_about_the_trunk_stop_the_sweep(repo: Path, tmp_path: Path) -> None:
    """The limit that survives consulting the remote list: two servers, two
    published HEADs, and nothing in the repository saying which one it belongs
    to. Their trunks are allowed to differ, and measuring merges against one
    that is ahead of the real trunk reports unmerged work as merged -- so the
    tier declines rather than picking, and with no local main or master beneath
    it nothing resolves at all. The branch below is genuinely merged into the
    trunk this repository does have, and is still left alone."""
    alpha_bare = tmp_path / "alpha.git"
    beta_bare = tmp_path / "beta.git"
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "trunk", str(alpha_bare)])
    SubprocessCommands().git(["init", "-q", "--bare", "-b", "release", str(beta_bare)])
    git(repo, "branch", "-m", "main", "trunk")
    git(repo, "remote", "add", "alpha", str(alpha_bare))
    git(repo, "remote", "add", "beta", str(beta_bare))
    git(repo, "push", "-q", "-u", "alpha", "trunk")
    git(repo, "checkout", "-q", "-b", "release")
    commit(repo, "release.txt")
    git(repo, "push", "-q", "-u", "beta", "release")
    git(repo, "checkout", "-q", "trunk")
    git(repo, "checkout", "-q", "-b", "feat")
    commit(repo, "feat.txt")
    git(repo, "checkout", "-q", "trunk")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat", "feat")
    git(repo, "push", "-q", "alpha", "trunk")
    for remote in ("alpha", "beta"):
        git(repo, "fetch", "-q", remote)
        git(repo, "remote", "set-head", remote, "-a")
    git(repo, "merge-base", "--is-ancestor", "feat", "trunk")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    repo_block = payload["repo"]
    assert isinstance(repo_block, dict)
    assert repo_block["default_branch_known"] is False
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert {d["target_id"] for d in execution["deletions"] if d["deleted"]} == set()
    assert find(payload, "branch:feat")["sweepable"] is False
    warnings = payload["warnings"]
    assert isinstance(warnings, list)
    # Named, so a reader can go and settle it rather than being told only that
    # something was indeterminate.
    assert any("alpha publishes trunk, beta publishes release" in w for w in warnings)
    for ref in ("refs/heads/trunk", "refs/heads/feat"):
        assert git(repo, "for-each-ref", "--format=%(refname)", ref) != ""


def test_merges_are_not_measured_against_a_local_branch_named_like_the_server_trunk(
    repo: Path, tmp_path: Path
) -> None:
    """Git resolves a bare name through `refs/heads/` before `refs/remotes/`,
    so `origin/main` in an argv reaches a local branch of that name whenever
    one exists -- and one legally can, as `git branch origin/main` here makes.

    Point that decoy at unmerged work and the baseline every tier measures
    against becomes the work itself: it is its own ancestor, `branch --merged`
    lists it, `cherry` finds every patch. A bare sweep then deletes the only
    copy of `feat`, holding a merge proof it manufactured. The full ref path is
    what makes the baseline the ref the survey actually verified."""
    _with_remote(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "feat")
    only = commit(repo, "feat.txt", "the only copy\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "origin/main", "feat")

    # The trap, measured rather than assumed: the short spelling reaches the
    # decoy, and the work really is absent from the server's trunk.
    assert git(repo, "rev-parse", "origin/main") == only
    assert git(repo, "rev-list", "--count", "refs/remotes/origin/main..feat") == "1"

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    surveyed = payload["repo"]
    assert isinstance(surveyed, dict)
    assert surveyed["base_ref"] == "refs/remotes/origin/main"
    feat = find(payload, "branch:feat")
    assert feat["merge_evidence"] == MergeEvidence.NONE.value
    assert feat["sweepable"] is False
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert [d for d in execution["deletions"] if d["deleted"]] == []
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat") != ""


def test_a_local_branch_spelled_like_a_remote_ref_is_a_target_of_its_own(
    repo: Path, tmp_path: Path
) -> None:
    """`origin/main` is a legal local branch, and creating one changes what git
    shortens the *server's* trunk to: `%(refname:short)` gives
    `remotes/origin/main`, because `origin/main` no longer denotes it.

    Reading a remote's name out of that string yields the remote `remotes`, and
    the trunk exclusion -- which compares the remainder against `main` -- stops
    firing for the server's own trunk. The local branch meanwhile has to stay
    what it is: a separate ref, with its own id, that a caller can delete
    without the report telling them it is the trunk."""
    _with_remote(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "origin/main")
    stray = commit(repo, "stray.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "origin/main")
    git(repo, "commit", "-q", "-m", "squashed the stray branch")

    assert git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/origin/main") == (
        "heads/origin/main"
    )

    payload = report(repo)
    surveyed = payload["repo"]
    assert isinstance(surveyed, dict)
    # The server's copy is still recognised as the trunk's, which needs the
    # remote's name to have stopped in the right place.
    excluded = {n["name"]: str(n["reason"]) for n in surveyed["not_offered"]}
    assert "trunk" in excluded["origin/main"]
    # And it is told apart from the local branch by ref, not by the string the
    # two of them share.
    local = next(b for b in surveyed["branches"] if b["ref"] == "refs/heads/origin/main")
    assert local["name"] == "origin/main"
    assert local["is_remote"] is False

    target = find(payload, "branch:origin/main")
    assert "trunk" not in str(target["withheld"] or "")

    with reachability_guard(repo) as guard:
        deleted = report(repo, "--cleanup", "branch:origin/main")
        guard.expect_unreachable(stray)

    assert deleted["_exit"] == EXIT_OK, anomaly_lines(deleted)
    assert deleted["execution"]["deletions"][0]["deleted"] is True  # type: ignore[index]
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/origin/main") == ""
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes/origin/main") != ""


@pytest.mark.parametrize(
    "flags",
    [
        pytest.param((), id="bare"),
        pytest.param(("--dry-run",), id="dry-run"),
        pytest.param(("--format", "human"), id="human-output"),
        pytest.param(("--salvage-dir", "SALVAGE"), id="salvage-dir"),
        pytest.param(
            ("--dry-run", "--format", "human", "--salvage-dir", "SALVAGE"), id="every-flag"
        ),
    ],
)
def test_no_unattended_sweep_reaches_the_server(
    repo: Path, tmp_path: Path, flags: tuple[str, ...]
) -> None:
    """Every flag combination the CLI still accepts, and none of them turns a
    sweep into a server deletion.

    Naming the ref is the whole authorisation for taking it, so the argument
    list is the only thing separating the two. This asserts on what was issued
    rather than on what was reported: a push whose outcome the report folded
    into a count reads the same as one that never happened."""
    bare = _with_remote(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "feat/pushed")
    commit(repo, "pushed.txt")
    git(repo, "push", "-q", "-u", "origin", "feat/pushed")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/pushed", "feat/pushed")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")

    # Not a vacuous pass: the server ref qualifies on evidence, and the only
    # thing between it and the sweep is the rule this test is about. Asserted
    # per row and in JSON, so the rows that render as human text and the rows
    # that issue no commands at all still say what the sweep decided.
    surveyed = find(report(repo), "remote:origin/feat/pushed")
    assert surveyed["merge_proven"] is True
    assert surveyed["sweepable"] is False

    port = Recording()
    resolved = [str(tmp_path / "salvage") if flag == "SALVAGE" else flag for flag in flags]
    with reachability_guard(repo), reachability_guard(bare):
        main(["--cleanup", *resolved], port=port, cwd=repo, now=datetime.now(UTC), out=StringIO())

    pushes = [call for call in port.transcript if call[1] == "push"]
    assert pushes == []
    assert "refs/heads/feat/pushed" in git(repo, "ls-remote", "--heads", "origin")


def test_a_stale_remote_ref_is_refused_rather_than_deleted(repo: Path, tmp_path: Path) -> None:
    """gitclean judges a remote branch from refs/remotes -- a cache. Between
    the last fetch and the delete, somebody else can push. Those commits were
    never surveyed, and without the lease `push --delete` would take them."""
    bare = _with_remote(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "feat/shared")
    commit(repo, "shared.txt")
    git(repo, "push", "-q", "-u", "origin", "feat/shared")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "feat/shared")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")

    # A colleague pushes to the same branch. Our refs/remotes still holds the
    # commit the survey will judge.
    other = tmp_path / "colleague"
    SubprocessCommands().git(["clone", "-q", str(bare), str(other)])
    git(other, "config", "user.email", "them@example.invalid")
    git(other, "config", "user.name", "Them")
    git(other, "checkout", "-q", "feat/shared")
    commit(other, "their-work.txt", "not ours to delete\n")
    git(other, "push", "-q", "origin", "feat/shared")

    # The server is guarded, not the local cache: the commit at risk is the one
    # that only ever existed on origin, and it was never in our object store.
    with reachability_guard(repo), reachability_guard(bare):
        payload = report(repo, "--cleanup", "origin/feat/shared")

    assert payload["_exit"] == EXIT_ANOMALY
    assert "feat/shared" in git(repo, "ls-remote", "--heads", "origin", "feat/shared")
    assert "fetch and re-run" in anomaly_lines(payload)


# -- argv hygiene -------------------------------------------------------------


def test_a_branch_named_like_an_option_is_swept_not_misread(repo: Path) -> None:
    """`git branch` will not create `-m`, but `update-ref` will and a remote
    can push one. Without an argv terminator on the delete, git reads the name
    as a switch and the sweep fails with a usage error.

    The automatic sweep is the path that matters: nobody types the name, so
    nothing shields git from it but the argument list. The whole cycle is
    exercised -- surveyed, reported, then deleted -- because a name git misread
    two stages earlier reaches the delete as a branch that was never there."""
    git(repo, "checkout", "-q", "-b", "feat/opt")
    head = commit(repo, "opt.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/opt", "feat/opt")
    git(repo, "branch", "-D", "feat/opt")
    git(repo, "update-ref", "refs/heads/-m", head)

    with reachability_guard(repo):
        surveyed = report(repo, "--report")
        payload = report(repo, "--cleanup")

    listed = find(surveyed, "branch:-m")
    assert listed["name"] == "-m"
    assert listed["merge_proven"] is True
    assert listed["sweepable"] is True

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/-m") == ""
    assert "-m" in [d["name"] for d in payload["execution"]["deletions"]]  # type: ignore[index]


def test_a_squash_merged_branch_named_like_an_option_is_proven(repo: Path) -> None:
    """The one case the test above does not cover: an ancestor or patch-id
    merge never reaches the squash tier at all, and that tier's own `git`
    calls are their own chance to lose the argv terminator that protects every
    other probe here. Two commits are used deliberately, as in
    `test_a_real_squash_merge_is_detected` -- with one, patch-id equivalence
    would settle it before the squash tier ran, and this would prove nothing
    about its argv."""
    git(repo, "checkout", "-q", "-b", "feat/opt-squash")
    first = commit(repo, "one.txt")
    second = commit(repo, "two.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/opt-squash")
    git(repo, "commit", "-q", "-m", "squashed feat/opt-squash")
    head = git(repo, "rev-parse", "refs/heads/feat/opt-squash")
    git(repo, "branch", "-D", "feat/opt-squash")
    git(repo, "update-ref", "refs/heads/-m", head)

    assert "-m" not in git(repo, "branch", "--merged", "main")

    with reachability_guard(repo) as guard:
        surveyed = report(repo, "--report")
        payload = report(repo, "--cleanup")
        # A squash rewrites the work into one new commit on main, so these two
        # are stranded by design -- that is what the sweep exists to remove.
        guard.expect_unreachable(first, second)

    branches = surveyed["repo"]
    assert isinstance(branches, dict)
    dashed = next(b for b in branches["branches"] if b["name"] == "-m")
    assert dashed["merge_evidence"] == "squash_equal"

    listed = find(surveyed, "branch:-m")
    assert listed["name"] == "-m"
    assert listed["merge_proven"] is True
    assert listed["sweepable"] is True

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/-m") == ""
    assert "-m" in [d["name"] for d in payload["execution"]["deletions"]]  # type: ignore[index]


def test_a_name_nothing_matches_is_clean_and_does_not_stop_the_rest(repo: Path) -> None:
    """Both halves matter. Exit 0 because the state the caller asked for holds,
    and `feat/done` actually gone because the absent name did not take the
    command down with it -- a selector refusal was plan-level, so one name
    already dealt with aborted every deletion beside it."""
    _merged_branch_beside(repo, "feat/done")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", "feat/done", "feat/never-existed")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/done") == ""
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert [a["selector"] for a in plan["absent"]] == ["feat/never-existed"]


def test_the_post_merge_sequence_an_agent_performs_cleans_up(repo: Path, tmp_path: Path) -> None:
    """The scenario this behaviour exists for, end to end.

    Leaving the worktree before cleaning it is the *correct* order -- git will
    not delete a branch a worktree still holds, and whatever owns that tree
    usually removes it on the way out. Doing it right is what made the worktree
    name match nothing, and the refusal that produced was plan-level: the
    branch survived, and the run said it failed."""
    work = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feat/shipped", str(work))
    commit(work, "shipped.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/shipped", "feat/shipped")
    git(repo, "worktree", "remove", str(work))

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", f"worktree:{work}", "feat/shipped")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/shipped") == ""
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert [a["selector"] for a in plan["absent"]] == [f"worktree:{work}"]


def test_a_branch_named_like_an_option_is_selectable_by_id(repo: Path) -> None:
    """Naming it directly cannot go through the bare name -- argparse claims
    `-m` as a flag before gitclean sees it. The `id` form is the way in, which
    is what a name matching nothing points the reader back to."""
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/heads/-m", head)

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", "branch:-m")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/-m") == ""


# -- what a sweep declines to take --------------------------------------------


def test_an_unmerged_branch_is_reported_but_never_swept(repo: Path) -> None:
    """Nothing here computes whether anyone still wants it. The report carries
    what was measured and the person reading it names what they want gone."""
    git(repo, "checkout", "-q", "-b", "feat/forgotten")
    commit(repo, "forgotten.txt")
    git(repo, "checkout", "-q", "main")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup")

    target = find(payload, "branch:feat/forgotten")
    assert target["sweepable"] is False
    assert "no merge proof" in str(target["withheld"])
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/forgotten") != ""


# -- the reachability matrix --------------------------------------------------


@dataclass(frozen=True)
class Topology:
    """A repository shape, the sweep to run over it, and what that sweep costs.

    ``deletes`` is what stops a case passing vacuously: a run that swept
    nothing would satisfy any reachability assertion. ``discards`` is the
    commits the deletion is allowed to strand, and it is empty everywhere
    except the shapes that rewrote the work under new hashes -- everywhere else
    a stranded commit is work lost.

    The rest describe shapes the first six rows had no way to say:

    - ``survives`` names refs that must still resolve afterwards. A row whose
      point is what the sweep declined to take proves nothing through
      ``deletes`` alone, and one that takes nothing at all would otherwise
      assert nothing whatever.
    - ``also_guard`` is the other repositories this run can reach. A server is
      a separate object store, and a ref deleted there is still held by this
      one's tracking cache -- so the local oracle would watch the deletion and
      report no loss.
    - ``run_from`` is the directory the CLI runs in. It decides which worktree
      answers the invoking-worktree question, which decides whether the main
      checkout is a candidate at all.
    - ``exit_code`` is what the run is expected to report. A shape where git
      refuses part of the plan is not a failure of the sweep -- the refusal is
      the safety story -- but it is an anomaly, and the row says so rather than
      the matrix assuming every sweep ends clean.
    """

    selectors: tuple[str, ...]
    deletes: frozenset[str]
    discards: tuple[str, ...] = ()
    survives: tuple[str, ...] = ()
    also_guard: tuple[Path, ...] = ()
    run_from: Path | None = None
    exit_code: int = EXIT_OK


def _squash_merged(repo: Path) -> Topology:
    """The one shape where discarding commits is the point: the work is on
    main under new hashes, and the originals are what the sweep is for."""
    git(repo, "checkout", "-q", "-b", "feat/squash")
    first = commit(repo, "s-one.txt")
    second = commit(repo, "s-two.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/squash")
    git(repo, "commit", "-q", "-m", "squashed feat/squash")
    return Topology((), frozenset({"feat/squash"}), (first, second))


def _truly_merged(repo: Path) -> Topology:
    """A merge commit keeps the branch's commits as parents, so deleting the
    ref costs nothing at all."""
    git(repo, "checkout", "-q", "-b", "feat/merged")
    commit(repo, "m-one.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/merged", "feat/merged")
    return Topology((), frozenset({"feat/merged"}))


def _unmerged_with_remote(repo: Path) -> Topology:
    """Unmerged, but pushed: the remote-tracking ref holds the commits after
    the local branch goes. Selected by id -- the bare name is ambiguous once
    origin carries a branch of the same name, and an unmerged branch is never
    swept unattended, so naming it is the only way in."""
    _with_remote(repo, repo.parent)
    git(repo, "checkout", "-q", "-b", "feat/pushed")
    commit(repo, "p-one.txt")
    git(repo, "push", "-q", "-u", "origin", "feat/pushed")
    git(repo, "checkout", "-q", "main")
    return Topology(("branch:feat/pushed",), frozenset({"feat/pushed"}))


def _merged_branch_beside(repo: Path, name: str, trunk: str = "main") -> None:
    """Something the sweep is entitled to take, so a case about what it leaves
    alone cannot pass by sweeping nothing at all.

    ``trunk`` is a parameter because a repository's trunk is not always called
    main, and the row that says so still needs something merged into it."""
    git(repo, "checkout", "-q", "-b", name)
    commit(repo, f"{name.replace('/', '-')}.txt")
    git(repo, "checkout", "-q", trunk)
    git(repo, "merge", "-q", "--no-ff", "-m", f"merge {name}", name)


def _detached_orphan_worktree(repo: Path) -> Topology:
    """A clean worktree whose commit is on no branch.

    A clean working tree says the files are committed. It says nothing about
    where that commit lives, and reading it as "this checkout holds no content"
    is what let a bare sweep strand an orphan commit with no salvage behind it.
    The commit is what gets asked about now, and no ref proves this one merged.
    """
    _merged_branch_beside(repo, "feat/beside-orphan")
    path = repo.parent / "wt-orphan"
    git(repo, "worktree", "add", "-q", "--detach", str(path))
    commit(path, "orphan.txt", "the only copy\n")
    return Topology((), frozenset({"feat/beside-orphan"}))


def _moved_aside_orphan_worktree(repo: Path) -> Topology:
    """The same commit, in a worktree whose directory has been moved rather
    than deleted -- an unmounted volume, or a tree set aside for an hour. git
    calls that prunable, and the tree and its commit are both still there."""
    _merged_branch_beside(repo, "feat/beside-moved")
    path = repo.parent / "wt-moved"
    git(repo, "worktree", "add", "-q", "--detach", str(path))
    commit(path, "orphan.txt", "the only copy\n")
    path.rename(repo.parent / "wt-moved-elsewhere")
    return Topology((), frozenset({"feat/beside-moved"}))


def _moved_aside_merged_worktree(repo: Path) -> Topology:
    """A moved-aside worktree whose commit *is* merged, holding an afternoon of
    uncommitted work.

    Nothing here is unreachable, so the guard has nothing to say: the loss this
    shape risks is a directory of files, not a commit. It is the case that
    isolates the working-tree question, because every other one is settled --
    and it is the case where reading `prunable` as "the directory is gone"
    asserts an empty tree on no measurement at all."""
    _merged_branch_beside(repo, "feat/beside-held")
    path = repo.parent / "wt-held"
    git(repo, "worktree", "add", "-q", str(path), "-b", "feat/held")
    commit(path, "held.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/held", "feat/held")
    (path / "afternoon.txt").write_text(
        "uncommitted, and not where git can look\n", encoding="utf-8"
    )
    path.rename(repo.parent / "wt-held-elsewhere")
    return Topology((), frozenset({"feat/beside-held"}))


def _patch_equal_branch(repo: Path) -> Topology:
    """Cherry-picked onto a trunk that had moved on -- the tier between plain
    ancestry and the squash probe, and the one no row reached.

    The commit on main is a copy under a different hash, so the originals go
    the way squashed ones do. Main needs a commit of its own first: replayed
    onto the same parent with the same tree, the copies would be the same
    objects, ancestry would settle it, and the shape would collapse into a
    row that already exists."""
    git(repo, "checkout", "-q", "-b", "feat/picked")
    first = commit(repo, "c-one.txt")
    second = commit(repo, "c-two.txt")
    git(repo, "checkout", "-q", "main")
    commit(repo, "meanwhile.txt")
    git(repo, "cherry-pick", first, second)
    return Topology((), frozenset({"feat/picked"}), (first, second))


def _branch_whose_work_was_backed_out(repo: Path) -> Topology:
    """Work added on a branch and taken off again on the same branch, while
    base acquired an empty commit.

    Nothing about this branch was ever merged: base has never held the file,
    and the two commits are the only copy of it. The tree at the tip is the
    merge base's tree though, so the squash probe synthesises a commit with an
    empty diff -- and an empty diff has the same patch id as every other empty
    diff, so `git cherry` finds it "already in base" the moment base carries an
    empty commit of its own. Without that commit on base the same branch is
    reported unproven and left alone, which is what says the evidence is about
    the empty commit rather than about this branch.

    An empty commit on the trunk is what a build retrigger leaves behind, so
    the run this shape describes is an ordinary one."""
    git(repo, "checkout", "-q", "-b", "feat/backed-out")
    commit(repo, "secret.txt", "the only copy of an afternoon\n")
    git(repo, "rm", "-q", "--", "secret.txt")
    git(repo, "commit", "-q", "-m", "back it out for now")
    git(repo, "checkout", "-q", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "chore: retrigger the build")
    return Topology((), frozenset(), survives=("refs/heads/feat/backed-out",))


def _clean_merged_worktree(repo: Path) -> Topology:
    """A finished worktree and the branch it holds, both provably merged, the
    tree holding nothing that is not committed.

    This is what the sweep is for, and every other worktree row is about a
    removal being declined -- so without it the matrix never watches a worktree
    actually come out, and a run that stranded something on the way would have
    no row to fail."""
    path = _worktree(repo, "wt-finished", "feat/finished")
    commit(path, "finished.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/finished", "feat/finished")
    return Topology((), frozenset({str(path), "feat/finished"}))


def _detached_worktree_at_a_merged_tip(repo: Path) -> Topology:
    """The control for the orphan rows: the same detached checkout, this time
    at a commit a merged branch names. Nothing is at risk, so a run that
    declined this one would be refusing the ordinary case the reachability
    check exists to permit."""
    _merged_branch_beside(repo, "feat/tip")
    path = repo.parent / "wt-detached"
    git(repo, "worktree", "add", "-q", "--detach", str(path), "feat/tip")
    return Topology((), frozenset({str(path), "feat/tip"}))


def _worktree_holding_an_edited_file(repo: Path) -> Topology:
    """Merged, so the commit question is settled, and a *tracked* file has been
    edited since -- the half of dirt the untracked case does not cover.

    The edit is in no commit, no reflog and no remote, so the tree stands. Its
    branch cannot go either while a worktree holds it, which is the one shape
    here where a bare sweep finishes clean having deliberately left something
    behind."""
    _merged_branch_beside(repo, "feat/beside-edited")
    path = _worktree(repo, "wt-edited", "feat/edited")
    commit(path, "edited.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/edited", "feat/edited")
    (path / "README.md").write_text("edited, never committed\n", encoding="utf-8")
    return Topology((), frozenset({"feat/beside-edited"}), survives=("refs/heads/feat/edited",))


def _worktree_holding_a_stash(repo: Path) -> Topology:
    """A merged worktree whose only uncommitted work has been stashed.

    `git status` calls that tree clean -- a stash is not a working-tree change
    -- so the dirt question waves it through and the tree comes out. What keeps
    that from costing anything is that the stash belongs to the repository
    rather than to the worktree: its ref outlives the removal, and so do the
    commits under it. The row is here because "the tree looks empty" is the
    reading that stranded an orphan commit once already."""
    path = _worktree(repo, "wt-stashed", "feat/stashed")
    commit(path, "stashed.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/stashed", "feat/stashed")
    (path / "stashed.txt").write_text("an afternoon, set aside\n", encoding="utf-8")
    git(path, "stash", "push", "-q", "-m", "set aside")
    return Topology((), frozenset({str(path), "feat/stashed"}))


def _locked_merged_worktree(repo: Path) -> Topology:
    """A locked worktree, on a merged branch, with a clean tree.

    Every one of the six questions waves it through -- a lock is recorded as a
    reason and is not dirt -- so git's own refusal is the whole of what is
    left, and it holds: the tree stands, the branch it occupies stands with it,
    and the run reports an anomaly rather than a success line. Nothing is lost,
    and the row exists to say that the report is what carries the news."""
    _merged_branch_beside(repo, "feat/beside-locked")
    path = _worktree(repo, "wt-locked", "feat/locked")
    commit(path, "locked.txt")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge feat/locked", "feat/locked")
    git(repo, "worktree", "lock", str(path))
    return Topology(
        (),
        frozenset({"feat/beside-locked"}),
        survives=("refs/heads/feat/locked",),
        exit_code=EXIT_ANOMALY,
    )


def _branch_parked_on_the_trunk_tip(repo: Path) -> Topology:
    """A branch cut from the trunk and never committed to.

    Ancestry proves it merged -- there is nothing on it to be unmerged -- and
    its name is not the trunk's, so matching the trunk by commit is the only
    thing holding it back. Deleting it would cost nothing this repository can
    measure, which is exactly why nothing but that rule refuses."""
    _merged_branch_beside(repo, "feat/beside-parked")
    git(repo, "branch", "feat/parked")
    return Topology((), frozenset({"feat/beside-parked"}), survives=("refs/heads/feat/parked",))


def _trunk_named_master(repo: Path) -> Topology:
    """No remote, and a trunk called master rather than main -- the resolution
    tier that answers when nothing is published. If it stopped answering, the
    trunk would read as an ordinary merged branch and a bare sweep would take
    the repository's whole history with it."""
    git(repo, "branch", "-m", "main", "master")
    _merged_branch_beside(repo, "feat/on-master", trunk="master")
    return Topology((), frozenset({"feat/on-master"}), survives=("refs/heads/master",))


def _trunk_across_the_remote_boundary(repo: Path) -> Topology:
    """A squash-merged branch that was also pushed, in a repository whose trunk
    origin publishes.

    Three claims at once: the local branch is taken, the server's copy of it is
    not, and neither `main` nor `origin/main` is mistaken for cruft. The squash
    is what makes the server worth guarding in its own right -- its
    refs/heads/feat holds the only copy of those commits, this repository's
    tracking ref answers for them locally, and a local oracle would therefore
    watch that ref be deleted and report nothing lost."""
    bare = _with_remote(repo, repo.parent)
    git(repo, "remote", "set-head", "origin", "-a")
    git(repo, "checkout", "-q", "-b", "feat/pushed")
    commit(repo, "r-one.txt")
    commit(repo, "r-two.txt")
    git(repo, "push", "-q", "-u", "origin", "feat/pushed")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/pushed")
    git(repo, "commit", "-q", "-m", "squashed feat/pushed")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    return Topology(
        (),
        frozenset({"feat/pushed"}),
        survives=("refs/heads/main", "refs/remotes/origin/feat/pushed"),
        also_guard=(bare,),
    )


def _no_resolvable_default_branch(repo: Path) -> Topology:
    """A trunk called neither main nor master, with no remote publishing one.

    Nothing here can be told apart from the trunk, so nothing is swept -- and
    the branch that is genuinely merged into it stays too, which is what makes
    this a measurement rather than an empty run. The reason a reader sees on
    each row is the first question's, not the trunk one's: every probe is
    measured against a ref that does not resolve, so nothing gets as far as
    being proven merged."""
    _merged_branch_beside(repo, "dev")
    git(repo, "branch", "-m", "main", "trunk")
    return Topology((), frozenset(), survives=("refs/heads/trunk", "refs/heads/dev"))


def _unmerged_worktree(repo: Path) -> Topology:
    """The ordinary working worktree: clean, on a branch carrying commits of
    its own. A clean tree says the files are committed and nothing more, so the
    first question stops the tree and its branch together -- the shape a sweep
    meets most often, and the one it must never take."""
    _merged_branch_beside(repo, "feat/beside-live")
    path = _worktree(repo, "wt-live", "feat/live")
    commit(path, "live.txt")
    return Topology((), frozenset({"feat/beside-live"}), survives=("refs/heads/feat/live",))


def _main_worktree_seen_from_a_linked_one(repo: Path) -> Topology:
    """The run executing somewhere other than the main checkout, which is how a
    worktree-per-task workflow uses it.

    The invoking-worktree question then answers for the linked tree, and the
    main checkout -- parked on a branch that is merged, with a clean tree --
    clears all six. git refuses to remove a main working tree, and that refusal
    is the whole of what stands between a bare sweep and the directory the
    repository lives in."""
    _merged_branch_beside(repo, "feat/beside-main")
    _merged_branch_beside(repo, "feat/parked-main")
    git(repo, "checkout", "-q", "feat/parked-main")
    path = _worktree(repo, "wt-running", "feat/running")
    commit(path, "running.txt")
    return Topology(
        (),
        frozenset({"feat/beside-main"}),
        survives=("refs/heads/feat/parked-main",),
        run_from=path,
        exit_code=EXIT_ANOMALY,
    )


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(_squash_merged, id="squash-merged-branch"),
        pytest.param(_truly_merged, id="truly-merged-branch"),
        pytest.param(_patch_equal_branch, id="cherry-picked-branch"),
        pytest.param(
            _branch_whose_work_was_backed_out,
            id="branch-whose-work-was-backed-out-on-itself",
        ),
        pytest.param(_unmerged_with_remote, id="unmerged-branch-with-remote-copy"),
        pytest.param(_detached_orphan_worktree, id="detached-worktree-holding-an-orphan-commit"),
        pytest.param(_moved_aside_orphan_worktree, id="moved-aside-detached-worktree"),
        pytest.param(_moved_aside_merged_worktree, id="moved-aside-worktree-on-a-merged-branch"),
        pytest.param(_clean_merged_worktree, id="clean-worktree-on-a-merged-branch"),
        pytest.param(_detached_worktree_at_a_merged_tip, id="detached-worktree-at-a-merged-tip"),
        pytest.param(_worktree_holding_an_edited_file, id="worktree-holding-an-edited-file"),
        pytest.param(_worktree_holding_a_stash, id="worktree-holding-a-stash"),
        pytest.param(_locked_merged_worktree, id="locked-worktree-on-a-merged-branch"),
        pytest.param(_unmerged_worktree, id="clean-worktree-on-an-unmerged-branch"),
        pytest.param(_branch_parked_on_the_trunk_tip, id="branch-parked-on-the-trunk-tip"),
        pytest.param(_trunk_named_master, id="trunk-named-master"),
        pytest.param(_trunk_across_the_remote_boundary, id="trunk-across-the-remote-boundary"),
        pytest.param(_no_resolvable_default_branch, id="no-resolvable-default-branch"),
        pytest.param(_main_worktree_seen_from_a_linked_one, id="main-worktree-from-a-linked-one"),
    ],
)
def test_a_sweep_strands_only_the_commits_it_proved_redundant(
    repo: Path, build: Callable[[Path], Topology]
) -> None:
    """The matrix the oracle exists for.

    Each row is a topology a reviewer had to imagine before anyone could write
    a test about it. The guard needs nobody to imagine the consequence: it
    reads the commit graph before and after and says what the run cost.

    Every row drives a bare sweep but one, and that one is named in its own
    builder: a sweep is the run with no per-target authorisation behind it, so
    it is where the shapes nobody enumerated do their damage."""
    topology = build(repo)

    with ExitStack() as guards:
        guard = guards.enter_context(reachability_guard(repo))
        for elsewhere in topology.also_guard:
            guards.enter_context(reachability_guard(elsewhere))
        payload = report(topology.run_from or repo, "--cleanup", *topology.selectors)
        guard.expect_unreachable(*topology.discards)

    assert payload["_exit"] == topology.exit_code, anomaly_lines(payload)
    deletions = payload["execution"]["deletions"]  # type: ignore[index]
    assert {d["name"] for d in deletions if d["deleted"]} == topology.deletes
    for ref in topology.survives:
        assert git(repo, "for-each-ref", "--format=%(refname)", ref) == ref


# -- the port itself ----------------------------------------------------------


def test_the_port_reports_a_real_failure_with_its_transcript(repo: Path) -> None:
    """Anomalies are only useful if the transcript is git's own words."""
    result: CommandResult = SubprocessCommands().git(["cat-file", "-e", "does-not-exist"], cwd=repo)

    assert not result.ok
    assert "$ git cat-file -e does-not-exist" in result.transcript()[0]


class WithPullRequest(Recording):
    """The real port, git untouched, answering for exactly one pull request.

    A tmp repository has no forge behind it, so the authorising fact has to come
    from somewhere -- and the thing under test is what gitclean does with that
    fact against a real repository, not whether it can parse gh. Everything git
    is asked still goes to git."""

    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__()
        self._payload = payload

    def has_gh(self) -> bool:
        return True

    def gh(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,  # noqa: ARG002 - the port's signature; gh needs no cwd here
    ) -> CommandResult:
        # The bulk index answers empty on purpose. Merge evidence then comes
        # from git alone, so what these tests exercise is the mode acting on
        # the pull request it was handed rather than on a PR-state tier that
        # happened to agree with it.
        if list(args[:2]) == ["pr", "list"]:
            body = "[]"
        elif list(args[:2]) == ["pr", "view"]:
            body = json.dumps(self._payload)
        else:  # pragma: no cover - a call no test intends
            raise AssertionError(f"unexpected gh call: {args}")
        return CommandResult(argv=("gh", *args), returncode=0, stdout=body, stderr="")


def _merge_a_branch(repo: Path, name: str) -> str:
    """A branch carrying one commit that is now an ancestor of the trunk.

    A bare `git branch` off the tip is NOT this: gitclean withholds a branch
    sitting exactly on the trunk, because nothing on disk distinguishes that
    from the trunk itself, and a fixture built that way tests the withhold
    rather than the sweep."""
    git(repo, "checkout", "-q", "-b", name)
    head = commit(repo, f"{name}.txt", f"work on {name}\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", f"merge {name}", name)
    return head


def _merged_payload(head_ref: str, number: int = 438) -> dict[str, object]:
    return {
        "number": number,
        "state": "MERGED",
        "headRefName": head_ref,
        "mergedAt": "2026-08-01T09:30:00Z",
    }


def test_after_merge_removes_the_worktree_and_branch_one_pull_request_produced(
    repo: Path, tmp_path: Path
) -> None:
    """The whole point of the mode, against a real repository: an agent that
    merged its own pull request reaches the end state in one call, having named
    nothing, and every other branch is still there afterwards."""
    _merge_a_branch(repo, "shipped")
    wt = tmp_path / "wt-shipped"
    git(repo, "worktree", "add", "-q", str(wt), "shipped")
    git(repo, "branch", "someone-elses-work")

    port = WithPullRequest(_merged_payload("shipped"))
    with reachability_guard(repo):
        payload = report(repo, "--after-merge", "438", port=port)

    assert payload["_exit"] == EXIT_OK
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert {d["name"] for d in execution["deletions"]} == {str(wt), "shipped"}
    assert all(d["deleted"] and d["verified"] for d in execution["deletions"])

    remaining = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    assert "shipped" not in remaining.split()
    assert "someone-elses-work" in remaining.split()
    assert not wt.exists()


def test_after_merge_never_deletes_the_worktree_the_run_is_standing_in(
    repo: Path, tmp_path: Path
) -> None:
    """The likeliest way to invoke this mode is from inside the worktree it is
    about -- an agent merges its own pull request and cleans up where it stands.
    Removing that directory pulls the working directory out from under the
    process, so the sweep withholds it, and the branch it holds is withheld
    beside it because git would refuse that too. Nothing is deleted and both
    reasons are reported."""
    _merge_a_branch(repo, "shipped")
    wt = tmp_path / "wt-shipped"
    git(repo, "worktree", "add", "-q", str(wt), "shipped")

    port = WithPullRequest(_merged_payload("shipped"))
    with reachability_guard(repo):
        # cwd is the worktree itself, which is what makes it the invoking one.
        payload = report(wt, "--after-merge", "438", port=port)

    assert payload["_exit"] == EXIT_OK
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert execution["deletions"] == []
    plan = payload["plan"]
    assert isinstance(plan, dict)
    reasons = {s["target_id"]: str(s["reason"]) for s in plan["skipped"]}
    assert set(reasons) == {f"worktree:{wt}", "branch:shipped"}
    # Each withheld for its own measured reason, not incidentally.
    assert "the run is executing in" in reasons[f"worktree:{wt}"]
    assert str(wt) in reasons["branch:shipped"]
    assert wt.exists()
    assert "shipped" in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()


def test_after_merge_leaves_a_branch_carrying_work_the_pull_request_did_not_merge(
    repo: Path,
) -> None:
    """A merged pull request describes the commit its head pointed at, not
    whatever the branch of that name holds now. Someone pushing one more commit
    after the merge is ordinary, and that commit exists nowhere else."""
    git(repo, "checkout", "-q", "-b", "shipped")
    commit(repo, "shipped.txt", "merged work\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "shipped")
    git(repo, "checkout", "-q", "shipped")
    stranded = commit(repo, "after.txt", "landed after the merge\n")
    git(repo, "checkout", "-q", "main")

    port = WithPullRequest(_merged_payload("shipped"))
    with reachability_guard(repo):
        payload = report(repo, "--after-merge", "438", port=port)

    assert payload["_exit"] == EXIT_OK
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert execution["deletions"] == []
    assert stranded in git(repo, "rev-list", "--all").split()
    assert "shipped" in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()


def test_a_pull_request_that_closed_unmerged_deletes_nothing_in_a_real_repository(
    repo: Path,
) -> None:
    """The refusal that protects the only copy of abandoned work."""
    git(repo, "checkout", "-q", "-b", "abandoned")
    only = commit(repo, "abandoned.txt", "the only copy\n")
    git(repo, "checkout", "-q", "main")

    payload = {
        "number": 438,
        "state": "CLOSED",
        "headRefName": "abandoned",
        "mergedAt": None,
    }
    with reachability_guard(repo):
        envelope = report(repo, "--after-merge", "438", port=WithPullRequest(payload))

    assert envelope["_exit"] == EXIT_REFUSED
    refusal = envelope["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_PR_NOT_MERGED"
    assert only in git(repo, "rev-list", "--all").split()
