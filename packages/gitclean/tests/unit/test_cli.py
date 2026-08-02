"""Tests for argument handling, the JSON envelope, and exit codes.

Exit codes are the contract a caller scripts against, so each mode pins one:
0 clean, 1 refused, 2 unusable, 3 acted-but-something-surprised-us."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest
from test_survey import SEP, make_port, ref_line

from gitclean.cli import EXIT_ANOMALY, EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main
from gitclean.ports import ScriptedCommands, fail, ok

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

_OBJECTNAME = 2
"""Field index of `%(objectname)` in the ref format the survey asks git for."""


def ref_at(full: str, short: str, oid: str, **kwargs: str) -> str:
    """A ref line pointing at a commit of its own.

    `ref_line` publishes the same commit for every ref it builds, which is fine
    for the survey -- it reads commits, it does not compare them. The trunk is
    identified partly by the commit it sits on, so a CLI fixture whose refs all
    share one SHA describes a repository containing nothing but the trunk."""
    fields = ref_line(full, short, **kwargs).split(SEP)
    fields[_OBJECTNAME] = oid
    return SEP.join(fields)


def invoke(argv: list[str], port: ScriptedCommands) -> tuple[int, dict[str, object]]:
    buffer = io.StringIO()
    code = main(argv, port=port, now=NOW, out=buffer)
    return code, json.loads(buffer.getvalue())


def invoke_human(argv: list[str], port: ScriptedCommands) -> tuple[int, str]:
    buffer = io.StringIO()
    code = main([*argv, "--format", "human"], port=port, now=NOW, out=buffer)
    return code, buffer.getvalue()


def merged_branch_port() -> ScriptedCommands:
    """A repo with one provably-merged branch and nothing else interesting."""
    return make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/heads/done", "done", "d" * 40),
        ],
        counts={"origin/main..done": "0"},
        extra={
            "branch -D -- done": ok(),
            "for-each-ref --format=%(refname) refs/heads/done": ok(""),
        },
    )


# -- usage -------------------------------------------------------------------


def test_a_mode_is_required() -> None:
    with pytest.raises(SystemExit) as exc:
        main([], port=ScriptedCommands())
    assert exc.value.code == EXIT_USAGE


def test_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--report", "--cleanup"], port=ScriptedCommands())
    assert exc.value.code == EXIT_USAGE


def test_version_prints_and_exits_clean(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"], port=ScriptedCommands())
    assert exc.value.code == EXIT_OK
    assert "gitclean" in capsys.readouterr().out


def test_help_exits_clean(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"], port=ScriptedCommands())
    assert exc.value.code == EXIT_OK
    assert "--cleanup" in capsys.readouterr().out


def test_the_removed_flags_are_gone_rather_than_quietly_ignored() -> None:
    """Each of these used to widen what a run would delete. Accepting them as
    no-ops would let an old command line read as though it still did."""
    for flag in ("--force", "--include-remote", "--idle-days", "--base"):
        with pytest.raises(SystemExit) as exc:
            main(["--report", flag], port=ScriptedCommands())
        assert exc.value.code == EXIT_USAGE, flag


def test_outside_a_repo_is_a_usage_failure_not_a_crash() -> None:
    port = ScriptedCommands(git={"rev-parse --show-toplevel": fail("not a git repository")})
    code, payload = invoke(["--report"], port)
    assert code == EXIT_USAGE
    assert payload["ok"] is False
    assert payload["error"] == "not inside a git repository"


# -- report ------------------------------------------------------------------


def test_report_changes_nothing_and_returns_the_full_state() -> None:
    port = merged_branch_port()
    code, payload = invoke(["--report"], port)
    assert code == EXIT_OK
    assert payload["ok"] is True
    assert payload["mode"] == "report"
    assert payload["execution"] is None
    assert ("git", "branch", "-D", "done") not in port.transcript


def test_report_carries_the_measurements_per_target() -> None:
    port = merged_branch_port()
    _, payload = invoke(["--report"], port)
    targets = payload["targets"]
    assert isinstance(targets, list)
    assert all(
        {"last_activity", "merge_evidence", "sweepable", "withheld"} <= set(t) for t in targets
    )


def test_a_target_left_out_of_the_sweep_says_why_on_its_own_row() -> None:
    """The report is the product for everything the sweep will not touch, so a
    row that just reads `sweepable: false` sends the reader to go and work it
    out for themselves."""
    _, payload = invoke(["--report"], merged_branch_port())
    targets = payload["targets"]
    assert isinstance(targets, list)
    assert all(t["withheld"] for t in targets if not t["sweepable"])


def test_the_summary_counts_the_evidence_and_the_sweepable_subset() -> None:
    _, payload = invoke(["--report"], merged_branch_port())
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["total"] == 3
    assert summary["sweepable_now"] == 1
    evidence = summary["by_merge_evidence"]
    assert isinstance(evidence, dict)
    assert evidence["ancestor"] == 2  # main, and the merged branch
    assert "by_disposition" not in summary
    assert "by_risk" not in summary


def half_measured_port() -> ScriptedCommands:
    """Two worktrees, one statted and one git would not answer for."""
    port = make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/heads/done", "done", "d" * 40),
        ],
        worktrees=(
            f"worktree /repo\nHEAD {'a' * 40}\nbranch refs/heads/main\n"
            f"\n"
            f"worktree /repo/wt\nHEAD {'d' * 40}\nbranch refs/heads/done\n"
        ),
        counts={"origin/main..done": "0"},
    )
    port._git["status --porcelain=v1"] = [ok(""), fail("fatal: cannot open", code=128)]
    return port


def test_an_unanswered_probe_reads_differently_from_a_measured_zero() -> None:
    """A caller parsing the envelope gets null where a count was never taken,
    and the row that count belongs to says so in prose. Silence would render
    the unreadable tree exactly like the empty one."""
    _, payload = invoke(["--report"], half_measured_port())

    repo = payload["repo"]
    assert isinstance(repo, dict)
    worktrees = repo["worktrees"]
    assert isinstance(worktrees, list)
    assert worktrees[0]["ignored_file_count"] == 0
    assert worktrees[1]["ignored_file_count"] is None

    targets = payload["targets"]
    assert isinstance(targets, list)
    row = next(t for t in targets if t["id"] == "worktree:/repo/wt")
    assert any("was not measured" in reason for reason in row["reasons"])
    assert "unknown" in row["withheld"]


def test_the_human_report_states_the_unknown_on_the_row_it_belongs_to() -> None:
    """The top-level warning says a tree could not be read; the row is where a
    reader deciding what to name is looking."""
    _, text = invoke_human(["--report"], half_measured_port())

    assert "could not read the working-tree status of /repo/wt" in text
    body = text.split("worktree:/repo/wt", 1)[1]
    assert "could not read this tree's status" in body
    assert "was not measured" in body


def test_a_degraded_gh_read_is_surfaced_in_the_report() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")], has_gh=False)
    _, payload = invoke(["--report"], port)
    repo = payload["repo"]
    assert isinstance(repo, dict)
    assert repo["gh_available"] is False
    assert repo["gh_error"]


# -- cleanup -----------------------------------------------------------------


def test_a_successful_sweep_exits_clean_and_lists_what_went() -> None:
    code, payload = invoke(["--cleanup"], merged_branch_port())
    assert code == EXIT_OK
    execution = payload["execution"]
    assert isinstance(execution, dict)
    deletions = execution["deletions"]
    assert isinstance(deletions, list)
    assert [d["name"] for d in deletions] == ["done"]
    assert deletions[0]["verified"] is True


def test_the_trunk_survives_a_bare_sweep_although_it_is_an_ancestor() -> None:
    """`main` is an ancestor of `origin/main`, so merge evidence alone would
    hand the trunk to the sweep."""
    port = merged_branch_port()
    _, payload = invoke(["--cleanup"], port)
    assert ("git", "branch", "-D", "--", "main") not in port.transcript
    targets = payload["targets"]
    assert isinstance(targets, list)
    main_row = next(t for t in targets if t["id"] == "branch:main")
    assert main_row["merge_evidence"] == "ancestor"
    assert main_row["sweepable"] is False


def test_naming_the_invoking_worktree_exits_one_with_its_path() -> None:
    port = merged_branch_port()
    code, payload = invoke(["--cleanup", "worktree:/repo"], port)
    assert code == EXIT_REFUSED
    refusal = payload["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_INVOKING_WORKTREE"
    assert "/repo" in refusal["message"]
    assert refusal["remedy"]


def test_an_anomaly_exits_three_with_the_transcript() -> None:
    """Acted, but git surprised us. A caller must be able to tell this from a
    clean run without parsing prose."""
    port = make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/heads/done", "done", "d" * 40),
        ],
        counts={"origin/main..done": "0"},
        extra={
            "branch -D -- done": ok(),
            "for-each-ref --format=%(refname) refs/heads/done": ok("refs/heads/done"),
        },
    )
    code, payload = invoke(["--cleanup"], port)
    assert code == EXIT_ANOMALY
    assert payload["ok"] is False
    execution = payload["execution"]
    assert isinstance(execution, dict)
    anomalies = execution["anomalies"]
    assert isinstance(anomalies, list)
    assert anomalies[0]["transcript"]


def test_dry_run_reports_a_plan_without_touching_anything() -> None:
    port = merged_branch_port()
    code, payload = invoke(["--cleanup", "--dry-run"], port)
    assert code == EXIT_OK
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert plan["dry_run"] is True
    assert ("git", "branch", "-D", "done") not in port.transcript


def test_cleanup_resurveys_rather_than_trusting_an_earlier_report() -> None:
    """The state may have moved since the caller read the report."""
    port = merged_branch_port()
    invoke(["--cleanup", "--dry-run"], port)
    assert [t[1] for t in port.transcript].count("for-each-ref") == 1


def _remote_port() -> ScriptedCommands:
    return make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/remotes/origin/feat/x", "origin/feat/x", "f" * 40),
        ],
        counts={"origin/main..origin/feat/x": "0"},
        # The server still has it. Every route to deleting a server ref asks
        # that first, dry runs included, so a fixture that left it unscripted
        # would only ever exercise the already-gone path.
        extra={"ls-remote": ok(f"{'f' * 40}\trefs/heads/feat/x")},
    )


def test_a_bare_sweep_never_touches_a_server_ref() -> None:
    """A merged remote branch qualifies on evidence and is still left alone:
    deleting it is irreversible for everyone fetching, and the server keeps no
    reflog. It takes an explicit name."""
    port = _remote_port()
    _, payload = invoke(["--cleanup"], port)
    assert not any(call[:2] == ("git", "push") for call in port.transcript)
    targets = payload["targets"]
    assert isinstance(targets, list)
    remote = next(t for t in targets if t["id"] == "remote:origin/feat/x")
    assert remote["merge_proven"] is True
    assert remote["sweepable"] is False
    assert "server" in remote["withheld"]


def test_an_explicit_salvage_dir_is_honoured() -> None:
    _, payload = invoke(
        ["--cleanup", "origin/feat/x", "--dry-run", "--salvage-dir", "/var/salvage/keep"],
        _remote_port(),
    )
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert plan["salvage_dir"] == "/var/salvage/keep"


def test_a_miss_with_no_refs_read_exits_refused_not_clean() -> None:
    """Exit 0 here would report a branch as gone on the strength of a list that
    failed to load. The caller is entitled to know the difference between "it
    is not there" and "I could not look"."""
    port = make_port(extra={"for-each-ref": fail("fatal: bad object"), "branch -D -- done": ok()})

    code, payload = invoke(["--cleanup", "done"], port)

    assert code == EXIT_REFUSED
    refusal = payload["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_SURVEY_INCOMPLETE"
    assert not any(call[:3] == ("git", "branch", "-D") for call in port.transcript)


def test_naming_the_servers_copy_of_the_trunk_exits_refused() -> None:
    """It is on the server and gitclean keeps it out of the target list, so a
    miss says nothing about whether it exists. Exit 0 with `already gone` would
    be a false report about a ref sitting right there."""
    port = make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/remotes/origin/main", "origin/main", "a" * 40),
        ]
    )

    code, payload = invoke(["--cleanup", "origin/main"], port)

    assert code == EXIT_REFUSED
    refusal = payload["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_NOT_A_TARGET"
    assert refusal["remedy"]


def _absent_remote_port() -> ScriptedCommands:
    """The tracking ref is here and the server's copy is not, which is what a
    forge that deletes merged branches leaves behind."""
    return make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/remotes/origin/feat/x", "origin/feat/x", "f" * 40),
        ],
        counts={"origin/main..origin/feat/x": "0"},
        extra={"ls-remote": ok("")},
    )


