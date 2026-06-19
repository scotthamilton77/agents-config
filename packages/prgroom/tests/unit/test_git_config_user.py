from prgroom.git.client import GitCli
from prgroom.proc import CommandResult
from tests.fakes import RecordedRunner


def _ok(stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def test_config_user_returns_name() -> None:
    runner = RecordedRunner([_ok("Scott Hamilton\n")])
    assert GitCli(runner).config_user() == "Scott Hamilton"
    assert runner.calls[0] == ["git", "config", "user.name"]


def test_config_user_falls_back_to_email() -> None:
    runner = RecordedRunner([_ok("\n"), _ok("scott@example.com\n")])
    assert GitCli(runner).config_user() == "scott@example.com"
    assert runner.calls[1] == ["git", "config", "user.email"]
