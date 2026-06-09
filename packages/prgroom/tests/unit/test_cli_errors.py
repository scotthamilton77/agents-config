"""Tests for the CLI's structured-error handling (§1, §7.6).

When a verb raises a tier-tagged error, the CLI must render the registry's
4-line ``what/why/how`` block to stderr (for PreconditionError) or a one-line
code (for other tiers) and exit with the tier's documented sysexits code. These
pin that behavior at the handler boundary — the "CLI catching PreconditionError
and formatting the block with the right registry code" path from §7.6.
"""

from __future__ import annotations

import io

import pytest

from prgroom import cli
from prgroom.cli import handle_cli_error, main
from prgroom.errors import ErrorCode, PreconditionError, PrgroomError, Tier


def test_precondition_error_renders_block_and_returns_usage_code() -> None:
    stderr = io.StringIO()
    code = handle_cli_error(PreconditionError(ErrorCode.PRECONDITION_NO_PR_DETECTED), stderr=stderr)
    assert code == 2  # PRECONDITION_USER_ERROR -> EX_USAGE
    rendered = stderr.getvalue()
    assert "error: PRECONDITION_NO_PR_DETECTED" in rendered
    assert "what:" in rendered
    assert "how:" in rendered


def test_no_work_precondition_returns_zero() -> None:
    stderr = io.StringIO()
    code = handle_cli_error(PreconditionError(ErrorCode.PRECONDITION_NO_ITEMS), stderr=stderr)
    assert code == 0  # success-no-op


def test_non_precondition_error_returns_tier_code_with_one_line() -> None:
    stderr = io.StringIO()
    err = PrgroomError(tier=Tier.STATE_CORRUPT, code=ErrorCode.STATE_CORRUPT)
    code = handle_cli_error(err, stderr=stderr)
    assert code == 78  # EX_CONFIG
    assert "STATE_CORRUPT" in stderr.getvalue()


def test_main_converts_a_raised_prgroom_error_into_a_system_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # main() must catch a tier-tagged error from the app and exit with its code,
    # not surface an uncaught traceback. Stub the app to raise one.
    def _boom() -> None:
        raise PreconditionError(ErrorCode.PRECONDITION_NO_PR_DETECTED)

    monkeypatch.setattr(cli, "app", _boom)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