def test_naming_something_already_gone_is_a_clean_exit() -> None:
    """Exit 1 here is the failure that matters: an agent that correctly leaves
    a worktree before cleaning it up, then names it, is told the run refused
    and reaches for raw git or escalates over a job already done."""
    code, payload = invoke(["--cleanup", "not-a-thing"], merged_branch_port())
    assert code == EXIT_OK
    assert payload["refusal"] is None
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert [a["selector"] for a in plan["absent"]] == ["not-a-thing"]


def test_an_absent_name_does_not_take_the_names_beside_it_down() -> None:
    """A selector refusal is plan-level, so before this the one name that had
    already been dealt with aborted every other deletion in the command."""
    code, payload = invoke(["--cleanup", "done", "not-a-thing"], merged_branch_port())
    assert code == EXIT_OK
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert [d["name"] for d in execution["deletions"]] == ["done"]
    assert execution["deletions"][0]["deleted"] is True


def test_a_server_ref_already_gone_exits_clean_rather_than_anomalous() -> None:
    """Exit 3 says something is wrong and needs reading. Spending it on the
    ordinary outcome of a forge that tidies up after itself teaches a reader to
    skip the code that was supposed to stop them."""
    code, payload = invoke(["--cleanup", "origin/feat/x"], _absent_remote_port())
    assert code == EXIT_OK
    execution = payload["execution"]
    assert isinstance(execution, dict)
    assert execution["anomalies"] == []
    assert execution["deletions"][0]["already_absent"] is True


