"""The admission bar.

Every artifact in a *gated namespace* (``rules``, ``skills``, ``commands``,
``agents``) must carry a complete ``admission`` record in its front matter to
be deployed. The record states what the artifact is worth, what it costs, and
the observation that would remove it — so nothing enters the always-on /
on-invoke surface by default or nostalgia.

Worth is stated one of two ways, and a record carries **exactly one**:

- ``prevents`` — the failure the artifact stops. The preventative case.
- ``provides`` — the capability it supplies. The assistive case: a repeatable
  procedure is worth having even though no failure precedes it, and forcing it
  into failure language produces a fiction rather than a justification.

Requiring exactly one keeps the record a claim rather than a brochure: an
author must decide which case the artifact actually makes.

Classification is three-valued:

- **no record** — no ``admission`` block at all → *not admitted* (dropped and
  reported). This is the zero-base mechanism: today's content carries no
  records, so all of it is skipped and prune empties the deployed dirs.
- **malformed** — an ``admission`` block that is not a mapping, is missing a
  required non-empty field, or states neither/both worth fields → a mechanical
  defect that *aborts* the deploy.
- **complete** — one worth field plus ``cost`` and ``remove_when``, all
  non-empty → *admitted*.

``agents`` is gated alongside the ``rule/skill/command`` set: an agent is an
on-invoke capability indistinguishable from a skill for admission purposes, and
the zero-base hand-deploy emptied ``agents/`` too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from installer.core.frontmatter import split_frontmatter

if TYPE_CHECKING:
    from installer.core.model import StagedItem

GATED_NAMESPACES = frozenset({"rules", "skills", "commands", "agents"})

_REQUIRED_FIELDS = ("cost", "remove_when")

# The two ways a record can state the artifact's worth. Exactly one is carried.
_WORTH_FIELDS = ("prevents", "provides")

# Where a gated artifact's front matter lives when the staged item is a
# directory (skills, and any directory-shaped agent): the canonical entry file.
_DIR_RECORD_FILE = "SKILL.md"


class AdmissionOutcome(Enum):
    """The three-valued verdict for one gated artifact."""

    NO_RECORD = "no_record"
    MALFORMED = "malformed"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class AdmissionRecord:
    """A complete admission record.

    Exactly one of ``prevents`` / ``provides`` is set; the other is ``None``.
    """

    cost: str
    remove_when: str
    prevents: str | None = None
    provides: str | None = None


@dataclass(frozen=True, slots=True)
class ItemAdmission:
    """The classification of one gated item.

    ``record`` and ``claims`` are populated only when ``outcome`` is
    ``COMPLETE``; ``detail`` names the defect only when ``MALFORMED``.
    """

    outcome: AdmissionOutcome
    record: AdmissionRecord | None = None
    claims: dict[str, str] = field(default_factory=dict)
    detail: str = ""


def is_gated(item: StagedItem) -> bool:
    """True when ``item`` sits in a gated namespace and must carry a record."""
    return item.namespace in GATED_NAMESPACES


def record_source_text(item: StagedItem) -> str | None:
    """The markdown whose front matter carries the admission record.

    File items (rules, commands, ``*.md`` agents) carry their own bytes. A
    directory item (a skill, or a directory-shaped agent) keeps its record in
    the canonical ``SKILL.md`` entry file read from ``source_path``; a directory
    without one has no inspectable record.
    """
    if item.content is not None:
        return item.content.decode("utf-8", errors="replace")
    entry = item.source_path / _DIR_RECORD_FILE
    if entry.is_file():
        return entry.read_text(encoding="utf-8")
    return None


def _coerce_claims(raw: Any) -> dict[str, str]:
    """A ``claims`` front-matter value coerced to ``{str: str}``.

    Only string→scalar pairs survive; a non-mapping ``claims`` contributes
    nothing. Scalars are stringified so ``true``/``1`` compare by rendered
    value in the conflict audit.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and value is not None and not isinstance(value, (dict, list)):
            out[key] = str(value)
    return out


def classify(item: StagedItem) -> ItemAdmission:
    """Classify one gated item against the admission bar."""
    text = record_source_text(item)
    if text is None:
        return ItemAdmission(AdmissionOutcome.NO_RECORD)
    mapping, _body = split_frontmatter(text)
    if mapping is None or "admission" not in mapping:
        return ItemAdmission(AdmissionOutcome.NO_RECORD)

    block: Any = mapping["admission"]
    if not isinstance(block, dict):
        return ItemAdmission(AdmissionOutcome.MALFORMED, detail="admission is not a mapping")

    missing: list[str] = []
    values: dict[str, str] = {}
    for key in (*_REQUIRED_FIELDS, *_WORTH_FIELDS):
        raw = block.get(key)
        if isinstance(raw, str) and raw.strip():
            values[key] = raw.strip()
        elif key in _REQUIRED_FIELDS:
            missing.append(key)
    if missing:
        return ItemAdmission(
            AdmissionOutcome.MALFORMED,
            detail=f"missing or empty field(s): {', '.join(missing)}",
        )

    stated = [key for key in _WORTH_FIELDS if key in values]
    if len(stated) != 1:
        named = " or ".join(_WORTH_FIELDS)
        defect = "states both" if stated else "states neither"
        return ItemAdmission(
            AdmissionOutcome.MALFORMED,
            detail=f"{defect} {named} — a record carries exactly one",
        )

    record = AdmissionRecord(
        cost=values["cost"],
        remove_when=values["remove_when"],
        prevents=values.get("prevents"),
        provides=values.get("provides"),
    )
    return ItemAdmission(
        AdmissionOutcome.COMPLETE, record=record, claims=_coerce_claims(mapping.get("claims"))
    )
