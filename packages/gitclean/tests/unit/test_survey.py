"""Tests for the read pass: parsing, and the tiered merge proof."""

from __future__ import annotations

import json
from pathlib import Path

from gitclean.model import MergeEvidence, Survey
from gitclean.ports import CommandResult, ScriptedCommands, SubprocessCommands, fail, ok
from gitclean.survey import (
    _count_dirt,
    read_pull_requests,
    read_worktrees,
    resolve_base_ref,
    resolve_default_branch,
    resolve_repo,
    survey,
)

SEP = "\x1f"


_AUTO_TRACK = "\x00auto"
"""Sentinel: the tracking marker git would emit for the given upstream.

A branch with no upstream has no marker, and one that has an upstream is in
sync unless a test says otherwise -- which is the boring case every builder
here defaults to. Spelling `track` out on every call would make each ref line
an assertion about push state even in the tests that are about something
else."""


def porcelain(text: str) -> str:
    """A worktree listing framed the way git frames it under `-z`.

    The survey asks for that framing because a worktree path may contain a
    newline and the porcelain format emits it raw. The fixtures stay written
    with newlines, which is how anyone reads them; only the framing changes,
    and a record separator is a record separator either way. A fixture about a
    path that actually contains a newline says so by not coming through here."""
    return text.replace("\n", "\0")


_AUTO_UPSTREAM_REF = "\x00auto"
"""Sentinel: the full refname of the given upstream, read as a server copy.

Tracking a ref a remote publishes is the ordinary case, so a line that names an
upstream and nothing else describes one. A test about a branch tracking another
local branch spells `upstream_ref` out, which is the whole of what tells the two
apart."""


def ref_line(
    full: str,
    short: str,
    *,
    committed: str = "2026-07-20T00:00:00+00:00",
    upstream: str = "",
    upstream_ref: str = _AUTO_UPSTREAM_REF,
    track: str = _AUTO_TRACK,
    head: str = "",
) -> str:
    if track == _AUTO_TRACK:
        track = "=" if upstream else ""
    if upstream_ref == _AUTO_UPSTREAM_REF:
        upstream_ref = f"refs/remotes/{upstream}" if upstream else ""
    return SEP.join([full, short, "a" * 40, committed, upstream_ref, upstream, track, head])


def make_port(
    *,
    refs: list[str] | None = None,
    worktrees: str = "worktree /repo\nHEAD abc\nbranch refs/heads/main\n",
    prs: list[dict[str, object]] | None = None,
    local_merged: str = "",
    remote_merged: str = "",
    counts: dict[str, str] | None = None,
    extra: dict[str, CommandResult] | None = None,
    has_gh: bool = True,
    gh_result: CommandResult | None = None,
    remotes: str = "origin\n",
) -> ScriptedCommands:
    table: dict[str, CommandResult] = {
        "rev-parse --show-toplevel": ok("/repo"),
        # Asked of every survey: it is the only thing that says where a
        # remote's name stops inside a path under refs/remotes/, so the boring
        # case has to answer it too.
        "remote": ok(remotes),
        "rev-parse --path-format=absolute --git-common-dir": ok("/repo/.git"),
        "symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/main"),
        "show-ref --verify --quiet refs/remotes/origin/main": ok(),
        "rev-parse --abbrev-ref HEAD": ok("main"),
        "worktree list --porcelain": ok(porcelain(worktrees)),
        "status --porcelain=v1": ok(""),
        # A detached worktree has no branch to take its age from, so the survey
        # dates it from HEAD instead.
        "show -s --format=%cI": ok("2026-07-20T00:00:00+00:00"),
        "for-each-ref": ok("\n".join(refs or [])),
        "branch --merged": ok(local_merged),
        "branch -r --merged": ok(remote_merged),
        # The trunk is probed like any other branch, so its own count is part
        # of the boring case. A test that cares what it says overrides it
        # through `counts`, which is applied after this table.
        "rev-list --count refs/remotes/origin/main..main": ok("0"),
        # The merge base's tree, which the squash tier compares against the
        # branch tip's. Deliberately unlike the "treesha" those tests give the
        # tip: the boring branch changed something, so there is a diff to
        # replay. A test about a branch that ends where it started says so by
        # overriding this to match.
        "rev-parse basesha^{tree}": ok("basetreesha"),
    }
    for spec, value in (counts or {}).items():
        table[f"rev-list --count {spec}"] = ok(value)
    table.update(extra or {})
    gh = gh_result or ok(json.dumps(prs or []))
    return ScriptedCommands(git=table, gh={"pr list": gh}, has_gh=has_gh)


def run(port: ScriptedCommands, **kwargs: object) -> Survey:
    result = survey(port, **kwargs)  # type: ignore[arg-type]
    assert isinstance(result, Survey)
    return result


# -- repo resolution ---------------------------------------------------------


def test_outside_a_repo_returns_a_message_not_an_exception() -> None:
    port = ScriptedCommands(git={"rev-parse --show-toplevel": fail("not a git repository")})
    assert survey(port) == "not inside a git repository"


def test_git_common_dir_falls_back_for_older_git() -> None:
    """--path-format landed in git 2.31; older git still answers the plain
    form, relative to the repo root."""
    port = ScriptedCommands(
        git={
            "rev-parse --show-toplevel": ok("/repo"),
            "rev-parse --path-format=absolute --git-common-dir": fail("unknown option"),
            "rev-parse --git-common-dir": ok(".git"),
        }
    )
    resolved = resolve_repo(port, None)
    assert resolved == ("/repo", "/repo/.git")


def test_unresolvable_common_dir_gives_up_rather_than_guessing() -> None:
    port = ScriptedCommands(
        git={
            "rev-parse --show-toplevel": ok("/repo"),
            "rev-parse --path-format=absolute --git-common-dir": fail("nope"),
            "rev-parse --git-common-dir": fail("nope"),
        }
    )
    assert resolve_repo(port, None) is None


# -- default branch ----------------------------------------------------------


def test_default_branch_comes_from_origins_published_head() -> None:
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/trunk"),
            "show-ref --verify --quiet refs/remotes/origin/trunk": ok(),
        }
    )
    assert resolve_default_branch(port, None) == ("trunk", None)


def test_default_branch_falls_back_to_master_when_main_is_absent() -> None:
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail(),
            "show-ref --verify --quiet refs/heads/main": fail(),
            "show-ref --verify --quiet refs/heads/master": ok(),
        }
    )
    assert resolve_default_branch(port, None) == ("master", None)


