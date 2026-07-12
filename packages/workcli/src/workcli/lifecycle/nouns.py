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
    Noun.SPIKE: NounTemplate("task", "shape-spike", False, False, False),
    Noun.CHORE: NounTemplate("chore", "shape-chore", False, False, False),
    Noun.DECISION: NounTemplate("decision", "shape-decision", False, False, False),
    Noun.FEAT: NounTemplate("feature", "shape-feat", False, True, False),
    Noun.BUGFIX: NounTemplate("bug", "shape-bugfix", False, True, False),
    Noun.SPEC: NounTemplate("feature", "shape-spec", True, False, True),
    Noun.EPIC: NounTemplate("epic", "shape-epic", True, False, False),
}

DESIGN_CHILD_LABEL = "shape-design"
IMPL_PLACEHOLDER_LABEL = "impl-placeholder"
PLANNED_LABEL = "planned"
SPEC_READY_LABEL = "spec-ready"
