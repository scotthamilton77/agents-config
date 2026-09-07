"""Tests for PRRef — the per-PR key (§2).

The ``slug`` is a coded decision: it is the filename stem the file adapter uses
(`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`) and the bd linkage label
(`for-pr-<owner>-<repo>-<n>`). It is a serialization contract, so it is pinned
here at its definition boundary.
"""

from __future__ import annotations

import pytest

from prgroom.prsession.pr_ref import PRRef, is_commit_sha

HEX40 = "a1b2c3d4" * 5


def test_slug_joins_owner_repo_number_with_hyphens() -> None:
    assert PRRef(owner="octo", repo="hello-world", number=42).slug() == "octo-hello-world-42"


def test_display_renders_github_shorthand() -> None:
    assert PRRef(owner="octo", repo="hello-world", number=42).display() == "octo/hello-world#42"


def test_pr_ref_is_hashable_for_use_as_dict_key() -> None:
    # The in-memory store keys a dict by PRRef; frozen+slots makes it hashable.
    ref = PRRef(owner="octo", repo="hello-world", number=1)
    assert {ref: "state"}[ref] == "state"


def test_to_dict_from_dict_round_trips() -> None:
    # The {owner, repo, number} shape is shared by state + contract payloads.
    ref = PRRef(owner="octo", repo="hello-world", number=42)
    assert PRRef.from_dict(ref.to_dict()) == ref
    assert ref.to_dict() == {"owner": "octo", "repo": "hello-world", "number": 42}


# A commit id is 40 characters and nothing else. The forms below are what an id
# picks up on its way through a file or a shell — and each one, accepted, names a
# commit that is not the one the caller meant.
SURROUNDED = [
    pytest.param(HEX40 + "\n", id="a-trailing-newline"),
    pytest.param("\n" + HEX40, id="a-leading-newline"),
    pytest.param(HEX40 + "\n\n", id="two-trailing-newlines"),
    pytest.param(HEX40 + " ", id="trailing-whitespace"),
    pytest.param(HEX40 + "x", id="a-trailing-character"),
    pytest.param(HEX40[:-1], id="one-character-short"),
    pytest.param(HEX40 + "a", id="one-character-long"),
]


def test_a_full_hex_commit_id_is_one() -> None:
    assert is_commit_sha(HEX40)
    assert is_commit_sha(HEX40.upper())


@pytest.mark.parametrize("value", SURROUNDED)
def test_anything_but_the_forty_characters_is_not_a_commit_id(value: str) -> None:
    assert not is_commit_sha(value)
