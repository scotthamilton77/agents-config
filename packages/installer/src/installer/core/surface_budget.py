"""The always-on surface budget.

Three mechanical caps, each a hard failure that aborts the deploy before any
write:

- the **always-on surface** for a tool — the deployed instruction file, every
  admitted always-on rule, and every skill catalog entry that tool's runtime
  publishes to the model — is capped at ``ALWAYS_ON_TOKEN_CAP``;
- the **user core** inside that surface — the deployed instruction file alone,
  which is the shared zero-based core plus whatever the tool's own template
  adds around it — is capped at ``USER_CORE_TOKEN_CAP``;
- each admitted **skill body** (the SKILL.md content after its front matter,
  the on-invoke payload) is capped at ``SKILL_BODY_TOKEN_CAP``, or at
  ``USER_INVOKED_SKILL_BODY_TOKEN_CAP`` when the target it deploys to keeps
  that skill out of the model's reach.

The core cap is a sub-budget rather than a second opinion about the same
bytes. The surface cap prices what a session loads in total, and a surface
under it can still be one bloated instruction file with nothing else admitted;
the core cap prices the one component that no admission decision can remove,
so a line only earns a place in it by being universal. Without it the core can
grow by an order of magnitude and stay invisible under the wider ceiling.

A ceiling prices bytes the reader cannot decline, and it prices them as the
target actually loads them. A catalog entry is the unconditional case: a skill's
name and description sit in the session before the user has typed anything,
which is what puts them in the same aggregate as the instruction file instead of
in a ceiling of their own. A model-invoked body is loaded on the model's own
judgement, mid-task, against whatever else the context is already carrying; a
body the model cannot reach is loaded only when the user names it, so the cost
is asked for and lands at a moment chosen for it. That difference is what the
second cap prices, and it is all it prices: the looser number is relief for a
body that has already been split down, never permission to leave it whole.

Both facts are per target, not per artifact, because the tools differ on whether
a user-invoked declaration reaches their loader at all (see ``capabilities``).
One skill is therefore charged on one tool and free on another, and measured
against a different ceiling on each. Where a tool's skill loading is not modelled
at all, it contributes to neither number.

And one measurement with no ceiling: a skill's **reference payload**, the files
that deploy beside its entry (``measure_skill_payload``). Reported, never
enforced. The unit a reader pays is one file chosen mid-task, so the directory
total is a quantity nobody is ever charged, and the largest readable file in the
tree is a verbatim mirror of an upstream document that a cap could only truncate
or delete. Readable means ``.md`` and ``.txt``; everything else is counted apart
and costed at nothing, because executed scripts, schemas and fixtures are disk
weight rather than context weight — charging them would price this repository's
own "code over prose" principle as a cost, so the exclusion is a decision and
not an oversight.

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

ALWAYS_ON_TOKEN_CAP = 10_000
USER_CORE_TOKEN_CAP = 800
SKILL_BODY_TOKEN_CAP = 2_000
USER_INVOKED_SKILL_BODY_TOKEN_CAP = 5_000

#: Payload suffixes an agent reads into its context as prose. Everything else a
#: skill ships is executed or indexed, and is reported apart at no cost.
READABLE_SUFFIXES = frozenset({".md", ".txt"})


@dataclass(frozen=True, slots=True)
class SurfaceMeasure:
    """One tool's always-on weight: the instruction file, its rules, and the
    skill catalog entries its runtime publishes.

    ``rules`` and ``catalog_entries`` are carried alongside ``tokens`` because
    the three move for different reasons — a growing token count with a flat
    rule count is one rule bloating, both rising is the surface accreting, and a
    rising entry count is the component that grows with every admission while
    the rules stay still.

    ``core_tokens`` is the instruction file's own share of ``tokens``, carried
    separately because it answers to a cap of its own and because it is the one
    component a reader cannot decline by admitting less.
    """

    tool: str
    tokens: int
    core_tokens: int
    rules: int
    catalog_entries: int


@dataclass(frozen=True, slots=True)
class SkillBodySource:
    """One admitted skill body on its way to the scale.

    ``user_invoked`` is read from the artifact's **projected** front matter, so
    it is a property of the deploy target rather than of the source: a tool
    the projection strips the key for measures the body against the strict
    cap. Where nothing replaces the key (Gemini, OpenCode) that is the plain
    truth — the model reaches the body on its own judgement whatever the
    author wrote. Codex strips the key too but deploys the declaration as a
    generated sidecar, and its copy is still priced from the projected
    reading — an over-charge in the safe direction. One artifact can
    therefore carry two numbers, one per target.
    """

    label: str
    body: str
    user_invoked: bool


@dataclass(frozen=True, slots=True)
class SkillPayloadMeasure:
    """What one skill deploys beside its body — reported, never capped.

    ``prose_tokens`` and ``largest_tokens`` are the two numbers worth a reader's
    attention: the whole tree if they followed every pointer, and the one file
    they actually pay when they follow one. ``other_tokens`` is stated apart and
    costed at nothing, so that a skill which moved work out of prose and into
    code does not read as one that grew.
    """

    label: str
    prose_tokens: int
    prose_files: int
    largest_file: str
    largest_tokens: int
    other_tokens: int


@dataclass(frozen=True, slots=True)
class SkillMeasure:
    """One admitted skill body's weight, measured after sanitization.

    ``cap`` travels with the measurement because with two caps in play the
    number alone does not say whether a body has headroom.
    """

    label: str
    tokens: int
    cap: int


def approx_tokens(data: bytes | str) -> int:
    """Approximate token count as ceil(bytes / 4).

    Ceil (not floor) so the estimate is conservative — it fails a hair early
    rather than a hair late at the cap boundary.
    """
    n = len(data if isinstance(data, bytes) else data.encode("utf-8"))
    return -(-n // 4)


def measure_always_on(
    *, tool: str, instruction: bytes | None, rules: list[bytes], catalog: list[bytes]
) -> SurfaceMeasure:
    """Weigh one tool's always-on surface: instruction-file bytes, every admitted
    rule's bytes, and every skill catalog entry ``tool``'s runtime publishes to
    the model. A tool with no instruction file (``instruction is None``)
    contributes only the other two.

    Which entries belong in ``catalog`` is the caller's judgement and cannot be
    made here: this function sees bytes, not which skill produced them or what
    the target does with it. An entry the target's runtime never publishes must
    not be in the list.
    """
    core = approx_tokens(instruction) if instruction is not None else 0
    total = core
    for entry in (*rules, *catalog):
        total += approx_tokens(entry)
    return SurfaceMeasure(
        tool=tool,
        tokens=total,
        core_tokens=core,
        rules=len(rules),
        catalog_entries=len(catalog),
    )


def skill_body_cap(*, user_invoked: bool) -> int:
    """The cap one skill body is measured against."""
    return USER_INVOKED_SKILL_BODY_TOKEN_CAP if user_invoked else SKILL_BODY_TOKEN_CAP


def measure_skill_bodies(bodies: Sequence[SkillBodySource]) -> list[SkillMeasure]:
    """Weigh each admitted skill body against the cap its invocation mode picks.
    ``body`` is the SKILL.md content with front matter already stripped."""
    return [
        SkillMeasure(
            label=source.label,
            tokens=approx_tokens(source.body),
            cap=skill_body_cap(user_invoked=source.user_invoked),
        )
        for source in bodies
    ]


def always_on_violations(
    *, tool: str, instruction: bytes | None, rules: list[bytes], catalog: list[bytes]
) -> list[str]:
    """Violation messages if a tool's always-on surface exceeds the cap.
    Returns at most one message."""
    measure = measure_always_on(tool=tool, instruction=instruction, rules=rules, catalog=catalog)
    if measure.tokens > ALWAYS_ON_TOKEN_CAP:
        return [
            f"{tool}: always-on surface is {measure.tokens} tokens, over the "
            f"{ALWAYS_ON_TOKEN_CAP}-token cap"
        ]
    return []


def user_core_violations(*, tool: str, instruction: bytes | None) -> list[str]:
    """Violation messages if a tool's deployed instruction file exceeds the core
    cap. Returns at most one message.

    Measured on the assembled file rather than on the shared source, because the
    core a session pays is what a tool's template produced: a template that
    includes the shared core and then adds to it has grown the core, whatever
    the shared file weighs. A tool deploying no instruction file has no core.
    """
    if instruction is None:
        return []
    tokens = approx_tokens(instruction)
    if tokens > USER_CORE_TOKEN_CAP:
        return [
            f"{tool}: always-on core is {tokens} tokens, over the {USER_CORE_TOKEN_CAP}-token cap"
        ]
    return []


def measure_skill_payload(*, label: str, files: Mapping[Path, bytes]) -> SkillPayloadMeasure:
    """Weigh one skill's payload — every file that deploys beside its entry.

    ``files`` maps a path relative to the skill's directory to the bytes that
    deploy at it, so which files those are is the caller's answer: nothing here
    reads disk or knows what a deploy prunes. The entry file itself is not one
    of them — its body is already weighed against the skill body cap, and
    counting it here would charge it twice.

    A skill with no payload measures zero against an empty ``largest_file``.
    Ties for largest are broken by path order, so the answer does not depend on
    the order the caller happened to read the tree in.
    """
    prose = {rel: data for rel, data in files.items() if rel.suffix in READABLE_SUFFIXES}
    largest: Path | None = None
    for rel in sorted(prose):
        if largest is None or len(prose[rel]) > len(prose[largest]):
            largest = rel
    return SkillPayloadMeasure(
        label=label,
        prose_tokens=sum(approx_tokens(data) for data in prose.values()),
        prose_files=len(prose),
        largest_file=str(largest) if largest is not None else "",
        largest_tokens=approx_tokens(prose[largest]) if largest is not None else 0,
        other_tokens=sum(
            approx_tokens(data)
            for rel, data in files.items()
            if rel.suffix not in READABLE_SUFFIXES
        ),
    )


def skill_body_violations(bodies: Sequence[SkillBodySource]) -> list[str]:
    """Violation messages for admitted skill bodies over the cap that applies to
    them. Returns one message per over-cap skill."""
    return [
        f"{m.label}: skill body is {m.tokens} tokens, over the {m.cap}-token cap — delegate to code"
        for m in measure_skill_bodies(bodies)
        if m.tokens > m.cap
    ]
