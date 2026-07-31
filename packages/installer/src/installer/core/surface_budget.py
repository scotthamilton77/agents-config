"""The always-on surface budget.

Two mechanical caps, each a hard failure that aborts the deploy before any
write:

- the **always-on surface** for a tool — the deployed instruction file plus
  every admitted always-on rule — is capped at ``ALWAYS_ON_TOKEN_CAP``;
- each admitted **skill body** (the SKILL.md content after its front matter,
  the on-invoke payload) is capped at ``SKILL_BODY_TOKEN_CAP``.

Token count is the ``bytes / 4`` approximation (ceil): no tokenizer dependency
is added. The cap carries >20x margin at the zero-base (~418 tokens vs
10 000), and the size-distribution erosion tripwire watches the trend.
Swapping in ``tiktoken`` is a later refinement, not a blocker.

Each cap is expressed twice — as a ``measure_*`` function returning the number,
and as a ``*_violations`` function returning messages for whatever exceeds it.
The violation functions are defined in terms of the measurements, so a caller
that wants to *report* headroom (the repo-side content lint) and the caller that
wants to *fail* on a breach (the deploy gate) can never disagree about what the
surface weighs.
"""

from __future__ import annotations

from dataclasses import dataclass

ALWAYS_ON_TOKEN_CAP = 10_000
SKILL_BODY_TOKEN_CAP = 2_000


@dataclass(frozen=True, slots=True)
class SurfaceMeasure:
    """One tool's always-on weight: the instruction file plus its rules.

    ``rules`` is carried alongside ``tokens`` because the two move for different
    reasons — a growing token count with a flat rule count is one rule bloating,
    and both rising is the surface accreting.
    """

    tool: str
    tokens: int
    rules: int


@dataclass(frozen=True, slots=True)
class SkillMeasure:
    """One admitted skill body's weight, measured after sanitization."""

    label: str
    tokens: int


def approx_tokens(data: bytes | str) -> int:
    """Approximate token count as ceil(bytes / 4).

    Ceil (not floor) so the estimate is conservative — it fails a hair early
    rather than a hair late at the cap boundary.
    """
    n = len(data if isinstance(data, bytes) else data.encode("utf-8"))
    return -(-n // 4)


def measure_always_on(
    *, tool: str, instruction: bytes | None, rules: list[bytes]
) -> SurfaceMeasure:
    """Weigh one tool's always-on surface: instruction-file bytes plus every
    admitted rule's bytes. A tool with no instruction file (``instruction is
    None``) contributes only its rules."""
    total = approx_tokens(instruction) if instruction is not None else 0
    for rule in rules:
        total += approx_tokens(rule)
    return SurfaceMeasure(tool=tool, tokens=total, rules=len(rules))


def measure_skill_bodies(bodies: list[tuple[str, str]]) -> list[SkillMeasure]:
    """Weigh each admitted skill body. ``bodies`` is ``(label, body_text)``
    per admitted skill; ``body_text`` is the SKILL.md content with front matter
    already stripped."""
    return [SkillMeasure(label=label, tokens=approx_tokens(body)) for label, body in bodies]


def always_on_violations(*, tool: str, instruction: bytes | None, rules: list[bytes]) -> list[str]:
    """Violation messages if a tool's always-on surface exceeds the cap.
    Returns at most one message."""
    measure = measure_always_on(tool=tool, instruction=instruction, rules=rules)
    if measure.tokens > ALWAYS_ON_TOKEN_CAP:
        return [
            f"{tool}: always-on surface is {measure.tokens} tokens, over the "
            f"{ALWAYS_ON_TOKEN_CAP}-token cap"
        ]
    return []


def skill_body_violations(bodies: list[tuple[str, str]]) -> list[str]:
    """Violation messages for admitted skill bodies over the per-skill cap.
    Returns one message per over-cap skill."""
    return [
        f"{m.label}: skill body is {m.tokens} tokens, over the "
        f"{SKILL_BODY_TOKEN_CAP}-token cap — delegate to code"
        for m in measure_skill_bodies(bodies)
        if m.tokens > SKILL_BODY_TOKEN_CAP
    ]
