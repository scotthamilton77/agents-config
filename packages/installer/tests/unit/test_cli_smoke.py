import pytest

from installer.cli import main


def test_main_returns_zero_with_no_args() -> None:
    assert main([]) == 0


def test_main_help_exits_with_status_zero() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_main_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "installer" in captured.out
