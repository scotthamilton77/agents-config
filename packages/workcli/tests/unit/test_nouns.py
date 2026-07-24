"""Noun taxonomy (plan L9) + the lifecycle marker/container helpers (plan
`lifecycle/__init__.py`).

`NOUN_TEMPLATES` is the single source of truth Task 3+ verbs key off of to
turn a noun into a bd `--type` + birth shape label. `is_container` is a
declared-state test only -- deep review flagged (MAJOR) an earlier
child-count-based guard as wrong, since a `claim` on a childless-but-labeled
container must still be rejected, and a plain item with children but no
container label/type must not accidentally be treated as one (spec
§5/invariant 5).
"""

from __future__ import annotations

from workcli.lifecycle import DELIVERED_MARKER, has_marker, is_container
from workcli.lifecycle.nouns import NOUN_TEMPLATES, Noun, NounTemplate
from workcli.model import Item


def _item(**overrides: object) -> Item:
    base = dict(
        id="x.1",
        title="T",
        type="task",
        status="open",
        priority="P2",
        labels=[],
        parent=None,
        deps=[],
        children=[],
        description="",
        notes="",
        created=None,
        updated=None,
    )
    base.update(overrides)
    return Item(**base)  # type: ignore[arg-type]


def test_has_marker_true_when_a_line_starts_with_the_prefix():
    assert has_marker("a\n[work] delivered: pr#1\nb", DELIVERED_MARKER) is True


def test_has_marker_false_when_the_prefix_is_absent():
    assert has_marker("a\nb\nc", DELIVERED_MARKER) is False


def test_is_container_true_for_shape_spec_label():
    item = _item(type="feature", labels=["shape-spec"])

    assert is_container(item) is True


def test_is_container_true_for_shape_epic_label():
    item = _item(type="feature", labels=["shape-epic"])

    assert is_container(item) is True


def test_is_container_true_for_childless_epic_typed_item():
    item = _item(type="epic", labels=[], children=[])

    assert is_container(item) is True


def test_is_container_false_for_feature_item_with_children_but_no_container_label_or_type():
    item = _item(type="feature", labels=[], children=["x.2", "x.3"])

    assert is_container(item) is False


def test_noun_templates_covers_all_eight_nouns_per_the_l9_table():
    # Seven base nouns + milestone.
    assert {
        Noun.SPIKE: NounTemplate("task", "shape-spike", False, False, False),
        Noun.CHORE: NounTemplate("chore", "shape-chore", False, False, False),
        Noun.DECISION: NounTemplate("decision", "shape-decision", False, False, False),
        Noun.FEAT: NounTemplate("feature", "shape-feat", False, True, False),
        Noun.BUGFIX: NounTemplate("bug", "shape-bugfix", False, True, False),
        Noun.SPEC: NounTemplate("feature", "shape-spec", True, False, True),
        Noun.EPIC: NounTemplate("epic", "shape-epic", True, False, False),
        Noun.MILESTONE: NounTemplate("milestone", "shape-milestone", True, False, False),
    } == NOUN_TEMPLATES
