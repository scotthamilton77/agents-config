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
    SubprocessCommands().git(["init", "-q", "--bare", str(bare)])
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


def test_naming_the_branch_you_are_standing_on_does_not_delete_it(repo: Path) -> None:
    """Naming a target is an authorisation, so nothing here re-derives whether
    it is wise. What stops this is that git will not delete a branch a worktree
    holds -- and saying so up front names the worktree that has to go first."""
    git(repo, "checkout", "-q", "-b", "feat/parked")
    commit(repo, "parked.txt")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", "feat/parked")

    assert payload["_exit"] == EXIT_REFUSED
    refusal = payload["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_BRANCH_IN_USE"
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


def test_naming_a_detached_worktree_will_not_strand_the_commit_it_holds(repo: Path) -> None:
    """The gap in "git's own refusals are enough".

    They cover uncommitted content. They say nothing about a commit made
    inside the worktree on no branch: that tree is clean, git removes it
    without complaint, and the record it deletes is the only thing that held
    HEAD -- the per-worktree reflog goes with it. No ref, no reflog, no undo.

    Naming a target is an authorisation to delete a checkout, and it was
    silently spending a commit. The run declines and says which commit and
    how to keep it, which is the difference between authorising and being
    told afterwards."""
    work = repo.parent / "wt-orphan"
    git(repo, "worktree", "add", "-q", "--detach", str(work))
    only = commit(work, "only.txt", "the only copy\n")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", f"worktree:{work}")

    assert payload["_exit"] == EXIT_ANOMALY
    assert work.exists()
    assert git(repo, "for-each-ref", "--count=1", f"--contains={only}") == ""
    said = str(payload["execution"]["anomalies"])  # type: ignore[index]
    assert only[:8] in said and "git branch" in said


def test_naming_a_worktree_whose_commit_a_branch_holds_still_removes_it(repo: Path) -> None:
    """The refusal is about reachability, not about being detached. A commit
    some branch contains survives the removal, so the removal proceeds --
    otherwise the check would block the ordinary case it exists to permit."""
    work = _worktree(repo, "wt-kept", "feat/kept")
    commit(work, "kept.txt")

    with reachability_guard(repo):
        payload = report(repo, "--cleanup", f"worktree:{work}")

    assert payload["_exit"] == EXIT_OK
    assert not work.exists()


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
    refusal = named["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_INVOKING_WORKTREE"
    assert str(work) in str(refusal["message"])


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


def test_a_branch_named_like_an_option_is_selectable_by_id(repo: Path) -> None:
    """Naming it directly cannot go through the bare name -- argparse claims
    `-m` as a flag before gitclean sees it. The `id` form is the way in, which
    is what the unknown-target refusal already tells the reader to use."""
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
    shape used to cause is a directory of files, not a commit. It is the case
    that isolates the working-tree question, because every other one is settled
    -- and it is the case where `prunable` was read as "the directory is gone"
    and the tree asserted empty on no measurement at all."""
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
            marks=pytest.mark.xfail(
                strict=True,
                reason="a branch whose tip tree is its merge base's tree makes the squash "
                "probe synthesise a commit with an empty diff, and an empty diff shares its "
                "patch id with every other empty diff -- so any empty commit base picked up "
                "after the fork reads as proof, and a bare sweep deletes the only copy of "
                "the work the branch backed out",
            ),
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
