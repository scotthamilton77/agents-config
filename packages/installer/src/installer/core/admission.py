"""The admission bar.

Every artifact in a *gated namespace* (``rules``, ``skills``, ``commands``,
``agents``, ``workflows``) must carry a complete ``admission`` record in its
front matter to be deployed. The record states what the artifact is worth, what it costs, and
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

``workflows`` is gated on the same terms — it deploys executable capability
into the user's home, which is the strongest case for a record, not a weaker
one. A workflow is a ``.js`` file rather than markdown, so its record travels
in a leading ``---`` fence carrying nothing but the ``admission`` block; the
gate strips that block before any byte is written, and a fence left with no
surviving key goes with it, so the deployed file is plain JavaScript. The
authored file is therefore not valid JS until the strip — the cost of gating
the namespace rather than exempting it, paid by whoever adds the next
workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from installer.core.frontmatter import split_frontmatter

if TYPE_CHECKING:
    from installer.core.model import StagedItem

GATED_NAMESPACES = frozenset({"rules", "skills", "commands", "agents", "workflows"})

_REQUIRED_FIELDS = ("cost", "remove_when")

# The two ways a record can state the artifact's worth. Exactly one is carried.
_WORTH_FIELDS = ("prevents", "provides")

# Where a gated artifact's front matter lives when the staged item is a
# directory (skills, and any directory-shaped agent): the canonical entry file.
# Public because the gate rewrites this same file's bytes when it sanitizes an
# admitted directory.
DIR_RECORD_FILE = "SKILL.md"


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


def entry_file_text(item: StagedItem) -> str | None:
    """A directory item's record-bearing markdown, read from its source tree.

    A directory item (a skill, or a directory-shaped agent) keeps its record in
    the canonical ``SKILL.md`` entry file under ``source_path``; a directory
    without one has no inspectable record. File items are not asked — they carry
    their own bytes, and a caller holding those bytes already has the text.
    """
    entry = item.source_path / DIR_RECORD_FILE
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


def classify(text: str) -> ItemAdmission:
    """Classify one gated contributor's markdown against the admission bar.

    Takes the text rather than the staged item because the bar judges an
    authored file, and a staged destination is not always one of those: the
    caller resolves which bytes belong to which source — through the merge
    contributions, through the directory-override channel, or from the source
    tree — and asks about each in turn.
    """
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
