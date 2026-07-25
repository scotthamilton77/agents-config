"""Tests for argument handling, the JSON envelope, and exit codes.

Exit codes are the contract a caller scripts against, so each mode pins one:
0 clean, 1 refused, 2 unusable, 3 acted-but-something-surprised-us."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest
from test_survey import make_port, ref_line

from gitclean.cli import EXIT_ANOMALY, EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main
from gitclean.ports import ScriptedCommands, fail, ok

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def invoke(argv: list[str], port: ScriptedCommands) -> tuple[int, dict[str, object]]:
    buffer = io.StringIO()
    code = main(argv, port=port, now=NOW, out=buffer)
    return code, json.loads(buffer.getvalue())


def invoke_human(argv: list[str], port: ScriptedCommands) -> tuple[int, str]:
    buffer = io.StringIO()
    code = main([*argv, "--format", "human"], port=port, now=NOW, out=buffer)
    return code, buffer.getvalue()


def merged_branch_port() -> ScriptedCommands:
    """A repo with one safely-deletable branch and nothing else interesting."""
    return make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/done", "done"),
        ],
        counts={"origin/main..done": "0"},
        extra={
            "branch -D done": ok(),
            "show-ref --verify --quiet refs/heads/done": fail(),
        },
    )


# -- usage -------------------------------------------------------------------


def test_a_mode_is_required() -> None:
    with pytest.raises(SystemExit) as exc:
        main([], port=ScriptedCommands())
    assert exc.value.code == EXIT_USAGE


def test_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--report", "--clean-all"], port=ScriptedCommands())
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


def test_report_carries_last_activity_per_target() -> None:
    port = merged_branch_port()
    _, payload = invoke(["--report"], port)
    targets = payload["targets"]
    assert isinstance(targets, list)
    assert all("last_activity" in t for t in targets)


def test_the_summary_counts_both_verdicts_and_the_sweepable_subset() -> None:
    _, payload = invoke(["--report"], merged_branch_port())
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["total"] == 3
    assert summary["sweepable_now"] == 1
    assert isinstance(summary["by_disposition"], dict)
    assert isinstance(summary["by_risk"], dict)


def test_a_degraded_gh_read_is_surfaced_in_the_report() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")], has_gh=False)
    _, payload = invoke(["--report"], port)
    repo = payload["repo"]
    assert isinstance(repo, dict)
    assert repo["gh_available"] is False
    assert repo["gh_error"]


def test_idle_days_reaches_the_classifier() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/old", "old", committed="2026-07-15T00:00:00+00:00"),
        ],
        counts={"origin/main..old": "2"},
        extra={
            "cherry origin/main old": ok("+ a"),
            "merge-base origin/main old": ok("b"),
            "rev-parse old^{tree}": ok("t"),
            "commit-tree t -p b -m gitclean-probe": ok("s"),
            "cherry origin/main s": ok("+ s"),
        },
    )
    _, wide = invoke(["--report", "--idle-days", "30"], port)
    port2 = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/old", "old", committed="2026-07-15T00:00:00+00:00"),
        ],
        counts={"origin/main..old": "2"},
        extra={
            "cherry origin/main old": ok("+ a"),
            "merge-base origin/main old": ok("b"),
            "rev-parse old^{tree}": ok("t"),
            "commit-tree t -p b -m gitclean-probe": ok("s"),
            "cherry origin/main s": ok("+ s"),
        },
    )
    _, narrow = invoke(["--report", "--idle-days", "5"], port2)

    def disposition(payload: dict[str, object]) -> str:
        targets = payload["targets"]
        assert isinstance(targets, list)
        return next(t["disposition"] for t in targets if t["name"] == "old")

    assert disposition(wide) == "active"
    assert disposition(narrow) == "abandoned"


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


def test_a_refusal_exits_one_and_carries_the_remedy() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")])
    code, payload = invoke(["--clean-all"], port)
    assert code == EXIT_REFUSED
    refusal = payload["refusal"]
    assert isinstance(refusal, dict)
    assert refusal["code"] == "E_CLEAN_ALL_REQUIRES_FORCE"
    assert refusal["remedy"]


def test_an_anomaly_exits_three_with_the_transcript() -> None:
    """Acted, but git surprised us. A caller must be able to tell this from a
    clean run without parsing prose."""
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/done", "done"),
        ],
        counts={"origin/main..done": "0"},
        extra={
            "branch -D done": ok(),
            "show-ref --verify --quiet refs/heads/done": ok(),
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


def test_an_explicit_salvage_dir_is_honoured() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/wip", "wip"),
        ],
        counts={"origin/main..wip": "2"},
        extra={
            "cherry origin/main wip": ok("+ a"),
            "merge-base origin/main wip": ok("b"),
            "rev-parse wip^{tree}": ok("t"),
            "commit-tree t -p b -m gitclean-probe": ok("s"),
            "cherry origin/main s": ok("+ s"),
        },
    )
    _, payload = invoke(
        ["--cleanup", "wip", "--force", "--dry-run", "--salvage-dir", "/var/salvage/keep"], port
    )
    plan = payload["plan"]
    assert isinstance(plan, dict)
    assert plan["salvage_dir"] == "/var/salvage/keep"


# -- human rendering ---------------------------------------------------------


def test_human_report_shows_both_verdicts_and_the_reasons() -> None:
    code, text = invoke_human(["--report"], merged_branch_port())
    assert code == EXIT_OK
    assert "repo:" in text
    assert "[safe" in text
    assert "merge proven by" in text
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
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/done", "done"),
        ],
        counts={"origin/main..done": "0"},
        extra={
            "branch -D done": ok(),
            "show-ref --verify --quiet refs/heads/done": ok(),
        },
    )
    _, text = invoke_human(["--cleanup"], port)
    assert "FAIL" in text
    assert "ANOMALY" in text


def test_human_refusal_names_the_code_and_the_remedy() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")])
    _, text = invoke_human(["--clean-all"], port)
    assert "REFUSED (E_CLEAN_ALL_REQUIRES_FORCE)" in text
    assert "remedy:" in text


def test_human_output_names_a_skipped_target() -> None:
    port = make_port(
        refs=[
            ref_line("refs/heads/main", "main", head="*"),
            ref_line("refs/heads/held", "held"),
        ],
        worktrees=(
            "worktree /repo\nHEAD abc\nbranch refs/heads/main\n"
            "\n"
            "worktree /repo/wt\nHEAD def\nbranch refs/heads/held\nlocked\n"
        ),
        counts={"origin/main..held": "0"},
    )
    _, text = invoke_human(["--cleanup", "--dry-run"], port)
    assert "SKIPPED held" in text


def test_human_output_warns_when_gh_is_unavailable() -> None:
    port = make_port(refs=[ref_line("refs/heads/main", "main", head="*")], has_gh=False)
    _, text = invoke_human(["--report"], port)
    assert "WARN:" in text
