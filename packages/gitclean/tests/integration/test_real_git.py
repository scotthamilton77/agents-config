"""gitclean against real git, in throwaway repositories.

Everything above ``ports.py`` is tested against ``ScriptedCommands``, which
pins the code to the author's beliefs about git's output. That is the right
trade for classification rules, and the wrong one for the claims this tool
makes about git itself -- most of all the squash-merge detector, the entire
reason the package exists, which those tests only ever showed a transcript
somebody wrote by hand.

So these build actual repositories and run the actual CLI over them. They are
hermetic: every repo lives in a tmp directory, and ``has_gh`` is forced off so
nothing reaches the network. PR-state evidence is not exercised here -- it has
no git-side behaviour to get wrong, and the unit suite covers it.
"""

from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest

from gitclean.cli import EXIT_ANOMALY, EXIT_OK, EXIT_REFUSED, main
from gitclean.execute import Executor
from gitclean.model import Disposition, Plan, Risk, Target, TargetKind
from gitclean.ports import CommandResult, SubprocessCommands
from gitclean.survey import parse_timestamp
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


def report(repo: Path, *args: str, now: datetime | None = None) -> dict[str, object]:
    """Run the CLI in-process and return the parsed envelope."""
    out = StringIO()
    code = main(
        list(args) or ["--report"],
        port=GitOnly(),
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

    payload = report(repo)
    branches = payload["repo"]
    assert isinstance(branches, dict)
    feat = next(b for b in branches["branches"] if b["name"] == "feat/squashed")

    assert feat["merge_evidence"] == "squash_equal"
    assert feat["merged"] is True
    assert find(payload, "branch:feat/squashed")["disposition"] == Disposition.SAFE.value


def test_a_genuinely_unmerged_branch_is_not_swept(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feat/live")
    commit(repo, "unique.txt")
    git(repo, "checkout", "-q", "main")

    payload = report(repo)
    target = find(payload, "branch:feat/live")

    assert target["disposition"] != Disposition.SAFE.value
    assert payload["summary"]["sweepable_now"] == 0  # type: ignore[index]


def test_a_squash_merged_branch_is_actually_deleted(repo: Path) -> None:
    """End to end: prove it, plan it, delete it, and re-ask git."""
    git(repo, "checkout", "-q", "-b", "feat/done")
    commit(repo, "a.txt")
    commit(repo, "b.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/done")
    git(repo, "commit", "-q", "-m", "squashed")

    payload = report(repo, "--cleanup")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/done") == ""
    deletions = payload["execution"]["deletions"]  # type: ignore[index]
    assert [d["name"] for d in deletions] == ["feat/done"]
    assert deletions[0]["verified"] is True


# -- protection ---------------------------------------------------------------


def test_the_default_branch_and_the_current_checkout_are_refused_by_name(repo: Path) -> None:
    """The trunk and the branch you are standing on are not deletable, and
    --force does not buy them: naming them is refused and both survive."""
    git(repo, "checkout", "-q", "-b", "feat/parked")
    commit(repo, "parked.txt")

    payload = report(repo, "--cleanup", "main", "feat/parked", "--force")

    assert payload["_exit"] == EXIT_REFUSED
    refusal = payload["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_PROTECTED"
    assert {t["name"] for t in refusal["blocked"]} == {"main", "feat/parked"}  # type: ignore[union-attr]
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/main") != ""
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "feat/parked"
    assert find(payload, "branch:main")["disposition"] == Disposition.PROTECTED.value


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

    payload = report(repo)

    names = [t["name"] for t in payload["targets"]]  # type: ignore[union-attr]
    assert not any("secret" in str(n) for n in names)
    assert not any(str(neighbour) in str(n) for n in names)


# -- worktrees ----------------------------------------------------------------


def _worktree(repo: Path, name: str, branch: str) -> Path:
    path = repo.parent / name
    git(repo, "worktree", "add", "-q", str(path), "-b", branch)
    return path


def test_a_dirty_worktree_is_active_and_refused(repo: Path) -> None:
    work = _worktree(repo, "wt-dirty", "feat/wt")
    (work / "README.md").write_text("edited but never committed\n", encoding="utf-8")

    payload = report(repo, "--cleanup", str(work))

    assert payload["_exit"] == EXIT_REFUSED
    assert payload["refusal"]["code"] == "E_DATA_LOSS"  # type: ignore[index]
    assert work.exists()


def test_a_worktree_holding_only_ignored_files_still_sweeps(repo: Path) -> None:
    """The settled trade, against real git: ignored content is reported but
    does not make a finished worktree need --force. Treating caches as work at
    risk would put a manual triage in front of every automatic cleanup."""
    (repo / ".gitignore").write_text(".cache/\n", encoding="utf-8")
    git(repo, "add", "--", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore caches")

    work = _worktree(repo, "wt-cached", "feat/cached")
    (work / ".cache").mkdir()
    (work / ".cache" / "blob").write_text("regenerates for free\n", encoding="utf-8")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/cached")

    payload = report(repo, "--cleanup", str(work))

    assert payload["_exit"] == EXIT_OK
    assert not work.exists()
    target = find(payload, f"worktree:{work}")
    assert any("ignored file" in r for r in target["reasons"])  # type: ignore[union-attr]


def test_a_worktree_that_goes_dirty_after_the_survey_is_left_alone(repo: Path) -> None:
    """The window this tool re-surveys to close, forced open.

    The plan says risk=none, so nothing was archived. Reality says the tree has
    changes. `worktree remove` without --force is the only thing left that can
    notice, which is why it is not spent unconditionally."""
    work = _worktree(repo, "wt-race", "feat/race")
    survey_data = run_survey(GitOnly(), cwd=repo)
    assert not isinstance(survey_data, str)

    # ... and now the agent that owns this worktree writes a file.
    (work / "urgent.txt").write_text("work that exists nowhere else\n", encoding="utf-8")

    stale = Target(
        id=f"worktree:{work}",
        kind=TargetKind.WORKTREE,
        name=str(work),
        disposition=Disposition.SAFE,
        risk=Risk.NONE,
        reasons=(),
        last_activity=None,
        salvage_needed=False,
    )
    outcome = Executor(GitOnly(), survey_data, cwd=repo).run(
        Plan(targets=(stale,), salvage_dir=None, dry_run=False)
    )

    assert not outcome.ok
    assert work.exists()
    assert (work / "urgent.txt").read_text(encoding="utf-8").startswith("work that exists")
    assert "not there when it was surveyed" in outcome.anomalies[0].message
    assert any("--force" in line for line in outcome.anomalies[0].transcript)


def test_an_active_worktree_survives_a_bare_sweep(repo: Path) -> None:
    """A bare sweep takes safe-and-none. A worktree holding work that was never
    committed is neither, and an automatic run must leave it standing rather
    than deciding for the person using it."""
    work = _worktree(repo, "wt-live", "feat/live-wt")
    (work / "in-progress.txt").write_text("uncommitted\n", encoding="utf-8")

    swept = report(repo, "--cleanup")

    assert swept["_exit"] == EXIT_OK
    assert work.exists()
    assert find(swept, f"worktree:{work}")["disposition"] == Disposition.ACTIVE.value


# -- salvage round trip -------------------------------------------------------


def test_forced_salvage_captures_the_tree_and_restores_it(repo: Path, tmp_path: Path) -> None:
    """The archive is the promise --force makes. So: destroy a worktree
    holding content of every kind that has previously been lost -- tracked
    edits, untracked files, ignored files, and a symlink whose target holds a
    secret -- then unpack the archive and read it all back."""
    (repo / ".gitignore").write_text("secrets.env\n", encoding="utf-8")
    git(repo, "add", "--", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore secrets")

    work = _worktree(repo, "wt-salvage", "feat/salvage")
    (work / "README.md").write_text("edited\n", encoding="utf-8")
    (work / "scratch.txt").write_text("untracked\n", encoding="utf-8")
    (work / "secrets.env").write_text("TOKEN=hunter2\n", encoding="utf-8")

    private = tmp_path / "id_rsa"
    private.write_text("PRIVATE KEY MATERIAL\n", encoding="utf-8")
    (work / "link-to-key").symlink_to(private)

    payload = report(repo, "--cleanup", str(work), "--force")

    assert payload["_exit"] == EXIT_OK
    assert not work.exists()

    archive = Path(payload["execution"]["salvages"][0]["path"])  # type: ignore[index]
    assert archive.exists()

    restored = tmp_path / "restored"
    restored.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(restored, filter="tar")

    assert (restored / "README.md").read_text(encoding="utf-8") == "edited\n"
    assert (restored / "scratch.txt").read_text(encoding="utf-8") == "untracked\n"
    assert (restored / "secrets.env").read_text(encoding="utf-8") == "TOKEN=hunter2\n"
    # The link is preserved AS a link. Copying it would have written the key's
    # bytes into a salvage directory inside the repository.
    assert (restored / "link-to-key").is_symlink()
    assert "PRIVATE KEY" not in (restored / "link-to-key").readlink().name


def test_a_salvaged_branch_bundle_clones_back(repo: Path, tmp_path: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feat/unpushed")
    commit(repo, "only-copy.txt", "irreplaceable\n")
    git(repo, "checkout", "-q", "main")

    payload = report(repo, "--cleanup", "feat/unpushed", "--force")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/unpushed") == ""

    bundle = Path(payload["execution"]["salvages"][0]["path"])  # type: ignore[index]
    clone = tmp_path / "from-bundle"
    result = SubprocessCommands().git(
        ["clone", "-q", "--branch", "feat/unpushed", str(bundle), str(clone)]
    )

    assert result.ok, result.stderr
    assert (clone / "only-copy.txt").read_text(encoding="utf-8") == "irreplaceable\n"


# -- remote deletion ----------------------------------------------------------


def _with_remote(repo: Path, tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    SubprocessCommands().git(["init", "-q", "--bare", str(bare)])
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


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

    payload = report(repo, "--cleanup", "origin/feat/shared", "--include-remote")

    assert payload["_exit"] == EXIT_ANOMALY
    server_refs = git(repo, "ls-remote", "--heads", "origin", "feat/shared")
    assert "feat/shared" in server_refs
    anomalies = payload["execution"]["anomalies"]  # type: ignore[index]
    assert "fetch and re-run" in anomalies[0]["message"]


def test_naming_a_remote_branch_without_include_remote_is_refused(
    repo: Path, tmp_path: Path
) -> None:
    _with_remote(repo, tmp_path)
    git(repo, "checkout", "-q", "-b", "feat/pushed")
    commit(repo, "pushed.txt")
    git(repo, "push", "-q", "-u", "origin", "feat/pushed")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "feat/pushed")
    git(repo, "fetch", "-q", "origin")

    payload = report(repo, "--cleanup", "origin/feat/pushed")

    assert payload["_exit"] == EXIT_REFUSED
    assert payload["refusal"]["code"] == "E_REMOTE_NOT_ENABLED"  # type: ignore[index]
    assert "feat/pushed" in git(repo, "ls-remote", "--heads", "origin", "feat/pushed")


# -- argv hygiene -------------------------------------------------------------


def test_a_branch_named_like_an_option_is_swept_not_misread(repo: Path) -> None:
    """`git branch` will not create `-m`, but `update-ref` will and a remote
    can push one. Without an argv terminator on the delete, git reads the name
    as a switch and the sweep fails with a usage error.

    The automatic sweep is the path that matters: nobody types the name, so
    nothing shields git from it but the terminator."""
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/heads/-m", head)

    payload = report(repo, "--cleanup")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/-m") == ""
    assert "-m" in [d["name"] for d in payload["execution"]["deletions"]]  # type: ignore[index]


def test_a_branch_named_like_an_option_is_selectable_by_id(repo: Path) -> None:
    """Naming it directly cannot go through the bare name -- argparse claims
    `-m` as a flag before gitclean sees it. The `id` form is the way in, which
    is what the unknown-target refusal already tells the reader to use."""
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/heads/-m", head)

    payload = report(repo, "--cleanup", "branch:-m")

    assert payload["_exit"] == EXIT_OK
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/-m") == ""


# -- the idle boundary --------------------------------------------------------


def _committed_at(payload: dict[str, object], name: str) -> datetime:
    repo_data = payload["repo"]
    assert isinstance(repo_data, dict)
    branch = next(b for b in repo_data["branches"] if b["name"] == name)
    moment = parse_timestamp(branch["last_activity"])
    assert moment is not None
    return moment


def test_the_idle_window_is_exclusive_at_exactly_fourteen_days(repo: Path) -> None:
    """Measured from the commit git actually recorded, so the boundary is the
    real one rather than a timestamp the test wrote itself."""
    git(repo, "checkout", "-q", "-b", "feat/ageing")
    commit(repo, "aged.txt")
    git(repo, "checkout", "-q", "main")

    committed = _committed_at(report(repo), "feat/ageing")

    at_boundary = report(repo, "--report", now=committed + timedelta(days=14))
    past_boundary = report(repo, "--report", now=committed + timedelta(days=14, seconds=1))

    assert find(at_boundary, "branch:feat/ageing")["disposition"] == Disposition.ACTIVE.value
    assert find(past_boundary, "branch:feat/ageing")["disposition"] == Disposition.ABANDONED.value


def test_an_abandoned_branch_is_reported_but_never_swept(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "feat/forgotten")
    commit(repo, "forgotten.txt")
    git(repo, "checkout", "-q", "main")
    committed = _committed_at(report(repo), "feat/forgotten")

    payload = report(repo, "--cleanup", now=committed + timedelta(days=365))

    assert find(payload, "branch:feat/forgotten")["disposition"] == Disposition.ABANDONED.value
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/feat/forgotten") != ""


# -- the port itself ----------------------------------------------------------


def test_the_port_reports_a_real_failure_with_its_transcript(repo: Path) -> None:
    """Anomalies are only useful if the transcript is git's own words."""
    result: CommandResult = SubprocessCommands().git(["cat-file", "-e", "does-not-exist"], cwd=repo)

    assert not result.ok
    assert "$ git cat-file -e does-not-exist" in result.transcript()[0]
