"""The verdict-posting flow: what is submitted, where it anchors, when it refuses.

The verb makes exactly one submission per verdict, so every anchor it sends must
already be placeable — GitHub rejects the whole review when one comment names a
line outside the diff. These tests drive the flow through the route-table
transport and assert on the single posted payload.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.app import FILES_PER_PAGE, REVIEWS_PER_PAGE
from prgroom.lifecycle.approve import APPROVE_EVENT
from prgroom.lifecycle.post_verdict import (
    Anchor,
    Verdict,
    build_comments,
    commentable_spans,
    place_anchor,
    post_verdict_pr,
)
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner, RouteTableHttp

HEAD = "a" * 40
MOVED = "b" * 40
APP_ID = 4275336
KEY_PATH = Path("/keys/app.pem")
REF = PRRef(owner="octo", repo="demo", number=5)
LOGIN = "pr-hater[bot]"

PULL = "/repos/octo/demo/pulls/5"
REVIEWS_PAGE_1 = ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1")
FILES_PAGE_1 = ("GET", f"{PULL}/files?per_page={FILES_PER_PAGE}&page=1")
SUBMIT = ("POST", f"{PULL}/reviews")

APP_PY = "packages/prgroom/src/prgroom/gh/app.py"
TEST_APPROVE = "packages/prgroom/tests/unit/test_cli_approve.py"
NOTES_A = "docs/a/notes.md"
NOTES_B = "docs/b/notes.md"
BINARY = "assets/logo.png"

# One changed-files listing standing in for a real diff: two hunks in one file
# (so a range straddling them is unplaceable), a file named the short way in
# prose, the same basename under two directories, and a file with no patch.
FILES: list[dict[str, Any]] = [
    # The patch-less file leads, as GitHub's own ordering would put it: a walk
    # that stopped at the first entry it could take no spans from would leave
    # every later file unanchorable.
    {"filename": BINARY, "status": "added"},
    {
        "filename": APP_PY,
        "patch": (
            "@@ -1,4 +1,6 @@\n"
            " import json\n"
            "+import re\n"
            "+\n"
            " from typing import Any\n"
            "@@ -40,3 +50,10 @@ def submit_review():\n"
            "-    old()\n"
            "+    new()\n"
        ),
    },
    {"filename": TEST_APPROVE, "patch": "@@ -70,2 +72,5 @@ def test_x():\n+    pass\n"},
    {"filename": NOTES_A, "patch": "@@ -1 +1 @@\n-a\n+b\n"},
    {"filename": NOTES_B, "patch": "@@ -1 +1 @@\n-a\n+b\n"},
]

SPANS = {
    APP_PY: [(1, 6), (50, 59)],
    TEST_APPROVE: [(72, 76)],
    NOTES_A: [(1, 1)],
    NOTES_B: [(1, 1)],
    BINARY: [],
}

BASE_ROUTES: dict[tuple[str, str], tuple[int, Any]] = {
    ("GET", "/app"): (200, {"slug": "pr-hater"}),
    ("GET", "/repos/octo/demo/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", PULL): (200, {"head": {"sha": HEAD}}),
    REVIEWS_PAGE_1: (200, []),
    FILES_PAGE_1: (200, FILES),
    SUBMIT: (200, {"id": 99}),
}


def transport(routes: dict[tuple[str, str], tuple[int, Any]]) -> RouteTableHttp:
    """The App-HTTP fake with its credential rule armed for this App.

    Every construction in this module goes through here, so a call site that
    drops or swaps a credential is refused wherever one is added.
    """
    return RouteTableHttp(routes, app_id=APP_ID)


def finding(finding_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": finding_id, "lens": "correctness", "type": "mechanical", **extra}


def verdict_of(*findings: dict[str, Any], head: str = HEAD) -> Verdict:
    envelope = {"schema_version": "3", "head_sha": head, "findings": list(findings)}
    return Verdict(text=json.dumps(envelope, indent=2), head_sha=head, findings=findings)


def signing_runner() -> RecordedRunner:
    return RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 0a0b\n", "")])


def post(
    verdict: Verdict, routes: dict[tuple[str, str], tuple[int, Any]] | None = None
) -> tuple[str, RouteTableHttp]:
    http = transport(BASE_ROUTES if routes is None else routes)
    message = post_verdict_pr(
        http=http,
        runner=signing_runner(),
        ref=REF,
        verdict=verdict,
        app_id=APP_ID,
        key_path=KEY_PATH,
        now=1_000_000,
    )
    return message, http


def test_the_flow_signs_once_with_the_key_the_caller_named() -> None:
    # The key the caller named is the key the signature is made with. Nothing
    # downstream can tell one key from another — a JWT signed with the wrong one
    # is well-formed, and only GitHub rejects it.
    runner = signing_runner()
    post_verdict_pr(
        http=transport(BASE_ROUTES),
        runner=runner,
        ref=REF,
        verdict=verdict_of(),
        app_id=APP_ID,
        key_path=KEY_PATH,
        now=1_000_000,
    )
    assert [argv[0] for argv in runner.calls] == ["openssl"]
    assert str(KEY_PATH) in runner.calls[0]


class TestTheSubmittedReview:
    def test_the_event_is_comment_and_the_pin_is_the_reviewed_head(self) -> None:
        _, http = post(verdict_of())
        (posted,) = http.posted_reviews()
        assert posted["event"] == "COMMENT"
        assert posted["commit_id"] == HEAD

    def test_the_event_is_never_the_approving_one(self) -> None:
        # A verdict says what a round found; it never says a change may merge, so
        # this path must not be able to produce the review a ruleset counts.
        _, http = post(verdict_of(finding("f1", evidence=f"{APP_PY}:3 is wrong")))
        (posted,) = http.posted_reviews()
        assert posted["event"] != APPROVE_EVENT

    def test_the_body_is_the_verdict_text_byte_for_byte(self) -> None:
        # Deliberately non-canonical spacing: a body rebuilt by re-serializing the
        # parsed envelope would come back normalized and fail here.
        text = '{ "head_sha":"' + HEAD + '",\t"findings":[] }'
        _, http = post(Verdict(text=text, head_sha=HEAD, findings=()))
        (posted,) = http.posted_reviews()
        assert posted["body"] == text

    def test_a_clean_verdict_posts_the_envelope_with_no_inline_comments(self) -> None:
        message, http = post(verdict_of())
        (posted,) = http.posted_reviews()
        assert "comments" not in posted
        assert "with 0 inline comment(s)" in message

    def test_exactly_one_submission_is_made(self) -> None:
        # The verb never submits, sees a rejection, and resubmits a reduced review.
        _, http = post(verdict_of(finding("f1", evidence=f"{APP_PY}:3"), finding("f2")))
        assert len([url for method, url, _, _ in http.calls if method == "POST"]) == 2  # mint + one
        assert len(http.posted_reviews()) == 1


class TestInlineComments:
    def test_a_single_line_anchor_becomes_one_right_side_comment(self) -> None:
        item = finding("f1", evidence=f"{APP_PY}:3 indexes the field directly")
        _, http = post(verdict_of(item))
        (posted,) = http.posted_reviews()
        (comment,) = posted["comments"]
        assert comment["path"] == APP_PY
        assert comment["line"] == 3
        assert comment["side"] == "RIGHT"
        assert "start_line" not in comment

    def test_a_range_anchor_carries_both_ends_of_the_range(self) -> None:
        item = finding("f1", evidence=f"{APP_PY}:50-59 eagerly calls the builder")
        _, http = post(verdict_of(item))
        ((comment,),) = [posted["comments"] for posted in http.posted_reviews()]
        assert (comment["start_line"], comment["line"]) == (50, 59)
        assert comment["start_side"] == comment["side"] == "RIGHT"

    def test_a_comments_body_is_the_findings_own_json(self) -> None:
        item = finding("f1", evidence=f"{APP_PY}:3", claim="a claim", ac="AC-1")
        _, http = post(verdict_of(item))
        ((comment,),) = [posted["comments"] for posted in http.posted_reviews()]
        assert json.loads(comment["body"]) == item

    def test_every_anchored_finding_gets_its_own_comment(self) -> None:
        _, http = post(
            verdict_of(
                finding("f1", evidence=f"{APP_PY}:3"),
                finding("f2", evidence=f"{TEST_APPROVE}:72-76"),
            )
        )
        (posted,) = http.posted_reviews()
        assert [comment["path"] for comment in posted["comments"]] == [APP_PY, TEST_APPROVE]

    def test_two_findings_on_one_line_are_two_comments(self) -> None:
        # No de-duplication: the panel's count is not this verb's to revise.
        _, http = post(
            verdict_of(finding("f1", evidence=f"{APP_PY}:3"), finding("f2", evidence=f"{APP_PY}:3"))
        )
        (posted,) = http.posted_reviews()
        assert len(posted["comments"]) == 2

    def test_an_unplaceable_finding_is_named_on_stdout_and_sends_no_comment(self) -> None:
        message, http = post(verdict_of(finding("f1", evidence="nothing locatable here")))
        (posted,) = http.posted_reviews()
        assert "comments" not in posted
        assert "no line in the diff for finding f1" in message

    def test_the_reported_lines_are_assembled_one_per_line(self) -> None:
        # The whole rendering, not a substring of it: the unplaced findings each
        # get a line and the outcome is the last one, so a caller reading the
        # result reads the final line and nothing is run together.
        message, _ = post(
            verdict_of(
                finding("f1"),
                finding("f2", evidence=f"{APP_PY}:3"),
                finding("f3"),
            )
        )
        assert message == (
            "no line in the diff for finding f1\n"
            "no line in the diff for finding f3\n"
            f"posted: review 99 by {LOGIN} pinned to {HEAD} with 1 inline comment(s)"
        )

    def test_a_file_the_diff_reports_without_a_patch_anchors_nothing(self) -> None:
        message, http = post(verdict_of(finding("f1", evidence=f"{BINARY}:3 changed")))
        assert "comments" not in http.posted_reviews()[0]
        assert "no line in the diff for finding f1" in message


# Every form the corpus of real verdicts writes a location in, plus the forms that
# neighbour it closely enough to be mistaken for one. The expectation is the
# anchor the form must place at, or None when the form places nothing.
ANCHOR_FORMS = [
    pytest.param(f"{APP_PY}:3 indexes it", Anchor(APP_PY, 3, 3), id="a-full-path-and-line"),
    pytest.param(f"{APP_PY}:50-59 calls it", Anchor(APP_PY, 50, 59), id="a-full-path-and-range"),
    pytest.param(f"`{APP_PY}:3` indexes it", Anchor(APP_PY, 3, 3), id="an-anchor-inside-backticks"),
    pytest.param(
        "test_cli_approve.py:72-76 passes it",
        Anchor(TEST_APPROVE, 72, 76),
        id="a-bare-filename-and-range",
    ),
    pytest.param(
        "unit/test_cli_approve.py:74 passes it",
        Anchor(TEST_APPROVE, 74, 74),
        id="a-partial-path-and-line",
    ),
    pytest.param(
        f"the anchor is at the end: {APP_PY}:3",
        Anchor(APP_PY, 3, 3),
        id="an-anchor-ending-the-text",
    ),
    pytest.param(
        f"{APP_PY}:3 and {TEST_APPROVE}:74", Anchor(APP_PY, 3, 3), id="the-first-of-two-anchors"
    ),
    pytest.param(
        f"{BINARY}:3 and {APP_PY}:3",
        Anchor(APP_PY, 3, 3),
        id="the-first-placeable-of-two-anchors",
    ),
    pytest.param(
        f"nowhere/missing.py:3 and {APP_PY}:3",
        Anchor(APP_PY, 3, 3),
        id="an-unresolvable-path-before-a-resolvable-one",
    ),
    pytest.param(
        f"{APP_PY}:59-50 and {APP_PY}:3",
        Anchor(APP_PY, 3, 3),
        id="a-reversed-range-before-a-placeable-one",
    ),
    pytest.param("gh/app.py:_decode_hex_signature uses it", None, id="a-path-and-symbol"),
    pytest.param("docs/architecture/prgroom/design.md says so", None, id="a-path-with-no-line"),
    pytest.param("test_config_approver.py (lines 78-91)", None, id="line-numbers-written-as-prose"),
    pytest.param("notes.md:1 changed", None, id="a-basename-two-changed-files-share"),
    pytest.param("some/other/module.py:3 is wrong", None, id="a-file-the-diff-does-not-touch"),
    pytest.param(f"{APP_PY}:900 is wrong", None, id="a-line-outside-every-hunk"),
    pytest.param(f"{APP_PY}:6-50 spans them", None, id="a-range-straddling-two-hunks"),
    pytest.param(f"{APP_PY}:59-50 is backwards", None, id="a-reversed-range"),
    pytest.param(f"{APP_PY}:0 is wrong", None, id="a-line-before-the-file-starts"),
    pytest.param("version 1.2:3 shipped", None, id="a-numeric-token-that-is-not-a-path"),
]


@pytest.mark.parametrize(("evidence", "expected"), ANCHOR_FORMS)
def test_each_anchor_form_places_where_it_must(evidence: str, expected: Anchor | None) -> None:
    assert place_anchor(finding("f1", evidence=evidence), SPANS) == expected


@pytest.mark.parametrize(("text", "expected"), ANCHOR_FORMS)
def test_the_claim_is_read_when_the_evidence_names_nothing(
    text: str, expected: Anchor | None
) -> None:
    # Locations usually sit in the evidence, occasionally in the claim; a finding
    # that only states where it looked in its claim still anchors there.
    assert place_anchor(finding("f1", claim=text), SPANS) == expected


def test_the_evidence_is_preferred_over_the_claim() -> None:
    item = finding("f1", claim=f"{TEST_APPROVE}:74", evidence=f"{APP_PY}:3")
    assert place_anchor(item, SPANS) == Anchor(APP_PY, 3, 3)


def test_a_finding_carrying_neither_field_anchors_nothing() -> None:
    assert place_anchor(finding("f1"), SPANS) is None


HUNK_HEADERS = [
    pytest.param("@@ -1,4 +10,3 @@\n context\n", [(10, 12)], id="both-counts-present"),
    pytest.param("@@ -1 +10 @@\n-a\n+b\n", [(10, 10)], id="both-counts-omitted"),
    pytest.param("@@ -1,4 +10 @@\n+a\n", [(10, 10)], id="the-new-count-omitted"),
    pytest.param("@@ -1 +10,3 @@\n+a\n", [(10, 12)], id="the-old-count-omitted"),
    pytest.param("@@ -5,3 +10,0 @@\n-a\n", [], id="a-hunk-that-adds-no-new-side-line"),
    pytest.param(
        "@@ -1,2 +1,2 @@ def f():\n-a\n+b\n@@ -8,1 +8,4 @@ def g():\n+c\n",
        [(1, 2), (8, 11)],
        id="two-hunks-with-section-headings",
    ),
    pytest.param("", [], id="an-empty-patch"),
    pytest.param("no hunk header at all\n", [], id="a-patch-with-no-header"),
    pytest.param(
        " a line that mentions @@ -1,4 +10,3 @@ mid-line\n", [], id="a-header-shape-inside-a-line"
    ),
]


@pytest.mark.parametrize(("patch", "expected"), HUNK_HEADERS)
def test_each_hunk_header_form_yields_its_right_side_span(
    patch: str, expected: list[tuple[int, int]]
) -> None:
    assert commentable_spans(patch) == expected


class TestTheHeadItReviewed:
    def test_a_live_head_past_the_reviewed_one_refuses_before_any_submission(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        http = transport(routes)
        with pytest.raises(PreconditionError) as caught:
            post_verdict_pr(
                http=http,
                runner=signing_runner(),
                ref=REF,
                verdict=verdict_of(),
                app_id=APP_ID,
                key_path=KEY_PATH,
                now=1_000_000,
            )
        assert caught.value.code is ErrorCode.PRECONDITION_APPROVER_HEAD_MOVED
        assert http.posted_reviews() == []

    def test_the_refusal_reads_the_head_before_it_reads_the_diff(self) -> None:
        # Nothing is spent listing a diff for a verdict that cannot be posted.
        routes = dict(BASE_ROUTES)
        routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        http = transport(routes)
        with pytest.raises(PreconditionError):
            post_verdict_pr(
                http=http,
                runner=signing_runner(),
                ref=REF,
                verdict=verdict_of(),
                app_id=APP_ID,
                key_path=KEY_PATH,
                now=1_000_000,
            )
        assert not [url for _, url, _, _ in http.calls if "/files" in url]


class TestPostingTwiceIsANoOp:
    def existing(self, **overrides: Any) -> dict[str, Any]:
        text = verdict_of().text
        return {
            "id": 7,
            "commit_id": HEAD,
            "body": text,
            "user": {"login": LOGIN},
            "state": "COMMENTED",
            **overrides,
        }

    def routes_with_review(self, review: dict[str, Any]) -> dict[tuple[str, str], tuple[int, Any]]:
        routes = dict(BASE_ROUTES)
        routes[REVIEWS_PAGE_1] = (200, [review])
        return routes

    def test_the_same_verdict_at_the_same_head_posts_nothing_and_names_the_review(self) -> None:
        message, http = post(verdict_of(), self.routes_with_review(self.existing()))
        assert http.posted_reviews() == []
        assert "review 7" in message
        assert "nothing posted" in message

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"commit_id": MOVED}, id="the-same-text-at-another-head"),
            pytest.param({"body": "a different verdict"}, id="another-text-at-this-head"),
            pytest.param({"user": {"login": "someone-else"}}, id="another-identity"),
            pytest.param({"body": ""}, id="an-empty-body"),
        ],
    )
    def test_a_review_that_is_not_this_verdict_does_not_suppress_the_post(
        self, overrides: dict[str, Any]
    ) -> None:
        _, http = post(verdict_of(), self.routes_with_review(self.existing(**overrides)))
        assert len(http.posted_reviews()) == 1

    def test_the_apps_own_approval_at_the_head_does_not_suppress_the_verdict(self) -> None:
        # The approval and the verdict are two separate reviews; finding one must
        # never be read as having posted the other.
        approval = self.existing(state="APPROVED", body="Automated attestation")
        _, http = post(verdict_of(), self.routes_with_review(approval))
        assert len(http.posted_reviews()) == 1


def test_a_second_page_of_files_is_read_before_anchors_are_placed() -> None:
    # A file an anchor names can sit past page 1; a listing stopped at the first
    # full page would silently demote a placeable anchor to body-only.
    first = [{"filename": f"filler/{index}.py", "patch": ""} for index in range(FILES_PER_PAGE)]
    routes = dict(BASE_ROUTES)
    routes[FILES_PAGE_1] = (200, first)
    routes[("GET", f"{PULL}/files?per_page={FILES_PER_PAGE}&page=2")] = (200, FILES)
    _, http = post(verdict_of(finding("f1", evidence=f"{APP_PY}:3")), routes)
    (posted,) = http.posted_reviews()
    assert posted["comments"][0]["path"] == APP_PY


def test_build_comments_reports_the_unplaced_in_the_order_they_arrived() -> None:
    comments, unplaced = build_comments(
        [finding("f1"), finding("f2", evidence=f"{APP_PY}:3"), finding("f3")], SPANS
    )
    assert unplaced == ["f1", "f3"]
    assert len(comments) == 1
