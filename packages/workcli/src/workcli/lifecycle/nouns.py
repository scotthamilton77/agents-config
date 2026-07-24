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
    MILESTONE = "milestone"


# Leaf nouns -- everything except the two container nouns (spec/epic). `work
# discover` restricts to these: a discovery files a work item, not a
# structural container.
LEAF_NOUNS: tuple[Noun, ...] = (Noun.SPIKE, Noun.CHORE, Noun.DECISION, Noun.FEAT, Noun.BUGFIX)


@dataclass(frozen=True)
class NounTemplate:
    bd_type: str  # bd --type value
    shape_label: str  # birth shape label, e.g. "shape-feat"
    is_container: bool  # True for spec/epic
    expects_evidence: bool  # True for feat/bugfix (evidence rule applies)
    born_planned: bool  # True for spec -- but `planned` is stamped LAST


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
    # Closes the milestone-with-acceptance expressibility gap -- `--acceptance`
    # flows through like every noun, and `create --raw` stays transport-minimal.
    # Never a discover noun (a discovery is not a roadmap anchor), so LEAF_NOUNS
    # is unchanged.
    Noun.MILESTONE: NounTemplate(
        "milestone",
        "shape-milestone",
        is_container=True,
        expects_evidence=False,
        born_planned=False,
    ),
}

DESIGN_CHILD_LABEL = "shape-design"
IMPL_PLACEHOLDER_LABEL = "impl-placeholder"
# The multi-unit reconciled sub-container: the placeholder becomes this once its
# manifest children are minted. A declared container-shape handle (joins
# `_CONTAINER_SHAPE_LABELS`), so `claim` refuses it by label, never child count.
IMPL_CONTAINER_LABEL = "shape-impl-container"
# A spec container mid-instantiation: born with this handle (create spec /
# promote) and removed STRICTLY LAST, after design child + placeholder exist and
# `planned` is stamped. Its presence is the queryable signal `reconcile`
# enumerates interrupted spec instantiations through; its absence means the
# template is wholly minted. Not a container-shape label -- the container
# already carries `shape-spec` for the claim guard.
CREATING_SPEC_LABEL = "creating-spec"
PLANNED_LABEL = "planned"
SPEC_READY_LABEL = "spec-ready"