def test_an_unidentifiable_default_branch_is_unknown_not_guessed_as_main() -> None:
    """Guessing `main` looked harmless -- every probe against a ref that is not
    there fails, so nothing could be proven merged. But protection is assigned
    by name, so in a repository whose trunk is `trunk` the guess left no branch
    protected at all, and the real trunk was as deletable as the cruft."""
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail(),
            "show-ref --verify --quiet refs/heads/": fail(),
        }
    )
    name, warning = resolve_default_branch(port, None)
    assert name is None
    assert warning is not None and "origin has published no HEAD" in warning


def test_a_dangling_origin_head_is_not_a_default_branch() -> None:
    """The tier most likely to be stale was the one tier never verified.

    A server-side default-branch rename leaves `origin/HEAD -> origin/master`
    behind with no `origin/master` for it to point at. Trusting it names a
    trunk that exists nowhere -- and because the guess was then recorded as
    knowledge, it also suppressed the warning that would have said no branch is
    protected as the trunk."""
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/master"),
            "show-ref --verify --quiet refs/remotes/origin/master": fail(),
            "show-ref --verify --quiet refs/heads/main": fail(),
            "show-ref --verify --quiet refs/heads/master": fail(),
        }
    )
    name, warning = resolve_default_branch(port, None)
    assert name is None
    assert warning is not None and "origin/master" in warning


def test_a_dangling_origin_head_still_falls_through_to_a_local_trunk() -> None:
    """Declining the stale pointer must not cost the answer a lower tier can
    still verify."""
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/master"),
            "show-ref --verify --quiet refs/remotes/origin/master": fail(),
            "show-ref --verify --quiet refs/heads/main": ok(),
        }
    )
    assert resolve_default_branch(port, None) == ("main", None)


def test_a_dangling_origin_head_leaves_the_trunk_unknown_on_the_report() -> None:
    """The consequence the survey has to carry: `default_branch_known` False,
    so nothing downstream reads the guess as a protected name."""
    port = make_port(
        refs=[ref_line("refs/heads/trunk", "trunk", head="*")],
        counts={"refs/remotes/origin/main..trunk": "3"},
        extra={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/master"),
            "show-ref --verify --quiet refs/remotes/origin/master": fail(),
            "show-ref --verify --quiet refs/heads/main": fail(),
            "show-ref --verify --quiet refs/heads/master": fail(),
            "cherry refs/remotes/origin/main -- trunk": fail(),
            "merge-base refs/remotes/origin/main -- trunk": fail(),
        },
    )

    result = run(port)

    assert result.default_branch_known is False
    assert any("origin/master" in w for w in result.warnings)


def test_an_unknown_default_branch_is_reported_on_the_survey() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/trunk", "trunk"),
            ref_line("refs/heads/feature", "feature", head="*"),
        ],
        counts={"refs/heads/main..trunk": "3", "refs/heads/main..feature": "1"},
        extra={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail(),
            "show-ref --verify --quiet refs/heads/main": fail(),
            "show-ref --verify --quiet refs/heads/master": fail(),
            "show-ref --verify --quiet refs/remotes/origin/main": fail(),
            "cherry refs/heads/main -- trunk": fail(),
            "cherry refs/heads/main -- feature": fail(),
            "merge-base refs/heads/main -- trunk": fail(),
            "merge-base refs/heads/main -- feature": fail(),
        },
    )

    result = run(port)

    assert result.default_branch_known is False
    assert any("could not determine" in w for w in result.warnings)


def test_a_ref_probe_that_errors_is_not_read_as_a_missing_trunk() -> None:
    """`show-ref` exits 1 for a ref that is not there and 128 when it could not
    look. Collapsing the two told the reader that neither main nor master
    exists on the strength of a probe that never ran, which sends them to
    create a branch they already have."""
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail(),
            "show-ref --verify --quiet refs/heads/main": fail("fatal: bad repository", code=128),
            "show-ref --verify --quiet refs/heads/master": fail(),
        }
    )

    name, warning = resolve_default_branch(port, None)

    assert name is None
    assert warning is not None
    assert "would not say whether refs/heads/main exists" in warning
    assert "neither main nor master exists" not in warning


def test_an_unreadable_published_head_is_not_reported_as_an_unpublished_one() -> None:
    """`symbolic-ref --quiet` exits 1 when origin has published no HEAD; any
    other exit is git declining to answer, and telling someone to publish a
    HEAD they may already have published is the wrong instruction."""
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail("fatal: bad", code=128),
            "show-ref --verify --quiet refs/heads/": fail(),
        }
    )

    name, warning = resolve_default_branch(port, None)

    assert name is None
    assert warning is not None and "published HEAD could not be read" in warning


def test_base_prefers_the_remote_tracking_tip() -> None:
    """A stale local default branch would under-report merges.

    Handed back as a full ref path, which is the whole of what makes it name
    the ref this just proved exists: `origin/main` is also a legal *local*
    branch, and git reaches `refs/heads/` before `refs/remotes/`."""
    port = ScriptedCommands(git={"show-ref --verify --quiet refs/remotes/origin/main": ok()})
    assert resolve_base_ref(port, None, "main") == ("refs/remotes/origin/main", None)


def test_base_falls_back_to_the_local_branch_without_a_remote() -> None:
    """The fallback is a ref path for the same reason: `main` alone would find
    a tag of that name before the branch."""
    port = ScriptedCommands(git={"show-ref --verify --quiet refs/remotes/origin/main": fail()})
    assert resolve_base_ref(port, None, "main") == ("refs/heads/main", None)


def test_an_unreadable_remote_tip_falls_back_to_the_local_branch_and_says_so() -> None:
    """The same fallback, for a different reason: git errored rather than
    reporting the ref absent. Every merge in the report is then measured
    against a ref that may be behind the remote, which is only safe to read if
    it is said."""
    port = ScriptedCommands(
        git={"show-ref --verify --quiet refs/remotes/origin/main": fail("bad object", code=128)}
    )
    base, warning = resolve_base_ref(port, None, "main")
    assert base == "refs/heads/main"
    # The warning is prose for a reader, so it keeps the short spelling the
    # reader would type; only the rev handed to git has to be unambiguous.
    assert warning is not None and "would not say whether origin/main exists" in warning


# -- worktree parsing --------------------------------------------------------


def test_worktree_porcelain_blocks_are_parsed() -> None:
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(
                porcelain(
                    "worktree /repo\nHEAD aaa\nbranch refs/heads/main\n"
                    "\n"
                    "worktree /repo/wt\nHEAD bbb\nbranch refs/heads/feat\nlocked\n"
                    "\n"
                    "worktree /repo/gone\nHEAD ccc\ndetached\nprunable gitdir file removed\n"
                )
            ),
            "status --porcelain=v1": ok(""),
        }
    )
    worktrees, warnings, _known, _dropped, _framed = read_worktrees(port, None)
    assert [w.path for w in worktrees] == ["/repo", "/repo/wt", "/repo/gone"]
    assert worktrees[0].is_main and worktrees[0].branch == "main"
    assert worktrees[1].locked
    assert worktrees[2].prunable and worktrees[2].branch is None
    # The only warning parsing produces here: an unreachable tree whose
    # contents nothing can measure.
    assert [w for w in warnings if "/repo/gone" not in w] == []


