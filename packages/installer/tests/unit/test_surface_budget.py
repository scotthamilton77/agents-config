"""The always-on surface budget."""

from __future__ import annotations

from pathlib import Path

from installer.core.surface_budget import (
    ALWAYS_ON_TOKEN_CAP,
    SKILL_BODY_TOKEN_CAP,
    USER_CORE_TOKEN_CAP,
    USER_INVOKED_SKILL_BODY_TOKEN_CAP,
    SkillBodySource,
    always_on_violations,
    approx_tokens,
    measure_always_on,
    measure_skill_bodies,
    measure_skill_payload,
    skill_body_violations,
    user_core_violations,
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
    assert always_on_violations(tool="claude", instruction=b"x" * 1670, rules=[], catalog=[]) == []


def test_boundary_at_cap_passes_and_one_over_fails() -> None:
    at_cap = b"x" * (ALWAYS_ON_TOKEN_CAP * 4)  # exactly 10_000 tokens
    assert always_on_violations(tool="claude", instruction=at_cap, rules=[], catalog=[]) == []
    over = b"x" * (ALWAYS_ON_TOKEN_CAP * 4 + 1)  # 10_001 tokens (ceil)
    violations = always_on_violations(tool="claude", instruction=over, rules=[], catalog=[])
    assert len(violations) == 1
    assert "claude" in violations[0]
    assert str(ALWAYS_ON_TOKEN_CAP) in violations[0]


def test_rules_count_toward_always_on_surface() -> None:
    half = b"x" * (ALWAYS_ON_TOKEN_CAP * 2)  # 5_000 tokens each
    violations = always_on_violations(
        tool="codex", instruction=half, rules=[half, b"y" * 8], catalog=[]
    )
    assert len(violations) == 1  # 5000 + 5000 + 2 > 10000


def test_no_instruction_file_counts_only_rules() -> None:
    assert (
        always_on_violations(tool="gemini", instruction=None, rules=[b"x" * 16], catalog=[]) == []
    )


def test_the_core_boundary_passes_at_the_cap_and_fails_one_over() -> None:
    """The core sub-budget, pinned at both sides of its edge. The number is the
    ceiling a line has to fit to earn always-on status, so a change to it is a
    change to what the shared core may say."""
    at_cap = b"x" * (USER_CORE_TOKEN_CAP * 4)
    assert user_core_violations(tool="claude", instruction=at_cap) == []
    over = b"x" * (USER_CORE_TOKEN_CAP * 4 + 1)
    violations = user_core_violations(tool="claude", instruction=over)
    assert len(violations) == 1
    assert "claude" in violations[0]
    assert str(USER_CORE_TOKEN_CAP) in violations[0]


def test_a_core_many_times_over_its_cap_still_passes_the_surface_cap() -> None:
    """Why the sub-budget exists at all. The surface ceiling is over ten times the
    core's, so without a cap of its own the core can grow by an order of magnitude
    and breach nothing."""
    bloated = b"x" * (USER_CORE_TOKEN_CAP * 4 * 5)
    assert always_on_violations(tool="claude", instruction=bloated, rules=[], catalog=[]) == []
    assert len(user_core_violations(tool="claude", instruction=bloated)) == 1


def test_rules_and_catalog_entries_are_not_charged_to_the_core() -> None:
    """The core is the instruction file alone. Admitted rules and catalog entries
    answer to the surface cap, and charging them here would fail a core that had
    not moved — the one number a reader cannot reduce by admitting less."""
    measure = measure_always_on(
        tool="claude", instruction=b"x" * 400, rules=[b"y" * 4_000], catalog=[b"z" * 400]
    )
    assert (measure.core_tokens, measure.tokens) == (100, 1_200)


def test_a_tool_with_no_instruction_file_has_no_core() -> None:
    """Gemini's rules deploy without one, and a missing file is a core of zero
    rather than a breach."""
    assert user_core_violations(tool="gemini", instruction=None) == []
    measure = measure_always_on(tool="gemini", instruction=None, rules=[b"x" * 16], catalog=[])
    assert measure.core_tokens == 0


def test_the_core_verdict_is_the_core_measurement_it_reports() -> None:
    """Same contract as the surface cap: the lint reports headroom from the number
    the gate fails on, so the two can never disagree about what the core weighs."""
    over = b"x" * (USER_CORE_TOKEN_CAP * 4 + 1)
    measure = measure_always_on(tool="claude", instruction=over, rules=[], catalog=[])
    violations = user_core_violations(tool="claude", instruction=over)
    assert str(measure.core_tokens) in violations[0]


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
    """With two caps the token count alone does not say whether a body has
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
    measure = measure_always_on(
        tool="claude", instruction=b"x" * 8, rules=[b"y" * 4, b"z" * 4], catalog=[]
    )
    assert (measure.tool, measure.tokens, measure.rules) == ("claude", 4, 2)


def test_the_violation_verdict_is_the_measurement_it_reports() -> None:
    """The two callers must never disagree about what the surface weighs: the lint
    reports headroom from the same number the gate fails on."""
    over = b"x" * (ALWAYS_ON_TOKEN_CAP * 4 + 1)
    measure = measure_always_on(tool="claude", instruction=over, rules=[], catalog=[])
    violations = always_on_violations(tool="claude", instruction=over, rules=[], catalog=[])
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


def test_catalog_entries_are_charged_to_the_always_on_surface() -> None:
    """A skill's name and description load before the user types, so they belong
    in the same aggregate as the instruction file — the component that grows with
    every admission, charged against the ceiling that already exists."""
    entry = b"x" * 40  # 10 tokens
    measure = measure_always_on(
        tool="claude", instruction=b"y" * 8, rules=[], catalog=[entry, entry]
    )
    assert (measure.tokens, measure.catalog_entries) == (22, 2)


def test_a_catalog_alone_can_breach_the_always_on_cap() -> None:
    """No separate ceiling: the entries are measured by the always-on cap, over a
    domain that includes them."""
    over = b"x" * (ALWAYS_ON_TOKEN_CAP * 4 + 4)
    violations = always_on_violations(tool="opencode", instruction=None, rules=[], catalog=[over])
    assert len(violations) == 1
    assert str(ALWAYS_ON_TOKEN_CAP) in violations[0]


def test_the_payload_report_splits_prose_from_what_is_never_read() -> None:
    """Executed code and indexed data are disk weight, not context weight. Folding
    them into the prose total would report a skill that moved work into code as
    one that grew, and price this repo's own code-over-prose principle as a cost."""
    measure = measure_skill_payload(
        label="skills/example",
        files={
            Path("references/a.md"): b"x" * 40,
            Path("references/b.txt"): b"y" * 8,
            Path("scripts/run.py"): b"z" * 400,
            Path("evals/corpus.json"): b"w" * 4,
        },
    )
    assert (measure.prose_tokens, measure.prose_files) == (12, 2)
    assert measure.other_tokens == 101


def test_the_payload_report_names_the_largest_single_readable_file() -> None:
    """The unit a reader pays is one file chosen mid-task, never the tree — so the
    number that would decide anything is the largest one file, not the total."""
    measure = measure_skill_payload(
        label="skills/example",
        files={
            Path("references/small.md"): b"x" * 4,
            Path("references/big.md"): b"y" * 40,
            Path("assets/huge.json"): b"z" * 4_000,
        },
    )
    assert (measure.largest_file, measure.largest_tokens) == ("references/big.md", 10)


def test_a_skill_with_no_payload_measures_zero() -> None:
    measure = measure_skill_payload(label="skills/bare", files={})
    assert (measure.prose_tokens, measure.other_tokens, measure.largest_file) == (0, 0, "")
