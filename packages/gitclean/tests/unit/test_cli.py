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


# -- human rendering ---------------------------------------------------------


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
