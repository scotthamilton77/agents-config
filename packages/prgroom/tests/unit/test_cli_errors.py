"""Tests for the CLI's structured-error handling (§1, §7.6).

When a verb raises a tier-tagged error, the CLI must render the registry's
``what/why/how`` block to stderr — plus the underlying ``detail`` for runtime
errors — and exit with the tier's documented sysexits code. The fail-fast,
user-resolvable errors (auth, push-rejected, git-terminal) get the *richest*
telemetry, not the least. These pin that behavior at the handler boundary.
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


def test_non_precondition_error_renders_block_and_returns_tier_code() -> None:
    stderr = io.StringIO()
    err = PrgroomError(tier=Tier.STATE_CORRUPT, code=ErrorCode.STATE_CORRUPT)
    code = handle_cli_error(err, stderr=stderr)
    assert code == 78  # EX_CONFIG
    rendered = stderr.getvalue()
    assert "error: STATE_CORRUPT" in rendered
    assert "what:" in rendered  # runtime/state errors now carry the registry guidance
    assert "how:" in rendered
    assert "detail:" not in rendered  # no detail string was supplied


def test_runtime_terminal_error_surfaces_its_detail() -> None:
    # The fail-fast class a human must resolve: the underlying gh/git stderr MUST
    # reach the operator, not be dropped behind a bare `error: <CODE>`.
    stderr = io.StringIO()
    err = PrgroomError(
        tier=Tier.RUNTIME_TERMINAL_USER,
        code=ErrorCode.RUNTIME_GH_TERMINAL,
        detail="HTTP 401: Bad credentials",
    )
    code = handle_cli_error(err, stderr=stderr)
    assert code == 77  # EX_NOPERM
    rendered = stderr.getvalue()
    assert "error: RUNTIME_GH_TERMINAL" in rendered
    assert "how:" in rendered  # registry guidance (reconfigure the gh token)...
    assert "HTTP 401: Bad credentials" in rendered  # ...AND the raw failure detail


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
