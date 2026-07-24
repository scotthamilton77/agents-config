"""`sync` — ordered dolt commit+push, or `--pull`.

Default mode is commit-then-push, in that exact order (a dolt commit failing
with "nothing to commit" is still success -- idempotent sync, still
pushes). `--pull` runs `bd dolt pull` alone; a dirty-working-set stderr maps
to the named `E_SYNC_BEHIND` rather than a generic drift alarm.
"""

from __future__ import annotations

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

_OK = BdResult(returncode=0, stdout="", stderr="")


def test_sync_default_commits_then_pushes_in_order():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("dolt", "commit"), _OK),
            ScriptedStep(("dolt", "push"), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["sync"], runner)

    assert exit_code == 0
    assert envelope["data"] == {"synced": True, "mode": "push"}
    assert runner.calls == [("dolt", "commit"), ("dolt", "push")]


def test_sync_commit_nothing_to_commit_stderr_still_pushes_and_succeeds():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("dolt", "commit"),
                BdResult(returncode=1, stdout="", stderr="nothing to commit\n"),
            ),
            ScriptedStep(("dolt", "push"), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["sync"], runner)

    assert exit_code == 0
    assert envelope["ok"] is True
    assert envelope["data"] == {"synced": True, "mode": "push"}
    assert runner.calls == [("dolt", "commit"), ("dolt", "push")]


def test_sync_push_failure_with_unrecognized_stderr_yields_backend_drift():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("dolt", "commit"), _OK),
            ScriptedStep(("dolt", "push"), BdResult(returncode=1, stdout="", stderr="boom")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["sync"], runner)

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.BACKEND_DRIFT)


def test_sync_pull_with_dirty_working_set_yields_sync_behind():
    exit_code, envelope, _ = run_cli(
        ["sync", "--pull"],
        steps=[
            ScriptedStep(
                ("dolt", "pull"),
                BdResult(
                    returncode=1,
                    stdout="",
                    stderr="cannot merge with uncommitted changes\n",
                ),
            )
        ],
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.SYNC_BEHIND)


def test_sync_pull_clean_succeeds_with_pull_mode():
    exit_code, envelope, _ = run_cli(
        ["sync", "--pull"],
        steps=[ScriptedStep(("dolt", "pull"), _OK)],
    )

    assert exit_code == 0
    assert envelope["data"] == {"synced": True, "mode": "pull"}
