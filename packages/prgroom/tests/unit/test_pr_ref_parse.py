"""Tests for ``PRRef.parse`` — PR-ref string parsing for the CLI (§1, §3.7).

The CLI verbs receive the PR ref as a raw string (``123``, ``owner/repo#123``,
or a full URL). ``PRRef.parse`` turns it into the typed key the Store uses, or
raises ``PRECONDITION_BAD_PR_REF`` (exit 2, rendered block) on malformed input.
A bare number is only resolvable with an explicit ``owner/repo`` default.
"""

from __future__ import annotations

import pytest

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.prsession.pr_ref import PRRef


def test_parse_owner_repo_hash_number() -> None:
    assert PRRef.parse("octo/demo#7") == PRRef(owner="octo", repo="demo", number=7)


def test_parse_full_url() -> None:
    assert PRRef.parse("https://github.com/octo/demo/pull/7") == PRRef(
        owner="octo", repo="demo", number=7
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/demo/pull/7/files",  # trailing /path
        "https://github.com/octo/demo/pull/7#discussion_r123",  # #fragment directly after n
        "https://github.com/octo/demo/pull/7?tab=files",  # ?query directly after n
        "https://github.com/octo/demo/pull/7/files#diff-abc",  # /path then #fragment
    ],
)
def test_parse_full_url_with_trailing_path_fragment_or_query(url: str) -> None:
    # Real GitHub PR URLs commonly carry a trailing /path, #fragment, or ?query
    # after the PR number; everything after the number is ignored.
    assert PRRef.parse(url) == PRRef(owner="octo", repo="demo", number=7)


def test_parse_bare_number_with_default() -> None:
    assert PRRef.parse("7", default_repo=("octo", "demo")) == PRRef(
        owner="octo", repo="demo", number=7
    )


def test_parse_bare_number_without_default_is_bad_ref() -> None:
    with pytest.raises(PreconditionError) as exc:
        PRRef.parse("7")
    assert exc.value.code is ErrorCode.PRECONDITION_BAD_PR_REF


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-ref",
        "octo/demo",
        "octo/demo#abc",
        "octo#7",
        "octo/demo#",
        "octo/demo#0",
        # A non-delimiter suffix on the number is NOT a valid trailing path/fragment.
        "https://github.com/octo/demo/pull/7abc",
        "https://github.com/octo/demo/pull/0",
    ],
)
def test_parse_malformed_raises_bad_pr_ref(bad: str) -> None:
    with pytest.raises(PreconditionError) as exc:
        PRRef.parse(bad)
    assert exc.value.code is ErrorCode.PRECONDITION_BAD_PR_REF