def test_a_worktree_block_without_a_path_is_warned_not_dropped_silently() -> None:
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(porcelain("HEAD aaa\nbranch refs/heads/x\n")),
            "status --porcelain=v1": ok(""),
        }
    )
    worktrees, warnings, _known, _dropped, _framed = read_worktrees(port, None)
    assert worktrees == []
    assert warnings and "no path" in warnings[0]


def test_modified_untracked_and_ignored_files_are_counted_separately() -> None:
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(porcelain("worktree /repo\n")),
            "status --porcelain=v1": ok(" M a.txt\nA  b.txt\n?? c.txt\n?? d.txt\n!! .env\n"),
        }
    )
    worktrees, _, _known, _dropped, _framed = read_worktrees(port, None)
    assert worktrees[0].dirty_file_count == 2
    assert worktrees[0].untracked_file_count == 2
    assert worktrees[0].ignored_file_count == 1
    assert worktrees[0].dirty


def test_ignored_files_are_counted_but_do_not_make_a_worktree_dirty() -> None:
    """The settled trade. Ignored content is overwhelmingly caches and
    virtualenvs; calling it work at risk would make every finished worktree
    need --force and turn an automatic cleanup into a manual triage. It is
    counted so the report can name it, and the count drives nothing."""
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(porcelain("worktree /repo\n")),
            "status --porcelain=v1": ok("!! .venv/\n!! __pycache__/\n!! .env\n"),
        }
    )
    worktrees, _, _known, _dropped, _framed = read_worktrees(port, None)
    assert worktrees[0].ignored_file_count == 3
    assert worktrees[0].dirty is False


def test_the_dirt_probe_counts_files_rather_than_status_lines() -> None:
    """Counted for the report even though it does not drive the verdict: a
    reader deciding whether to sweep needs to know what goes with it -- and a
    count is only that disclosure if it counts files.

    `--untracked-files=normal` collapses a whole untracked directory to one
    line, so 40,000 files under `node_modules/` disclose as 1. `=all` expands
    it. Ignored content needs BOTH flags: under `--ignored=matching` any
    directory matching an ignore pattern re-collapses to its one line whatever
    the untracked mode says, and only `traditional` defers to `=all`."""
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(porcelain("worktree /repo\n")),
            "status --porcelain=v1": ok(""),
        }
    )
    read_worktrees(port, None)
    status_call = next(t for t in port.transcript if t[1] == "status")
    assert "--untracked-files=all" in status_call
    assert "--ignored=traditional" in status_call


def test_a_real_ignored_directory_is_counted_file_by_file(tmp_path: Path) -> None:
    """The one claim in this file that scripted output cannot make.

    Every other dirt test asserts what the parser does with bytes a fixture
    handed it, which is exactly how the collapsed-directory bug survived: the
    fixtures spelled one line per file because their author assumed git did.
    This asks real git."""
    port = SubprocessCommands()
    port.git(["init", "-q", "."], cwd=tmp_path)
    (tmp_path / ".gitignore").write_text("cache/\n*.log\n", encoding="utf-8")
    port.git(["add", ".gitignore"], cwd=tmp_path)
    port.git(
        ["-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
    )
    for directory in ("cache", "untracked"):
        (tmp_path / directory).mkdir()
        for index in range(500):
            (tmp_path / directory / f"f{index}.txt").write_text("x", encoding="utf-8")
    (tmp_path / "debug.log").write_text("x", encoding="utf-8")
    (tmp_path / "loose.txt").write_text("x", encoding="utf-8")

    assert _count_dirt(port, tmp_path) == (0, 501, 501)


def test_a_worktree_git_cannot_stat_is_unknown_not_clean() -> None:
    """The dangerous default. `dirty=False` here would send an unreadable tree
    -- the one most likely to be holding something -- into the sweep at
    Risk.NONE with no salvage."""
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(porcelain("worktree /repo/opaque\n")),
            "status --porcelain=v1": fail("no such directory"),
        }
    )
    worktrees, warnings, _known, _dropped, _framed = read_worktrees(port, None)
    assert worktrees[0].dirty is None
    assert worktrees[0].dirty_file_count is None
    assert worktrees[0].untracked_file_count is None
    assert any("could not read the working-tree status" in w for w in warnings)


def test_a_prunable_worktree_is_unknown_dirt_not_clean() -> None:
    """`prunable` was read as "the directory is gone, so there is nothing to
    stat" and its dirt asserted (0, 0, 0). git says prunable whenever the path
    is merely UNREACHABLE -- a tree moved aside, or on an unmounted volume,
    reports prunable while `.env` and an afternoon of uncommitted work sit
    intact inside it. Nothing here can be probed and nothing here is known, so
    the dirt is unknown and the path is named."""
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(
                porcelain(
                    "worktree /repo/moved\nHEAD ccc\ndetached\n"
                    "prunable gitdir file points to non-existent location\n"
                )
            ),
        }
    )
    worktrees, warnings, _known, _dropped, _framed = read_worktrees(port, None)
    assert worktrees[0].dirty is None
    assert worktrees[0].dirty_file_count is None
    assert worktrees[0].untracked_file_count is None
    assert worktrees[0].ignored_file_count is None
    assert any("/repo/moved" in w for w in warnings)
    # Still not probed: git has already said the path is unreachable, so the
    # probe would fail and say less than the warning above already does.
    assert "status" not in [t[1] for t in port.transcript]


def test_unlistable_worktrees_are_reported() -> None:
    port = ScriptedCommands(git={"worktree list --porcelain": fail("boom")})
    worktrees, warnings, _known, _dropped, _framed = read_worktrees(port, None)
    assert worktrees == []
    assert warnings


# -- pull requests -----------------------------------------------------------


def test_missing_gh_is_reported_as_a_limit_on_the_evidence() -> None:
    """Without gh there is no squash-merge signal at all, so this must never
    be swallowed."""
    port = ScriptedCommands(has_gh=False)
    prs, error, _ = read_pull_requests(port, None)
    assert prs == {}
    assert error is not None and "squash" in error


def test_a_failing_gh_call_is_reported() -> None:
    port = ScriptedCommands(gh={"pr list": fail("no git remotes found")}, has_gh=True)
    _, error, _ = read_pull_requests(port, None)
    assert error is not None and "no git remotes found" in error


