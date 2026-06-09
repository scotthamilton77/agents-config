"""Tests for PRRef — the per-PR key (§2).

The ``slug`` is a coded decision: it is the filename stem the file adapter uses
(`$XDG_STATE_HOME/prgroom/<owner>-<repo>-<n>.json`) and the bd linkage label
(`for-pr-<owner>-<repo>-<n>`). It is a serialization contract, so it is pinned
here at its definition boundary.
"""

from __future__ import annotations

from prgroom.prsession.pr_ref import PRRef


def test_slug_joins_owner_repo_number_with_hyphens() -> None:
    assert PRRef(owner="octo", repo="hello-world", number=42).slug() == "octo-hello-world-42"


def test_display_renders_github_shorthand() -> None:
    assert PRRef(owner="octo", repo="hello-world", number=42).display() == "octo/hello-world#42"


def test_pr_ref_is_hashable_for_use_as_dict_key() -> None:
    # The in-memory store keys a dict by PRRef; frozen+slots makes it hashable.
    ref = PRRef(owner="octo", repo="hello-world", number=1)
    assert {ref: "state"}[ref] == "state"
