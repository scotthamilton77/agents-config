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