def test_unparseable_gh_json_is_reported() -> None:
    port = ScriptedCommands(gh={"pr list": ok("{{{not json")}, has_gh=True)
    _, error, _ = read_pull_requests(port, None)
    assert error is not None and "unparseable" in error


def test_a_non_list_gh_payload_is_reported() -> None:
    port = ScriptedCommands(gh={"pr list": ok('{"unexpected": true}')}, has_gh=True)
    _, error, _ = read_pull_requests(port, None)
    assert error is not None and "non-list" in error


def test_the_newest_pr_wins_for_a_reused_branch() -> None:
    """A reopened or superseding PR describes the branch now; an older closed
    one does not."""
    payload = json.dumps(
        [
            {
                "number": 1,
                "state": "CLOSED",
                "headRefName": "feat/x",
                "url": "u1",
                "updatedAt": "2026-01-01T00:00:00Z",
            },
            {
                "number": 2,
                "state": "MERGED",
                "headRefName": "feat/x",
                "url": "u2",
                "updatedAt": "2026-06-01T00:00:00Z",
            },
        ]
    )
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)
    prs, _, _ = read_pull_requests(port, None)
    assert prs["feat/x"].number == 2


def test_malformed_pr_entries_are_skipped() -> None:
    payload = json.dumps(["not a dict", {"number": 3, "state": "OPEN", "headRefName": ""}])
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)
    prs, _, _ = read_pull_requests(port, None)
    assert prs == {}


def test_a_pr_number_that_is_not_a_number_costs_one_entry_not_the_report() -> None:
    """`int()` on whatever gh put there would raise out of the read pass and
    take the whole survey with it."""
    payload = json.dumps(
        [
            {"number": "not-a-number", "state": "MERGED", "headRefName": "broken"},
            {
                "number": 4,
                "state": "OPEN",
                "headRefName": "fine",
                "updatedAt": "2026-07-20T00:00:00Z",
            },
        ]
    )
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)

    prs, error, gap = read_pull_requests(port, None)

    assert error is None
    assert "broken" not in prs
    assert prs["fine"].number == 4
    # Dropping it quietly leaves `broken` looking like a branch that never had
    # a PR, which is the one shape a squash merge hides behind.
    assert gap is not None and "1 of the 2 pull requests" in gap


def test_pr_entries_gh_describes_in_other_terms_are_counted_not_swallowed() -> None:
    payload = json.dumps(["not-an-object", {"number": 2, "headRefName": ""}])
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)

    prs, error, gap = read_pull_requests(port, None)

    assert prs == {} and error is None
    assert gap is not None and "2 of the 2 pull requests" in gap


def test_a_pr_list_at_the_cap_says_the_evidence_is_incomplete() -> None:
    """gh was asked for a bounded number of PRs. At the bound there may be more
    it never returned, and a branch whose PR is among them is judged on git
    evidence alone -- correct, but weaker than the caller assumes."""
    payload = json.dumps(
        [
            {
                "number": n,
                "state": "MERGED",
                "headRefName": f"feat/{n}",
                "updatedAt": "2026-07-20T00:00:00Z",
            }
            for n in range(500)
        ]
    )
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)

    prs, error, truncated = read_pull_requests(port, None)

    assert error is None
    assert len(prs) == 500
    assert truncated is not None
    assert "git evidence alone" in truncated


def test_a_pr_list_below_the_cap_warns_about_nothing() -> None:
    payload = json.dumps(
        [
            {
                "number": 1,
                "state": "OPEN",
                "headRefName": "feat/a",
                "updatedAt": "2026-07-20T00:00:00Z",
            }
        ]
    )
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)

    assert read_pull_requests(port, None)[2] is None


# -- ref classification ------------------------------------------------------


def test_origins_symbolic_head_is_not_offered_as_a_branch() -> None:
    """git shortens refs/remotes/origin/HEAD to `origin` -- no slash, no HEAD
    suffix -- so a short-name filter reads it as a local branch to delete."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/origin/HEAD", "origin"),
        ]
    )
    names = [b.name for b in run(port).branches]
    assert "origin" not in names


def test_a_worktree_path_holding_a_newline_is_recorded_whole() -> None:
    """`worktree list --porcelain` emits a newline in a path raw -- it escapes
    nothing -- so a line-based reader records `/repo/we` and reads `ird` as a
    stray key. `-z` frames each record with a NUL, which a path cannot
    contain."""
    port = make_port(worktrees="worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n")
    port._git["worktree list --porcelain"] = ok(
        porcelain("worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n")
        + "worktree /repo/we\nird\0HEAD bbb\0branch refs/heads/wt\0\0"
    )

    surveyed = run(port)

    assert [w.path for w in surveyed.worktrees] == ["/repo", "/repo/we\nird"]
    assert surveyed.dropped_worktrees == 0


def test_a_git_without_nul_framing_drops_what_it_could_not_account_for() -> None:
    """A git that declines `-z` gets the line-based read, where the
    only evidence that a path was cut short is the fragment arriving as a key
    the format does not have. That block is dropped rather than recorded under
    a truncated path -- a name that then matches nothing, about a worktree
    sitting right there."""
    port = make_port()
    port._git["worktree list --porcelain -z"] = fail("error: unknown switch `z'", code=129)
    port._git["worktree list --porcelain"] = ok(
        "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\nworktree /repo/we\nird\nHEAD bbb\n"
    )

    surveyed = run(port)

    assert [w.path for w in surveyed.worktrees] == ["/repo"]
    assert surveyed.worktrees_known is True
    assert surveyed.dropped_worktrees == 1
    assert any("NUL framing" in w for w in surveyed.all_warnings())


def test_an_old_git_still_lists_ordinary_worktrees() -> None:
    """The fallback is a fallback, not a refusal: with no newline anywhere,
    every key is one the format has and nothing is dropped."""
    port = make_port()
    port._git["worktree list --porcelain -z"] = fail("error: unknown switch `z'", code=129)
    port._git["worktree list --porcelain"] = ok(
        "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
        "worktree /repo/wt\nHEAD bbb\nbranch refs/heads/feat\n"
    )

    surveyed = run(port)

    assert [w.path for w in surveyed.worktrees] == ["/repo", "/repo/wt"]
    assert surveyed.dropped_worktrees == 0


def test_a_failed_worktree_listing_is_recorded_as_unread_not_as_empty() -> None:
    """A repository with only its main working tree lists one entry; a listing
    that failed lists none. Both arrive as an empty tuple, and only one of them
    supports concluding that a named worktree is gone."""
    port = make_port(extra={"worktree list --porcelain": fail("fatal: bad config")})

    surveyed = run(port)

    assert surveyed.worktrees == ()
    assert surveyed.worktrees_known is False


def test_a_worktree_listing_that_answered_says_so() -> None:
    port = make_port()
    surveyed = run(port)
    assert surveyed.worktrees_known is True
    assert surveyed.dropped_worktrees == 0


def test_a_dropped_worktree_block_is_counted_not_just_warned() -> None:
    """The warning is prose for a reader. The count is what stops a later
    "nothing matched that name" being read as absence."""
    port = make_port(worktrees="worktree /repo\nHEAD abc\n\nHEAD deadbeef\nbranch refs/heads/x\n")

    surveyed = run(port)

    assert surveyed.worktrees_known is True
    assert surveyed.dropped_worktrees == 1


def test_an_unparseable_ref_row_is_counted_and_warned_rather_than_vanishing() -> None:
    """These rows used to be dropped in silence, so a ref could go unrecorded
    with nothing anywhere saying a row had been lost."""
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*"), "truncated\x1frow"])

    surveyed = run(port)

    assert surveyed.branches_known is True
    assert surveyed.dropped_refs == 1
    assert any("could not be parsed" in w for w in surveyed.all_warnings())


def test_a_ref_left_out_of_the_targets_is_recorded_rather_than_dropped() -> None:
    """Skipping it silently makes "not a target" and "not in the repository"
    the same fact downstream, and only one of them lets a caller be told there
    is nothing to delete.

    The symbolic HEAD is recorded under a spelling somebody might actually
    type. git shortens the ref to a bare `origin`, which nobody would."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/origin/HEAD", "origin"),
            ref_line("refs/remotes/origin/main", "origin/main"),
        ]
    )

    surveyed = run(port)

    recorded = {n.name: n.reason for n in surveyed.not_offered}
    assert set(recorded) == {"origin/HEAD", "origin/main"}
    assert "symbolic HEAD" in recorded["origin/HEAD"]
    assert "trunk" in recorded["origin/main"]
    assert "origin/main" not in [b.name for b in surveyed.branches]


