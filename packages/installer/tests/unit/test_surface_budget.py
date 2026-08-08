"""The always-on surface budget."""

from __future__ import annotations

from installer.core.surface_budget import (
    ALWAYS_ON_TOKEN_CAP,
    SKILL_BODY_TOKEN_CAP,
    USER_INVOKED_SKILL_BODY_TOKEN_CAP,
    SkillBodySource,
    always_on_violations,
    approx_tokens,
    measure_always_on,
    measure_skill_bodies,
    skill_body_violations,
)


def _body(label: str, tokens: int, *, user_invoked: bool = False) -> SkillBodySource:
    return SkillBodySource(label=label, body="x" * (tokens * 4), user_invoked=user_invoked)


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
    violations = skill_body_violations(
        [
            _body("claude:skills/big", SKILL_BODY_TOKEN_CAP + 1),
            _body("claude:skills/ok", SKILL_BODY_TOKEN_CAP),
        ]
    )
    assert len(violations) == 1
    assert "claude:skills/big" in violations[0]
    assert f"{SKILL_BODY_TOKEN_CAP}-token cap" in violations[0]


def test_no_skills_no_violations() -> None:
    assert skill_body_violations([]) == []


def test_a_user_invoked_body_is_measured_against_the_looser_cap() -> None:
    """Both sides of the raised boundary: at 5,000 it passes, one token over it
    fails, and the message names the cap it was measured against."""
    assert skill_body_violations([_body("c:skills/w", 5_000, user_invoked=True)]) == []
    violations = skill_body_violations([_body("c:skills/w", 5_001, user_invoked=True)])
    assert len(violations) == 1
    assert f"{USER_INVOKED_SKILL_BODY_TOKEN_CAP}-token cap" in violations[0]


def test_a_body_between_the_two_caps_passes_only_when_user_invoked() -> None:
    """The whole point of the second number: 2,971 tokens is a violation for a
    model-invoked skill and fine for a user-invoked one."""
    between = 2_971
    assert skill_body_violations([_body("c:skills/w", between, user_invoked=True)]) == []
    assert len(skill_body_violations([_body("c:skills/w", between)])) == 1


def test_the_measurement_carries_the_cap_that_applies_to_it() -> None:
    """With two caps the token count alone no longer says whether a body has
    headroom, so the trend report needs the ceiling beside the number."""
    measures = measure_skill_bodies(
        [_body("c:skills/m", 10), _body("c:skills/u", 10, user_invoked=True)]
    )
    assert [(m.label, m.cap) for m in measures] == [
        ("c:skills/m", SKILL_BODY_TOKEN_CAP),
        ("c:skills/u", USER_INVOKED_SKILL_BODY_TOKEN_CAP),
    ]


def test_measurement_carries_the_rule_count_beside_the_token_total() -> None:
    """Tokens and rule count move for different reasons — rising tokens against a
    flat rule count is one rule bloating, both rising is the surface accreting. A
    reader watching for drift needs to tell those apart."""
    measure = measure_always_on(tool="claude", instruction=b"x" * 8, rules=[b"y" * 4, b"z" * 4])
    assert (measure.tool, measure.tokens, measure.rules) == ("claude", 4, 2)


def test_the_violation_verdict_is_the_measurement_it_reports() -> None:
    """The two callers must never disagree about what the surface weighs: the lint
    reports headroom from the same number the gate fails on."""
    over = b"x" * (ALWAYS_ON_TOKEN_CAP * 4 + 1)
    measure = measure_always_on(tool="claude", instruction=over, rules=[])
    violations = always_on_violations(tool="claude", instruction=over, rules=[])
    assert str(measure.tokens) in violations[0]


def test_skill_bodies_are_measured_whether_or_not_they_breach() -> None:
    """Every admitted body is weighed, not only the over-cap ones — an under-cap
    body that has doubled is the signal the trend report exists to show."""
    measures = measure_skill_bodies(
        [
            SkillBodySource(label="claude:skills/small", body="y" * 8, user_invoked=False),
            SkillBodySource(label="claude:skills/big", body="x", user_invoked=False),
        ]
    )
    assert [(m.label, m.tokens) for m in measures] == [
        ("claude:skills/small", 2),
        ("claude:skills/big", 1),
    ]
