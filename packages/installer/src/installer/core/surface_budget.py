"""The always-on surface budget (S3, charter D16 / AC1).

Two mechanical caps, each a hard failure that aborts the deploy before any
write:

- the **always-on surface** for a tool — the deployed instruction file plus
  every admitted always-on rule — is capped at ``ALWAYS_ON_TOKEN_CAP``;
- each admitted **skill body** (the SKILL.md content after its front matter,
  the on-invoke payload) is capped at ``SKILL_BODY_TOKEN_CAP``.

Token count is the ``bytes / 4`` approximation (ceil): no tokenizer dependency
is added. The choice is documented in the S3 child spec — the cap carries >20x
margin at the zero-base (~418 tokens vs 10 000), and the size-distribution
erosion tripwire (charter D19) watches the trend. Swapping in ``tiktoken`` is a
later refinement, not a blocker.
"""

from __future__ import annotations

ALWAYS_ON_TOKEN_CAP = 10_000
SKILL_BODY_TOKEN_CAP = 2_000


def approx_tokens(data: bytes | str) -> int:
    """Approximate token count as ceil(bytes / 4).

    Ceil (not floor) so the estimate is conservative — it fails a hair early
    rather than a hair late at the cap boundary.
    """
    n = len(data if isinstance(data, bytes) else data.encode("utf-8"))
    return -(-n // 4)


def always_on_violations(*, tool: str, instruction: bytes | None, rules: list[bytes]) -> list[str]:
    """Violation messages if a tool's always-on surface exceeds the cap.

    The surface is the instruction-file bytes plus every admitted rule's bytes.
    A tool with no instruction file (``instruction is None``) contributes only
    its rules. Returns at most one message.
    """
    total = approx_tokens(instruction) if instruction is not None else 0
    for rule in rules:
        total += approx_tokens(rule)
    if total > ALWAYS_ON_TOKEN_CAP:
        return [
            f"{tool}: always-on surface is {total} tokens, over the {ALWAYS_ON_TOKEN_CAP}-token cap"
        ]
    return []


def skill_body_violations(bodies: list[tuple[str, str]]) -> list[str]:
    """Violation messages for admitted skill bodies over the per-skill cap.

    ``bodies`` is ``(label, body_text)`` per admitted skill; ``body_text`` is
    the SKILL.md content with front matter already stripped. Returns one
    message per over-cap skill.
    """
    out: list[str] = []
    for label, body in bodies:
        tokens = approx_tokens(body)
        if tokens > SKILL_BODY_TOKEN_CAP:
            out.append(
                f"{label}: skill body is {tokens} tokens, over the "
                f"{SKILL_BODY_TOKEN_CAP}-token cap — delegate to code"
            )
    return out