# -- human rendering ---------------------------------------------------------


def test_human_output_names_what_it_could_not_find() -> None:
    """Not an error, and not silence either. A name matching nothing is also
    exactly what a typo looks like from in here, and the reader is the only one
    who can tell the two apart -- so the name goes on the page for them."""
    code, text = invoke_human(["--cleanup", "not-a-thing"], merged_branch_port())
    assert code == EXIT_OK
    assert "ABSENT" in text
    assert "not-a-thing" in text


def test_human_output_does_not_mark_an_already_gone_ref_as_deleted() -> None:
    """`ok` is the mark for a deletion this run performed and verified. Reusing
    it here would put a cleanup that did nothing and one that did the work on
    the same line."""
    code, text = invoke_human(["--cleanup", "origin/feat/x"], _absent_remote_port())
    assert code == EXIT_OK
    assert "gone origin/feat/x" in text
    assert "ok   origin/feat/x" not in text


def test_human_report_marks_the_sweepable_rows_and_shows_the_evidence() -> None:
    code, text = invoke_human(["--report"], merged_branch_port())
    assert code == EXIT_OK
    assert "repo:" in text
    assert "[sweep]" in text
    assert "[hold ]" in text
    assert "merge proven by" in text
    assert "not swept:" in text
    assert "sweepable now:" in text


