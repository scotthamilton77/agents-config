from prgroom.errors import (
    BlockingErrorCodes,
    ErrorCode,
    PreconditionError,
    Tier,
    exit_code_for_tier,
)


def test_new_codes_are_user_error_tier_exit_2() -> None:
    for code in (
        ErrorCode.PRECONDITION_FIXED_NEEDS_COMMITS,
        ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED,
    ):
        assert code.precondition_tier() is Tier.PRECONDITION_USER_ERROR
        err = PreconditionError(code, detail="x")
        assert exit_code_for_tier(err) == 2


def test_new_codes_render_registry_block() -> None:
    err = PreconditionError(ErrorCode.PRECONDITION_FIXED_NEEDS_COMMITS, detail="needs --commits")
    text = err.render()
    assert "PRECONDITION_FIXED_NEEDS_COMMITS" in text
    assert "needs --commits" in text


def test_new_codes_not_blocking() -> None:
    assert ErrorCode.PRECONDITION_FIXED_NEEDS_COMMITS not in BlockingErrorCodes
    assert ErrorCode.PRECONDITION_ITEM_NOT_ESCALATED not in BlockingErrorCodes
