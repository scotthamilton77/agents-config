"""Each `work create <noun>` template stamps the right bd type + shape label."""

from __future__ import annotations

import pytest

# (noun, expected bd type, expected shape label) — verified against
# lifecycle/nouns.py NOUN_TEMPLATES (bd_type, shape_label). Exact contract.
NOUN_EXPECTATIONS = [
    ("spike", "task", "shape-spike"),
    ("chore", "chore", "shape-chore"),
    ("decision", "decision", "shape-decision"),
    ("feat", "feature", "shape-feat"),
    ("bugfix", "bug", "shape-bugfix"),
    ("spec", "feature", "shape-spec"),
    ("epic", "epic", "shape-epic"),
]


@pytest.mark.parametrize("noun,bd_type,shape_label", NOUN_EXPECTATIONS)
def test_create_noun_stamps_type_and_shape_label(driver, noun, bd_type, shape_label):
    created = driver(["create", noun, "--title", f"noun-{noun}", "--priority", "2", "--orphan"])
    assert created["ok"] is True, created
    item_id = created["data"]["id"]  # create → {"id": ...}
    shown = driver(["show", item_id])["data"]  # single-id show → item directly
    assert shown["type"] == bd_type  # Item field is `type`, not `issue_type`
    assert shape_label in shown["labels"]


def test_create_spec_children_carry_exactly_their_own_labels(driver):
    # bd inherits the parent's current labels onto --parent children by
    # default, so the design child + placeholder minted while the container
    # still carries `creating-spec` would come back carrying `creating-spec`
    # and `shape-spec` (wgclw.9.8). The adapter opts out per create; this pins
    # the EXACT label set against a live bd so any new inheritance surprise
    # fails loudly here, not in a reconcile sweep.
    created = driver(["create", "spec", "--title", "exact-labels", "--priority", "2", "--orphan"])
    assert created["ok"] is True, created
    design = driver(["show", created["data"]["design_child"]])["data"]
    placeholder = driver(["show", created["data"]["placeholder"]])["data"]
    assert set(design["labels"]) == {"shape-design"}
    assert set(placeholder["labels"]) == {"impl-placeholder"}