def test_human_dry_run_is_not_rendered_as_failure() -> None:
    """A dry run leaves every deletion unverified by construction; showing
    FAIL would teach the reader to distrust a clean preview."""
    _, text = invoke_human(["--cleanup", "--dry-run"], merged_branch_port())
    assert "plan done" in text
    assert "FAIL" not in text


def test_human_output_names_a_failed_deletion() -> None:
    port = make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/heads/done", "done", "d" * 40),
        ],
        counts={"origin/main..done": "0"},
        extra={
            "branch -D -- done": ok(),
            "for-each-ref --format=%(refname) refs/heads/done": ok("refs/heads/done"),
        },
    )
    _, text = invoke_human(["--cleanup"], port)
    assert "FAIL" in text
    assert "ANOMALY" in text


def test_human_refusal_names_the_code_and_the_remedy() -> None:
    _, text = invoke_human(["--cleanup", "worktree:/repo"], merged_branch_port())
    assert "REFUSED (E_INVOKING_WORKTREE)" in text
    assert "remedy:" in text


def test_human_output_names_a_skipped_target() -> None:
    port = make_port(
        refs=[
            ref_at("refs/heads/main", "main", "a" * 40, head="*"),
            ref_at("refs/heads/held", "held", "h" * 40),
        ],
        worktrees=(
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n"
            "\n"
            "worktree /repo/wt\nHEAD hhh\nbranch refs/heads/held\nlocked\n"
        ),
        counts={"origin/main..held": "0"},
    )
    _, text = invoke_human(["--cleanup", "--dry-run"], port)
    assert "SKIPPED held" in text


def test_human_output_warns_when_gh_is_unavailable() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")], has_gh=False)
    _, text = invoke_human(["--report"], port)
    assert "WARN:" in text