def test_a_remote_name_containing_a_slash_is_taken_whole() -> None:
    """`git remote add team/origin <url>` is accepted, so the slash between a
    remote and its branch is a delimiter the remote's own name may contain.
    The configured remote list is the only thing that says where one ends."""
    port = make_port(
        remotes="team/origin\n",
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/team/origin/feat/x", "team/origin/feat/x"),
        ],
        counts={"refs/remotes/origin/main..team/origin/feat/x": "0"},
    )

    surveyed = run(port)
    feat = next(b for b in surveyed.branches if b.is_remote)

    assert (feat.remote, feat.ref_name) == ("team/origin", "feat/x")
    assert feat.ref == "refs/remotes/team/origin/feat/x"
    assert surveyed.remotes == ("team/origin",)


def test_the_servers_trunk_is_recognised_under_a_slash_named_remote() -> None:
    """The exclusion compares the ref's own name against the default branch,
    so it only fires if the remote's name stopped in the right place. Splitting
    at the first slash leaves `origin/main`, which is not `main`, and the
    server's copy of the trunk becomes a deletion candidate."""
    port = make_port(
        remotes="team/origin\n",
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/team/origin/main", "team/origin/main"),
        ],
    )

    surveyed = run(port)

    recorded = {n.name: n.reason for n in surveyed.not_offered}
    assert "trunk" in recorded["team/origin/main"]
    assert not [b for b in surveyed.branches if b.is_remote]


def test_a_local_branch_colliding_with_a_remote_ref_keeps_its_own_name() -> None:
    """With a local branch literally called `origin/main`, git stops shortening
    the server's trunk to `origin/main` at all -- it becomes
    `remotes/origin/main`, and the local one becomes `heads/origin/main`.

    Reading a name out of either yields something nobody has: the remote
    `remotes`, or a local branch called `heads/origin/main`. Both names come
    from the ref path instead, and the two refs stay distinct."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/origin/main", "heads/origin/main"),
            ref_line("refs/remotes/origin/main", "remotes/origin/main"),
        ],
        counts={"refs/remotes/origin/main..heads/origin/main": "0"},
    )

    surveyed = run(port)
    local = next(b for b in surveyed.branches if b.ref == "refs/heads/origin/main")

    assert local.name == "origin/main"
    assert local.is_remote is False
    # The probe spelling is git's own, because `origin/main` in an argv now
    # resolves to this branch rather than to the server's copy of the trunk.
    assert local.probe_ref == "heads/origin/main"
    # And the server's copy is still recognised as the trunk's, which is the
    # half the first-slash split silently stopped doing.
    assert "trunk" in {n.name: n.reason for n in surveyed.not_offered}["origin/main"]


def test_a_server_ref_no_configured_remote_accounts_for_is_not_offered() -> None:
    """A tracking ref outliving its remote. Nothing says which part of the path
    is a remote's name, so nothing can be issued against it -- and it is right
    there, so a caller who names it must not be told it is already gone."""
    port = make_port(
        remotes="upstream\n",
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/origin/feat/x", "origin/feat/x"),
        ],
    )

    surveyed = run(port)

    assert not [b for b in surveyed.branches if b.is_remote]
    assert (
        "no configured remote accounts"
        in {n.name: n.reason for n in surveyed.not_offered}["origin/feat/x"]
    )


def test_a_ref_two_remotes_could_own_is_reported_rather_than_guessed() -> None:
    """With both `team` and `team/origin` configured, `refs/remotes/team/origin/x`
    is a branch called `origin/x` on one of them or `x` on the other, and the
    path does not say which. Picking one issues a deletion against a repository
    nobody asked about."""
    port = make_port(
        remotes="team\nteam/origin\n",
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/team/origin/x", "team/origin/x"),
        ],
    )

    surveyed = run(port)

    assert not [b for b in surveyed.branches if b.is_remote]
    reason = {n.name: n.reason for n in surveyed.not_offered}["team/origin/x"]
    assert "team, team/origin" in reason


def test_an_unreadable_remote_list_leaves_every_server_ref_unoffered() -> None:
    """The question that decides where a remote's name ends is one probe like
    any other, and an unanswered probe authorises nothing. Every ref under
    refs/remotes/ then stays in the report as unsplittable rather than being
    split on a guess."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/origin/feat/x", "origin/feat/x"),
        ],
        extra={"remote": fail("fatal: bad config line 3")},
    )

    surveyed = run(port)

    assert surveyed.remotes_known is False
    assert surveyed.remotes == ()
    assert not [b for b in surveyed.branches if b.is_remote]
    assert any("remote list" in w for w in surveyed.all_warnings())
    assert "could not be read" in {n.name: n.reason for n in surveyed.not_offered}["origin/feat/x"]


