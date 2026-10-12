"""The root delivery contract sends an author to the change-record skill.

Three sentences in the root ``AGENTS.md`` are the only thing that tells an author
to render a pull request body from a change record, how to open the pull request,
and how to carry out an instructed merge. No gate reads their meaning, so an edit
that drops one would pass every lint. These tests pin each sentence by its text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

_HEADING = "### How work ships here\n"

_SENTENCES = (
    "Render the PR body from a change record, the JSON document the `change-record` skill "
    "defines, and never write the body by hand.",
    "Open the PR with that skill's `publish --create`, or run `gh pr create` only after its "
    "`lint` exits 0 on the record.",
    "Run a merge that a human has instructed through the `change-record` skill's `merge` "
    "subcommand.",
)


def _delivery_contract() -> str:
    """Return the delivery contract section of the root ``AGENTS.md`` on one line.

    Runs of whitespace collapse to one space, so rewrapping the section does not
    fail a sentence that is still there.
    """
    text = (_REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert _HEADING in text, "the root AGENTS.md has no delivery contract section"
    section = text.split(_HEADING, 1)[1].split("\n#", 1)[0]
    return " ".join(section.split())


@pytest.mark.parametrize(
    "sentence",
    _SENTENCES,
    ids=("body-rendered-from-a-record", "lint-or-publish-create", "merge-subcommand"),
)
def test_cr_g2_the_delivery_contract_states_each_change_record_sentence(sentence: str) -> None:
    """CR-G2: each sentence stands in the delivery contract, word for word."""
    assert sentence in _delivery_contract()
