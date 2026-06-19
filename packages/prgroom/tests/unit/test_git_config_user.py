from prgroom.git.client import GitCli
from prgroom.proc import CommandResult
from tests.fakes import RecordedRunner


def _ok(stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def test_config_user_returns_name() -> None:
    runner = RecordedRunner([_ok("Scott Hamilton\n")])
    assert GitCli(runner).config_user() == "Scott Hamilton"
    # `--default ""` is load-bearing: an unset key must exit 0 (not 1), or `_run`
    # raises a transient git error before the email fallback can run.
    assert runner.calls[0] == ["git", "config", "--default", "", "user.name"]


def test_config_user_falls_back_to_email_when_name_unset() -> None:
    # An unset user.name returns "" with exit 0 (the `--default ""` contract), so the
    # fallback to user.email is reachable — the bug this guards against was an exit-1
    # unset name that `_run` turned into a transient error, never reaching the fallback.
    runner = RecordedRunner([_ok("\n"), _ok("scott@example.com\n")])
    assert GitCli(runner).config_user() == "scott@example.com"
    assert runner.calls[1] == ["git", "config", "--default", "", "user.email"]