def test_remote_refs_are_identified_by_prefix_not_by_a_slash() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/team/feat", "team/feat"),
            ref_line("refs/remotes/origin/feat", "origin/feat"),
        ],
        counts={
            "refs/remotes/origin/main..team/feat": "1",
            "refs/remotes/origin/main..origin/feat": "1",
        },
        extra={
            "cherry refs/remotes/origin/main -- team/feat": ok("+ abc"),
            "cherry refs/remotes/origin/main -- origin/feat": ok("+ abc"),
            "merge-base refs/remotes/origin/main": ok("base1"),
            "rev-parse base1^{tree}": ok("basetree1"),
            "rev-parse team/feat^{tree}": ok("tree1"),
            "rev-parse origin/feat^{tree}": ok("tree2"),
            "commit-tree": ok("synth"),
            "cherry refs/remotes/origin/main synth": ok("+ zzz"),
        },
    )
    by_name = {b.name: b for b in run(port).branches}
    assert by_name["team/feat"].is_remote is False
    assert by_name["origin/feat"].is_remote is True
    assert by_name["origin/feat"].remote == "origin"


def test_the_remote_copy_of_the_default_branch_is_not_a_candidate() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/remotes/origin/main", "origin/main"),
        ]
    )
    assert [b.name for b in run(port).branches] == ["main"]


def test_short_ref_lines_are_skipped() -> None:
    port = make_port(refs=["not-enough-fields", ""])
    assert run(port).branches == ()


def test_unreadable_refs_yield_no_branches_but_say_so() -> None:
    """An empty branch list and a confident `ok` is how a report becomes
    silently incomplete."""
    port = make_port()
    port._git["for-each-ref"] = fail("boom")
    result = run(port)
    assert result.branches == ()
    assert any("could not list refs" in w for w in result.warnings)
    # An empty branch list is also what a repository holding nothing but its
    # trunk produces, and every worktree row is judged against these refs.
    assert result.branches_known is False


def test_refs_that_were_read_are_recorded_as_read() -> None:
    assert run(make_port(refs=[ref_line("refs/heads/main", "main", head="*")])).branches_known


def test_a_failed_batch_ancestry_check_is_warned_not_swallowed() -> None:
    """Failure here only loses the cheap tier -- the per-branch probes still
    answer -- so it degrades speed, not safety. It is still reported."""
    port = _tier_port(**{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    port._git["branch --merged"] = fail("boom")
    result = run(port)
    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.PATCH_EQUAL
    assert any("batch ancestry check for local branches" in w for w in result.warnings)


# -- the merge tiers ---------------------------------------------------------


def _tier_port(*, track: str = _AUTO_TRACK, **extra: CommandResult) -> ScriptedCommands:
    return make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat", upstream="origin/feat", track=track),
        ],
        counts={"refs/remotes/origin/main..feat": "2", "origin/feat..feat": "0"},
        extra=extra,
    )


def _pr(state: str, *, number: int = 7, oid: str = "a" * 40) -> dict[str, object]:
    return {
        "number": number,
        "state": state,
        "headRefName": "feat",
        "headRefOid": oid,
        "url": "u",
        "updatedAt": "2026-07-01T00:00:00Z",
    }


def test_a_merged_pr_is_the_top_tier_of_evidence() -> None:
    """`ref_line` publishes a tip of 40 a's, so this PR's head is the tip."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED")],
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.PR_MERGED


def test_a_merged_pr_that_predates_the_tip_does_not_prove_the_branch_merged() -> None:
    """The kill path in a many-agent workflow: PR #1 merges, the agent keeps
    committing toward a PR not yet opened. Trusting the merged state here
    deletes commits that exist nowhere else."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("not an ancestor"),
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        },
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert not feat.merged
    assert feat.merge_evidence is MergeEvidence.NONE


def test_a_tip_behind_the_merged_head_is_still_covered_by_the_merge() -> None:
    """Containment is directional. A final commit made on the forge leaves the
    local branch behind the merged head; that branch was still merged, and
    refusing it would turn every such branch into permanent cruft."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={"merge-base --is-ancestor": ok()},
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.PR_MERGED


def test_a_pr_with_no_head_sha_never_covers_a_tip() -> None:
    """Older gh, or a field that came back empty. Absent evidence is not
    matching evidence."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="")],
        extra={
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        },
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.NONE


def test_the_squash_tier_still_answers_when_a_pr_verdict_is_declined() -> None:
    """Declining a PR verdict costs speed, not truth: the content-reading tiers
    below it re-derive the answer. This is why tip-binding is affordable."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("not an ancestor"),
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("- synthsha"),
        },
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.SQUASH_EQUAL


def test_ancestry_settles_a_branch_with_nothing_ahead() -> None:
    port = _tier_port()
    port._git["rev-list --count refs/remotes/origin/main..feat"] = ok("0")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.ANCESTOR


def test_a_closed_pr_is_recorded_as_a_discard_not_a_merge() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("CLOSED", number=9)],
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert not feat.merged
    assert feat.merge_evidence is MergeEvidence.PR_CLOSED_UNMERGED


def test_a_discard_decision_does_not_reach_commits_made_after_it() -> None:
    """ "Drop this" applies to what was in the PR. A tip the closed head does
    not contain was never part of that decision."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("CLOSED", number=9, oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("not an ancestor"),
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        },
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.NONE


def test_patch_equivalence_catches_rebased_and_cherry_picked_work() -> None:
    port = _tier_port(**{"cherry refs/remotes/origin/main -- feat": ok("- aaa\n- bbb")})
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.PATCH_EQUAL


def test_squash_merges_are_caught_by_replaying_the_tree_as_one_commit() -> None:
    """Nothing cheaper detects this: the squashed commit shares no patch-id
    with any individual branch commit, and the tip is nobody's ancestor."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa\n+ bbb"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("- synthsha"),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.SQUASH_EQUAL


def test_a_branch_ending_on_the_tree_it_started_from_proves_nothing() -> None:
    """Work added and taken off again leaves the tip tree equal to the merge
    base's, so the synthesised commit's diff is empty -- and every empty diff
    carries the same patch id. `cherry` is scripted here to answer as it does
    against a base holding one empty commit, which one build retrigger leaves:
    it says the patch is already upstream. It is not, and neither is the work,
    which lives only on the commits this branch holds. The tier has to stop
    before asking a question whose answer it cannot use."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa\n+ bbb"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("sametree"),
            "rev-parse basesha^{tree}": ok("sametree"),
            "cherry refs/remotes/origin/main synthsha": ok("- synthsha"),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")

    assert not feat.merged
    assert feat.merge_evidence is MergeEvidence.NONE
    assert not any(call[1] == "commit-tree" for call in port.transcript), (
        "no commit should be synthesised once the diff is known to be empty"
    )


