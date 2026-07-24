"""The always-on surface budget (S3-C, charter D16 / AC1)."""

from __future__ import annotations

from installer.core.surface_budget import (
    ALWAYS_ON_TOKEN_CAP,
    SKILL_BODY_TOKEN_CAP,
    always_on_violations,
    approx_tokens,
    skill_body_violations,
)


def test_approx_tokens_is_ceil_of_bytes_over_four() -> None:
    assert approx_tokens(b"") == 0
    assert approx_tokens(b"a") == 1  # ceil(1/4)
    assert approx_tokens(b"abcd") == 1
    assert approx_tokens(b"abcde") == 2  # ceil(5/4)
    assert approx_tokens("abcd") == 1


def test_zero_base_surface_passes() -> None:
    # ~1670 bytes ≈ 418 tokens, far under the cap.
    assert always_on_violations(tool="claude", instruction=b"x" * 1670, rules=[]) == []


def test_boundary_at_cap_passes_and_one_over_fails() -> None:
    at_cap = b"x" * (ALWAYS_ON_TOKEN_CAP * 4)  # exactly 10_000 tokens
    assert always_on_violations(tool="claude", instruction=at_cap, rules=[]) == []
    over = b"x" * (ALWAYS_ON_TOKEN_CAP * 4 + 1)  # 10_001 tokens (ceil)
    violations = always_on_violations(tool="claude", instruction=over, rules=[])
    assert len(violations) == 1
    assert "claude" in violations[0]
    assert str(ALWAYS_ON_TOKEN_CAP) in violations[0]


def test_rules_count_toward_always_on_surface() -> None:
    half = b"x" * (ALWAYS_ON_TOKEN_CAP * 2)  # 5_000 tokens each
    violations = always_on_violations(tool="codex", instruction=half, rules=[half, b"y" * 8])
    assert len(violations) == 1  # 5000 + 5000 + 2 > 10000


def test_no_instruction_file_counts_only_rules() -> None:
    assert always_on_violations(tool="gemini", instruction=None, rules=[b"x" * 16]) == []


def test_skill_body_over_cap_is_named() -> None:
    over = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    ok = "y" * (SKILL_BODY_TOKEN_CAP * 4)
    violations = skill_body_violations([("claude:skills/big", over), ("claude:skills/ok", ok)])
    assert len(violations) == 1
    assert "claude:skills/big" in violations[0]


def test_no_skills_no_violations() -> None:
    assert skill_body_violations([]) == []
