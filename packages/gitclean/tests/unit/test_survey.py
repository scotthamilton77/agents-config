"""Tests for the read pass: parsing, and the tiered merge proof."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from gitclean.model import MergeEvidence, Survey
from gitclean.ports import CommandResult, ScriptedCommands, fail, ok
from gitclean.survey import (
    idle_since,
    read_pull_requests,
    read_worktrees,
    resolve_base_ref,
    resolve_default_branch,
    resolve_repo,
    survey,
)

SEP = "\x1f"
NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def ref_line(
    full: str,
    short: str,
    *,
    committed: str = "2026-07-20T00:00:00+00:00",
    upstream: str = "",
    head: str = "",
) -> str:
    return SEP.join([full, short, "a" * 40, committed, upstream, head])


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
) -> ScriptedCommands:
    table: dict[str, CommandResult] = {
        "rev-parse --show-toplevel": ok("/repo"),
        "rev-parse --path-format=absolute --git-common-dir": ok("/repo/.git"),
        "symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/main"),
        "show-ref --verify --quiet refs/remotes/origin/main": ok(),
        "rev-parse --abbrev-ref HEAD": ok("main"),
        "worktree list --porcelain": ok(worktrees),
        "status --porcelain=v1 --untracked-files=normal": ok(""),
        "for-each-ref": ok("\n".join(refs or [])),
        "branch --merged": ok(local_merged),
        "branch -r --merged": ok(remote_merged),
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


def test_explicit_base_override_wins() -> None:
    port = ScriptedCommands()
    assert resolve_default_branch(port, None, "develop") == "develop"


def test_default_branch_comes_from_origins_published_head() -> None:
    port = ScriptedCommands(
        git={"symbolic-ref --quiet refs/remotes/origin/HEAD": ok("refs/remotes/origin/trunk")}
    )
    assert resolve_default_branch(port, None, None) == "trunk"


def test_default_branch_falls_back_to_master_when_main_is_absent() -> None:
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail(),
            "show-ref --verify --quiet refs/heads/main": fail(),
            "show-ref --verify --quiet refs/heads/master": ok(),
        }
    )
    assert resolve_default_branch(port, None, None) == "master"


def test_default_branch_settles_on_main_when_nothing_answers() -> None:
    port = ScriptedCommands(
        git={
            "symbolic-ref --quiet refs/remotes/origin/HEAD": fail(),
            "show-ref --verify --quiet refs/heads/": fail(),
        }
    )
    assert resolve_default_branch(port, None, None) == "main"


def test_base_prefers_the_remote_tracking_tip() -> None:
    """A stale local default branch would under-report merges."""
    port = ScriptedCommands(git={"show-ref --verify --quiet refs/remotes/origin/main": ok()})
    assert resolve_base_ref(port, None, "main") == "origin/main"


def test_base_falls_back_to_the_local_branch_without_a_remote() -> None:
    port = ScriptedCommands(git={"show-ref --verify --quiet refs/remotes/origin/main": fail()})
    assert resolve_base_ref(port, None, "main") == "main"


# -- worktree parsing --------------------------------------------------------


def test_worktree_porcelain_blocks_are_parsed() -> None:
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok(
                "worktree /repo\nHEAD aaa\nbranch refs/heads/main\n"
                "\n"
                "worktree /repo/wt\nHEAD bbb\nbranch refs/heads/feat\nlocked\n"
                "\n"
                "worktree /repo/gone\nHEAD ccc\ndetached\nprunable gitdir file removed\n"
            ),
            "status --porcelain=v1 --untracked-files=normal": ok(""),
        }
    )
    worktrees, warnings = read_worktrees(port, None)
    assert warnings == []
    assert [w.path for w in worktrees] == ["/repo", "/repo/wt", "/repo/gone"]
    assert worktrees[0].is_main and worktrees[0].branch == "main"
    assert worktrees[1].locked
    assert worktrees[2].prunable and worktrees[2].branch is None


def test_a_worktree_block_without_a_path_is_warned_not_dropped_silently() -> None:
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok("HEAD aaa\nbranch refs/heads/x\n"),
            "status --porcelain=v1 --untracked-files=normal": ok(""),
        }
    )
    worktrees, warnings = read_worktrees(port, None)
    assert worktrees == []
    assert warnings and "no path" in warnings[0]


def test_dirty_and_untracked_files_are_counted_separately() -> None:
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok("worktree /repo\n"),
            "status --porcelain=v1 --untracked-files=normal": ok(
                " M a.txt\nA  b.txt\n?? c.txt\n?? d.txt\n"
            ),
        }
    )
    worktrees, _ = read_worktrees(port, None)
    assert worktrees[0].dirty_file_count == 2
    assert worktrees[0].untracked_file_count == 4 - 2
    assert worktrees[0].dirty


def test_a_worktree_git_cannot_stat_is_unknown_not_clean() -> None:
    """The dangerous default. `dirty=False` here would send an unreadable tree
    -- the one most likely to be holding something -- into the sweep at
    Risk.NONE with no salvage."""
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok("worktree /repo/opaque\n"),
            "status --porcelain=v1 --untracked-files=normal": fail("no such directory"),
        }
    )
    worktrees, warnings = read_worktrees(port, None)
    assert worktrees[0].dirty is None
    assert worktrees[0].dirty_file_count is None
    assert worktrees[0].untracked_file_count is None
    assert any("could not read the working-tree status" in w for w in warnings)


def test_a_prunable_worktree_is_not_probed_for_dirt() -> None:
    """Its directory is gone by definition, so a failed stat there is an
    expected fact, not an unknown -- probing would manufacture a warning."""
    port = ScriptedCommands(
        git={
            "worktree list --porcelain": ok("worktree /repo/gone\nprunable gitdir file removed\n"),
        }
    )
    worktrees, warnings = read_worktrees(port, None)
    assert worktrees[0].dirty is False
    assert warnings == []
    assert "status" not in [t[1] for t in port.transcript]


def test_unlistable_worktrees_are_reported() -> None:
    port = ScriptedCommands(git={"worktree list --porcelain": fail("boom")})
    worktrees, warnings = read_worktrees(port, None)
    assert worktrees == []
    assert warnings


# -- pull requests -----------------------------------------------------------


def test_missing_gh_is_reported_as_a_limit_on_the_evidence() -> None:
    """Without gh there is no squash-merge signal at all, so this must never
    be swallowed."""
    port = ScriptedCommands(has_gh=False)
    prs, error = read_pull_requests(port, None)
    assert prs == {}
    assert error is not None and "squash" in error


def test_a_failing_gh_call_is_reported() -> None:
    port = ScriptedCommands(gh={"pr list": fail("no git remotes found")}, has_gh=True)
    _, error = read_pull_requests(port, None)
    assert error is not None and "no git remotes found" in error


def test_unparseable_gh_json_is_reported() -> None:
    port = ScriptedCommands(gh={"pr list": ok("{{{not json")}, has_gh=True)
    _, error = read_pull_requests(port, None)
    assert error is not None and "unparseable" in error


def test_a_non_list_gh_payload_is_reported() -> None:
    port = ScriptedCommands(gh={"pr list": ok('{"unexpected": true}')}, has_gh=True)
    _, error = read_pull_requests(port, None)
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
    prs, _ = read_pull_requests(port, None)
    assert prs["feat/x"].number == 2


def test_malformed_pr_entries_are_skipped() -> None:
    payload = json.dumps(["not a dict", {"number": 3, "state": "OPEN", "headRefName": ""}])
    port = ScriptedCommands(gh={"pr list": ok(payload)}, has_gh=True)
    prs, _ = read_pull_requests(port, None)
    assert prs == {}


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


def test_remote_refs_are_identified_by_prefix_not_by_a_slash() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/team/feat", "team/feat"),
            ref_line("refs/remotes/origin/feat", "origin/feat"),
        ],
        counts={
            "origin/main..team/feat": "1",
            "origin/main..origin/feat": "1",
        },
        extra={
            "cherry origin/main team/feat": ok("+ abc"),
            "cherry origin/main origin/feat": ok("+ abc"),
            "merge-base origin/main": ok("base1"),
            "rev-parse team/feat^{tree}": ok("tree1"),
            "rev-parse origin/feat^{tree}": ok("tree2"),
            "commit-tree": ok("synth"),
            "cherry origin/main synth": ok("+ zzz"),
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


def test_the_default_branch_is_surveyed_without_probing_itself() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")])
    main = run(port).branches[0]
    assert main.is_default and main.merged
    assert "rev-list" not in [t[1] for t in port.transcript]


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


def test_a_failed_batch_ancestry_check_is_warned_not_swallowed() -> None:
    """Failure here only loses the cheap tier -- the per-branch probes still
    answer -- so it degrades speed, not safety. It is still reported."""
    port = _tier_port(**{"cherry origin/main feat": ok("- aaa")})
    port._git["branch --merged"] = fail("boom")
    result = run(port)
    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.PATCH_EQUAL
    assert any("batch ancestry check for local branches" in w for w in result.warnings)


# -- the merge tiers ---------------------------------------------------------


def _tier_port(**extra: CommandResult) -> ScriptedCommands:
    return make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat", upstream="origin/feat"),
        ],
        counts={"origin/main..feat": "2", "origin/feat..feat": "0"},
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
        counts={"origin/main..feat": "2"},
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
        counts={"origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("not an ancestor"),
            "cherry origin/main feat": ok("+ aaa"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("+ synthsha"),
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
        counts={"origin/main..feat": "2"},
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
        counts={"origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="")],
        extra={
            "cherry origin/main feat": ok("+ aaa"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("+ synthsha"),
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
        counts={"origin/main..feat": "2"},
        prs=[_pr("MERGED", oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("not an ancestor"),
            "cherry origin/main feat": ok("+ aaa"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("- synthsha"),
        },
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.SQUASH_EQUAL


def test_ancestry_settles_a_branch_with_nothing_ahead() -> None:
    port = _tier_port()
    port._git["rev-list --count origin/main..feat"] = ok("0")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.ANCESTOR


def test_a_closed_pr_is_recorded_as_a_discard_not_a_merge() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/feat", "feat"),
        ],
        counts={"origin/main..feat": "2"},
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
        counts={"origin/main..feat": "2"},
        prs=[_pr("CLOSED", number=9, oid="b" * 40)],
        extra={
            "merge-base --is-ancestor": fail("not an ancestor"),
            "cherry origin/main feat": ok("+ aaa"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("+ synthsha"),
        },
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merge_evidence is MergeEvidence.NONE


def test_patch_equivalence_catches_rebased_and_cherry_picked_work() -> None:
    port = _tier_port(**{"cherry origin/main feat": ok("- aaa\n- bbb")})
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.PATCH_EQUAL


def test_squash_merges_are_caught_by_replaying_the_tree_as_one_commit() -> None:
    """Nothing cheaper detects this: the squashed commit shares no patch-id
    with any individual branch commit, and the tip is nobody's ancestor."""
    port = _tier_port(
        **{
            "cherry origin/main feat": ok("+ aaa\n+ bbb"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("- synthsha"),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.merged and feat.merge_evidence is MergeEvidence.SQUASH_EQUAL


def test_a_genuinely_unmerged_branch_proves_nothing() -> None:
    port = _tier_port(
        **{
            "cherry origin/main feat": ok("+ aaa"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("+ synthsha"),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert not feat.merged and feat.merge_evidence is MergeEvidence.NONE


def test_squash_probe_gives_up_cleanly_when_git_will_not_answer() -> None:
    for broken in (
        {"merge-base origin/main feat": fail("no merge base")},
        {"rev-parse feat^{tree}": fail("bad object")},
        {"commit-tree": fail("cannot write")},
    ):
        port = _tier_port(
            **{
                "cherry origin/main feat": ok("+ aaa"),
                "merge-base origin/main feat": ok("basesha"),
                "rev-parse feat^{tree}": ok("treesha"),
                "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
                "cherry origin/main synthsha": ok("+ x"),
                **broken,
            }
        )
        feat = next(b for b in run(port).branches if b.name == "feat")
        assert feat.merge_evidence is MergeEvidence.NONE


def test_an_empty_cherry_result_does_not_count_as_merged() -> None:
    """No output means the question was not answered, not that everything is
    already upstream."""
    port = _tier_port(
        **{
            "cherry origin/main feat": ok(""),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok(""),
        }
    )
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert not feat.merged


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


def test_a_detached_head_is_reported_as_no_current_branch() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main")])
    port._git["rev-parse --abbrev-ref HEAD"] = ok("HEAD")
    assert run(port).current_branch is None


def test_a_base_override_is_used_verbatim() -> None:
    port = make_port(refs=[ref_line("refs/heads/develop", "develop", head="*")])
    result = run(port, base_override="develop")
    assert result.base_ref == "develop"
    assert result.default_branch == "develop"


def test_counts_that_are_not_numbers_are_unknown_not_zero() -> None:
    port = _tier_port(**{"cherry origin/main feat": ok("- aaa")})
    port._git["rev-list --count origin/main..feat"] = ok("not-a-number")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.unmerged_commits is None


def test_a_failing_rev_list_is_unknown_and_never_proves_a_merge() -> None:
    """Zero here would read as 'nothing ahead of base', which resolves to
    ANCESTOR -- proof of a merge -- so one transient git failure would
    authorise deleting the very branch it failed on."""
    port = _tier_port(
        **{
            "cherry origin/main feat": ok("+ aaa"),
            "merge-base origin/main feat": ok("basesha"),
            "rev-parse feat^{tree}": ok("treesha"),
            "commit-tree treesha -p basesha -m gitclean-probe": ok("synthsha"),
            "cherry origin/main synthsha": ok("+ synthsha"),
        }
    )
    port._git["rev-list --count origin/main..feat"] = fail("bad revision")
    result = run(port)
    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.unmerged_commits is None
    assert not feat.merged
    assert feat.merge_evidence is not MergeEvidence.ANCESTOR
    assert any("could not count the commits on feat" in w for w in result.warnings)


def test_a_failing_unpushed_count_is_unknown_and_warned() -> None:
    port = _tier_port(**{"cherry origin/main feat": ok("- aaa")})
    port._git["rev-list --count origin/feat..feat"] = fail("bad revision")
    result = run(port)
    feat = next(b for b in result.branches if b.name == "feat")
    assert feat.unpushed_commits is None
    assert any("missing from origin/feat" in w for w in result.warnings)


def test_a_branch_with_no_upstream_has_no_unpushed_count() -> None:
    """Zero would claim 'fully pushed' for a branch that was never pushed."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/solo", "solo"),
        ],
        counts={"origin/main..solo": "2"},
        extra={
            "cherry origin/main solo": ok("- aaa"),
        },
    )
    solo = next(b for b in run(port).branches if b.name == "solo")
    assert solo.upstream is None
    assert solo.unpushed_commits is None


def test_upstream_is_carried_through_and_unpushed_counted() -> None:
    port = _tier_port(**{"cherry origin/main feat": ok("- aaa")})
    port._git["rev-list --count origin/feat..feat"] = ok("3")
    feat = next(b for b in run(port).branches if b.name == "feat")
    assert feat.upstream == "origin/feat"
    assert feat.unpushed_commits == 3


# -- idle window -------------------------------------------------------------


def test_idle_since_measures_against_the_window() -> None:
    window = timedelta(days=14)
    assert idle_since("2026-07-01T00:00:00+00:00", NOW, window)
    assert not idle_since("2026-07-24T00:00:00+00:00", NOW, window)


def test_an_unknown_timestamp_is_never_evidence_for_deletion() -> None:
    window = timedelta(days=14)
    assert not idle_since(None, NOW, window)
    assert not idle_since("", NOW, window)
    assert not idle_since("last tuesday", NOW, window)


def test_a_naive_timestamp_is_read_as_utc_rather_than_rejected() -> None:
    assert idle_since("2026-01-01T00:00:00", NOW, timedelta(days=14))