def test_the_squash_probe_terminates_argv_for_a_branch_named_like_an_option() -> None:
    """`refs/heads/-m` is a legal ref that `update-ref` or a remote push can
    create, and it reaches this tier the same way `feat` does above: ancestry
    and patch-id both miss. `merge-base` accepts `--`, so the branch name is
    terminated the same way as every other probe; `rev-parse` does not accept
    a terminator here, so the tree lookup instead resolves through the
    branch's full ref path, which never begins with `-`. Scripting only the
    corrected argv means a regression -- the bare name reappearing in either
    call -- fails with `ScriptedCommands has no answer for`, not a wrong
    verdict."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/-m", "-m"),
        ],
        counts={"refs/remotes/origin/main..-m": "2"},
        extra={
            "cherry refs/remotes/origin/main -- -m": ok("+ aaa\n+ bbb"),
            "merge-base refs/remotes/origin/main -- -m": ok("basesha"),
            "rev-parse refs/heads/-m^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("- synthsha"),
        },
    )
    branch = next(b for b in run(port).branches if b.name == "-m")
    assert branch.merged and branch.merge_evidence is MergeEvidence.SQUASH_EQUAL


def test_a_genuinely_unmerged_branch_proves_nothing() -> None:
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert not feat.merged and feat.merge_evidence is MergeEvidence.NONE


def test_a_squash_probe_that_stops_part_way_is_unknown_at_every_step() -> None:
    """Four commands make this tier, and a chain that stopped part-way proves
    nothing either way. Each step spells its own argv out: the fake matches on
    the longest key, so a short one is shadowed by the answer it meant to
    replace and the case goes untested while the suite stays green."""
    for broken in (
        {"merge-base refs/remotes/origin/main -- feat": fail("bad object", code=128)},
        {"rev-parse feat^{tree}": fail("bad object", code=128)},
        {"commit-tree treesha -p basesha -m gitclean-probe": fail("cannot write", code=128)},
        {"cherry refs/remotes/origin/main synthsha": fail("bad revision", code=128)},
    ):
        port = _tier_port(
            **{
                "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
                "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
                "rev-parse feat^{tree}": ok("treesha"),
                "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
                "cherry refs/remotes/origin/main synthsha": ok("+ x"),
                **broken,
            }
        )
        feat = next(b for b in run(port).branches if b.name == "feat")
        assert feat.merge_evidence is MergeEvidence.NONE
        assert any("squash-equivalence probe" in failure for failure in feat.probe_failures)


def test_an_empty_cherry_result_does_not_count_as_merged() -> None:
    """No output means the question was not answered, not that everything is
    already upstream."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok(""),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok(""),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert not feat.merged


# -- probes that did not answer ----------------------------------------------


def test_an_errored_patch_probe_is_an_unknown_not_a_negative() -> None:
    """`git cherry` has no exit code meaning "not equivalent", so a non-zero
    exit is a question that went unasked. Recording it as a negative left the
    row reading `evidence: none`, which is also what every tier running and
    finding nothing looks like."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": fail("fatal: bad revision", code=128),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        }
    )

    result = run(port)

    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.NONE
    assert any("patch-id probe" in failure for failure in feat.probe_failures)
    assert any("feat: the patch-id probe" in w for w in result.warnings)


def test_an_errored_squash_probe_is_an_unknown_not_a_negative() -> None:
    """The squash tier is the only one that sees a squash merge, so a row that
    does not say it went unasked reads as a branch nobody merged."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": fail("fatal: bad object", code=128),
        }
    )

    result = run(port)

    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.NONE
    assert any("squash-equivalence probe" in failure for failure in feat.probe_failures)
    assert not any("patch-id probe" in failure for failure in feat.probe_failures)


def test_histories_with_no_merge_base_are_answered_rather_than_unknown() -> None:
    """`merge-base` exits 1 to say these share no commit. That is git
    answering: there is no base to replay a tree onto, so there is no squash
    merge to find, and calling it an unknown would cry wolf on every unrelated
    history in the repository."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": fail(code=1),
        }
    )

    feat = next(b for b in run(port).branches if b.name == "feat")

    assert feat.merge_evidence is MergeEvidence.NONE
    assert feat.probe_failures == ()


def test_a_containment_check_git_cannot_answer_is_unknown_not_uncovered() -> None:
    """The merged commit is frequently absent locally once the remote branch is
    gone, and `merge-base --is-ancestor` then errors rather than answering no.
    Both outcomes decline the PR tier; only one of them compared the commits."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("fatal: Not a valid object name", code=128),
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        },
    )

    feat = next(b for b in run(port).branches if b.name == "feat")

    assert feat.pr_covers_tip is None
    assert not feat.merged


def test_a_containment_check_git_answers_no_to_is_recorded_as_no() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("", code=1),
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        },
    )

    assert next(b for b in run(port).branches if b.name == "feat").pr_covers_tip is False


def test_an_unreadable_head_is_not_reported_as_a_detached_checkout() -> None:
    """`current_branch` is None for a detached HEAD, so a failed read arrives
    looking like a measurement of one."""
    port = make_port(refs=[ref_line("refs/heads/main", "main")])
    port._git["rev-parse --abbrev-ref HEAD"] = fail("fatal: bad revision", code=128)

    result = run(port)

    assert result.current_branch is None
    assert any("could not read which branch this checkout is on" in w for w in result.warnings)


def test_an_unreadable_remote_tip_is_reported_on_the_assembled_survey() -> None:
    """Every merge verdict in the report was then measured against a local ref
    that may be behind the remote, which under-reports merges quietly unless
    the survey carries it."""
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", head="*")],
        counts={"refs/heads/main..main": "0"},
    )
    port._git["symbolic-ref --quiet refs/remotes/origin/HEAD"] = fail()
    port._git["show-ref --verify --quiet refs/heads/main"] = ok()
    port._git["show-ref --verify --quiet refs/remotes/origin/main"] = fail("bad", code=128)

    result = run(port)

    assert result.base_ref == "refs/heads/main"
    assert any("measured against the local main" in w for w in result.warnings)


def test_a_pull_request_gh_described_oddly_leaves_the_survey_saying_so() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"refs/remotes/origin/main..feat": "2"},
        prs=[
            {
                "number": "not-a-number",
                "state": "MERGED",
                "headRefName": "feat",
                "url": "u",
                "updatedAt": "2026-07-01T00:00:00Z",
            }
        ],
        extra={
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        },
    )

    result = run(port)

    assert result.pr_evidence_gap is not None
    assert any("could not be read and were left out" in w for w in result.warnings)


