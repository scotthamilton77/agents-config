from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Noun(StrEnum):
    SPIKE = "spike"
    CHORE = "chore"
    DECISION = "decision"
    FEAT = "feat"
    BUGFIX = "bugfix"
    SPEC = "spec"
    EPIC = "epic"


@dataclass(frozen=True)
class NounTemplate:
    bd_type: str  # bd --type value
    shape_label: str  # birth shape label, e.g. "shape-feat"
    is_container: bool  # True for spec/epic
    expects_evidence: bool  # True for feat/bugfix (evidence rule applies)
    born_planned: bool  # True for spec -- but `planned` is stamped LAST (L16)


NOUN_TEMPLATES: dict[Noun, NounTemplate] = {
    Noun.SPIKE: NounTemplate(
        "task", "shape-spike", is_container=False, expects_evidence=False, born_planned=False
    ),
    Noun.CHORE: NounTemplate(
        "chore", "shape-chore", is_container=False, expects_evidence=False, born_planned=False
    ),
    Noun.DECISION: NounTemplate(
        "decision",
        "shape-decision",
        is_container=False,
        expects_evidence=False,
        born_planned=False,
    ),
    Noun.FEAT: NounTemplate(
        "feature", "shape-feat", is_container=False, expects_evidence=True, born_planned=False
    ),
    Noun.BUGFIX: NounTemplate(
        "bug", "shape-bugfix", is_container=False, expects_evidence=True, born_planned=False
    ),
    Noun.SPEC: NounTemplate(
        "feature", "shape-spec", is_container=True, expects_evidence=False, born_planned=True
    ),
    Noun.EPIC: NounTemplate(
        "epic", "shape-epic", is_container=True, expects_evidence=False, born_planned=False
    ),
}

DESIGN_CHILD_LABEL = "shape-design"
IMPL_PLACEHOLDER_LABEL = "impl-placeholder"
# The multi-unit reconciled sub-container: the placeholder becomes this once its
# manifest children are minted. A declared container-shape handle (joins
# `_CONTAINER_SHAPE_LABELS`), so `claim` refuses it by label, never child count.
IMPL_CONTAINER_LABEL = "shape-impl-container"
PLANNED_LABEL = "planned"
SPEC_READY_LABEL = "spec-ready"
