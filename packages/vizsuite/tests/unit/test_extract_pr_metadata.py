"""PR metadata extractor — author/review-state/timestamps (spec §4.4, slice 5).

Mirrors the adapter/parse split used everywhere else: the extractor calls the
`GhRunner` seam and parses the raw result through the real `parse_pr_meta`, so
the test exercises the actual parse path, not a hand-built `PrMeta`.
"""

from __future__ import annotations

from tests.fakes import ScriptedGhRunner, gh_pr_meta_result


def test_pr_metadata_fetches_and_parses_via_the_gh_seam():
    from vizsuite.extract.pr_metadata import pr_metadata

    gh = ScriptedGhRunner(meta_result=gh_pr_meta_result(author="octocat", review_state="APPROVED"))

    meta = pr_metadata(gh, 7)

    assert meta.author == "octocat"
    assert meta.review_state == "APPROVED"
    assert ("pr_meta", 7) in gh.calls