def test_an_unreadable_commit_date_leaves_the_worktree_age_unknown() -> None:
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", head="*")],
        worktrees="worktree /repo\nHEAD abc\ndetached\n",
    )
    port._git["show -s --format=%cI"] = fail("fatal: bad object", code=128)

    assert run(port).worktrees[0].last_activity is None


def test_the_batch_merged_list_short_circuits_the_per_branch_probes() -> None:
    port = _tier_port()
    port._git["branch --merged"] = ok("main\nfeat\n")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.ANCESTOR
    assert "cherry" not in [t[1] for t in port.transcript]


# -- assembly ----------------------------------------------------------------


def test_worktree_activity_is_taken_from_the_branch_it_holds() -> None:
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", head="*", committed="2026-07-19T00:00:00+00:00")],
        worktrees="worktree /repo\nHEAD abc\nbranch refs/heads/main\n",
    )
    result = run(port)
    assert result.worktrees[0].last_activity == "2026-07-19T00:00:00+00:00"


def test_a_detached_worktree_is_dated_from_its_head() -> None:
    """With no branch to inherit from, a detached worktree used to have no age
    at all -- and an unknown age can never be called abandoned, so it stayed in
    the report permanently. The HEAD commit answers the same question."""
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", head="*")],
        worktrees=(
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n"
            "\n"
            "worktree /repo/detached\nHEAD deadbeef\ndetached\n"
        ),
    )
    port._git["show -s --format=%cI deadbeef"] = ok("2026-07-01T09:00:00+00:00")

    detached = next(w for w in run(port).worktrees if w.path == "/repo/detached")

    assert detached.branch is None
    assert detached.last_activity == "2026-07-01T09:00:00+00:00"


def test_a_detached_worktree_git_will_not_date_stays_unknown() -> None:
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", head="*")],
        worktrees=(
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n"
            "\n"
            "worktree /repo/detached\nHEAD deadbeef\ndetached\n"
        ),
    )
    port._git["show -s --format=%cI deadbeef"] = fail("bad object")

    detached = next(w for w in run(port).worktrees if w.path == "/repo/detached")

    assert detached.last_activity is None


def test_a_prunable_worktree_is_not_probed_for_a_date() -> None:
    """Its directory is gone; there is nothing to ask about."""
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", head="*")],
        worktrees=(
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n"
            "\n"
            "worktree /repo/gone\nHEAD deadbeef\ndetached\nprunable gitdir file removed\n"
        ),
    )

    run(port)

    assert not any(call[:2] == ("git", "show") for call in port.transcript)


def test_a_detached_head_is_reported_as_no_current_branch() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main")])
    port._git["rev-parse --abbrev-ref HEAD"] = ok("HEAD")
    assert run(port).current_branch is None


def test_the_trunk_is_measured_rather_than_assumed() -> None:
    """The trunk used to be handed zeroes and a merge verdict unprobed.

    Its counts are the most useful ones in the report -- commits sitting on
    the local trunk that were never pushed are exactly what someone about to
    clean up wants to see -- and a row asserting a measurement nobody took is
    the habit that made this tool dangerous."""
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")])
    main = next(b for b in run(port).branches if b.name == "main")

    assert main.is_default
    assert ("git", "rev-list", "--count", "refs/remotes/origin/main..main") in port.transcript


def test_counts_that_are_not_numbers_are_unknown_not_zero() -> None:
    port = _tier_port(**{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    port._git["rev-list --count refs/remotes/origin/main..feat"] = ok("not-a-number")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.unmerged_commits is None


def test_a_failing_rev_list_is_unknown_and_never_proves_a_merge() -> None:
    """Zero here would read as 'nothing ahead of base', which resolves to
    ANCESTOR -- proof of a merge -- so one transient git failure would
    authorise deleting the very branch it failed on."""
    port = _tier_port(
        **{
            "cherry refs/remotes/origin/main -- feat": ok("+ aaa"),
            "merge-base refs/remotes/origin/main -- feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry refs/remotes/origin/main synthsha": ok("+ synthsha"),
        }
    )
    port._git["rev-list --count refs/remotes/origin/main..feat"] = fail("bad revision")
    result = run(port)
    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.unmerged_commits is None
    assert not feat.merged
    assert feat.merge_evidence is not MergeEvidence.ANCESTOR
    assert any("could not count the commits on feat" in w for w in result.warnings)


def test_a_failing_unpushed_count_is_unknown_and_warned() -> None:
    port = _tier_port(track=">", **{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    port._git["rev-list --count origin/feat..feat"] = fail("bad revision")
    result = run(port)
    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.unpushed_commits is None
    assert any("missing from origin/feat" in w for w in result.warnings)


def test_a_branch_in_sync_with_its_upstream_costs_no_probe() -> None:
    """The tracking marker already answered, and the overwhelming majority of
    branches are in sync -- paying a `rev-list` each to be told zero is the
    per-branch cost this batching exists to remove."""
    port = _tier_port(track="=", **{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    del port._git["rev-list --count origin/feat..feat"]

    feat = next(b for b in run(port).branches if b.name == "feat")

    assert feat.unpushed_commits == 0
    assert not any(
        call[:3] == ("git", "rev-list", "--count") and "origin/feat.." in call[3]
        for call in port.transcript
    )


def test_a_branch_only_behind_its_upstream_has_nothing_to_push() -> None:
    port = _tier_port(track="<", **{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    del port._git["rev-list --count origin/feat..feat"]
    assert next(b for b in run(port).branches if b.name == "feat").unpushed_commits == 0


def test_an_upstream_that_no_longer_exists_is_unknown_not_pushed() -> None:
    """`[gone]` -- the remote branch was deleted. Reading that as zero unpushed
    would claim a copy survives somewhere it does not, which is exactly the
    claim that lets a branch into the bare sweep."""
    port = _tier_port(track="", **{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    del port._git["rev-list --count origin/feat..feat"]

    result = run(port)

    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.unpushed_commits is None
    assert any("no longer exists" in w for w in result.warnings)


def test_a_branch_with_no_upstream_has_no_unpushed_count() -> None:
    """Zero would claim 'fully pushed' for a branch that was never pushed."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/solo", "solo"),
        ],
        counts={"refs/remotes/origin/main..solo": "2"},
        extra={
            "cherry refs/remotes/origin/main -- solo": ok("- aaa"),
        },
    )
    solo = next(b for b in run(port).branches if b.name == "solo")
    assert solo.upstream is None
    assert solo.unpushed_commits is None


def test_upstream_is_carried_through_and_unpushed_counted() -> None:
    port = _tier_port(track=">", **{"cherry refs/remotes/origin/main -- feat": ok("- aaa")})
    port._git["rev-list --count origin/feat..feat"] = ok("3")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.upstream == "origin/feat"
    assert feat.unpushed_commits == 3
