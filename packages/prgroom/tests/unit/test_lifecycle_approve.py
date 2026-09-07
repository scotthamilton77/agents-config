"""Behaviour tests for the ``approve`` verb body.

The flow drives an injected route-table transport and a recorded runner, so a
POST that should not happen is observable as an empty call list rather than as a
live review on somebody's PR.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest

from prgroom.config import ApproverConfig
from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.app import REVIEWS_PER_PAGE
from prgroom.lifecycle.approve import approve_pr, attestation_body, resolve_key_path
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import RecordedRunner, RouteTableHttp

HEAD = "a" * 40
MOVED = "b" * 40
APP_LOGIN = "pr-hater[bot]"
FACTS = '{"instruction": "merge the stack"}'
NOW = 1_000_000
APP_ID = 4275336
KEY_PATH = Path("/keys/app.pem")
REF = PRRef(owner="octo", repo="demo", number=5)

PULL = "/repos/octo/demo/pulls/5"
REVIEWS_PAGE_1 = ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=1")
REVIEWS_PAGE_2 = ("GET", f"{PULL}/reviews?per_page={REVIEWS_PER_PAGE}&page=2")

Routes = dict[tuple[str, str], tuple[int, Any]]

BASE_ROUTES: Routes = {
    ("GET", "/app"): (200, {"slug": "pr-hater"}),
    ("GET", "/repos/octo/demo/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", PULL): (200, {"head": {"sha": HEAD}}),
    REVIEWS_PAGE_1: (200, []),
    ("POST", f"{PULL}/reviews"): (200, {"id": 99}),
}


def transport(routes: dict[tuple[str, str], tuple[int, Any]]) -> RouteTableHttp:
    """The App-HTTP fake with its credential rule armed for this App.

    Every construction in this module goes through here, so a call site that
    drops or swaps a credential is refused wherever one is added.
    """
    return RouteTableHttp(routes, app_id=APP_ID)


def signing_runner() -> RecordedRunner:
    """A runner answering the one ``openssl`` call the flow makes."""
    return RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 0a0b\n", "")])


def run_approve(routes: Routes) -> tuple[str, RouteTableHttp]:
    http = transport(routes)
    message = approve_pr(
        http=http,
        runner=signing_runner(),
        ref=REF,
        head_sha=HEAD,
        facts=FACTS,
        app_id=APP_ID,
        key_path=KEY_PATH,
        now=NOW,
    )
    return message, http


class TestHappyPath:
    def test_posts_an_approve_pinned_to_the_named_head_with_the_facts_verbatim(self) -> None:
        message, http = run_approve(dict(BASE_ROUTES))
        (posted,) = http.posted_reviews()
        assert posted["event"] == "APPROVE"
        assert posted["commit_id"] == HEAD
        assert FACTS in posted["body"]
        assert APP_LOGIN in posted["body"]
        assert HEAD in posted["body"]
        assert "not a human review" in posted["body"]
        assert message == f"approved: review 99 by {APP_LOGIN} pinned to {HEAD}"

    def test_the_posted_body_is_the_attestation_body(self) -> None:
        _, http = run_approve(dict(BASE_ROUTES))
        (posted,) = http.posted_reviews()
        assert posted["body"] == attestation_body(APP_LOGIN, HEAD, FACTS)

    def test_the_flow_signs_once_through_the_runner_seam(self) -> None:
        runner = signing_runner()
        approve_pr(
            http=transport(dict(BASE_ROUTES)),
            runner=runner,
            ref=REF,
            head_sha=HEAD,
            facts=FACTS,
            app_id=APP_ID,
            key_path=KEY_PATH,
            now=NOW,
        )
        assert [argv[0] for argv in runner.calls] == ["openssl"]
        # The key the caller named is the key the signature is made with. Nothing
        # downstream can tell one key from another — a JWT signed with the wrong
        # one is well-formed, and only GitHub rejects it.
        assert str(KEY_PATH) in runner.calls[0]

    def test_the_jwt_it_mints_with_issues_from_the_configured_app_id(self) -> None:
        _, http = run_approve(dict(BASE_ROUTES))
        (_, _, headers, _) = http.calls[0]
        claims = headers["Authorization"].removeprefix("Bearer ").split(".")[1]
        decoded = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
        assert decoded["iss"] == str(APP_ID)


class TestIdempotence:
    def test_an_existing_app_approval_at_the_head_posts_nothing(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[REVIEWS_PAGE_1] = (
            200,
            [{"id": 7, "state": "APPROVED", "commit_id": HEAD, "user": {"login": APP_LOGIN}}],
        )
        message, http = run_approve(routes)
        assert http.posted_reviews() == []
        assert "already approved" in message
        assert "review 7" in message

    def test_a_prior_approval_beyond_page_one_is_still_found(self) -> None:
        # Reviews arrive oldest-first, so on a heavily-reviewed PR the App's own
        # approval sits past page 1; missing it would post a duplicate.
        routes = dict(BASE_ROUTES)
        routes[REVIEWS_PAGE_1] = (
            200,
            [
                {"id": i, "state": "COMMENTED", "commit_id": HEAD, "user": {"login": "a-human"}}
                for i in range(REVIEWS_PER_PAGE)
            ],
        )
        routes[REVIEWS_PAGE_2] = (
            200,
            [{"id": 500, "state": "APPROVED", "commit_id": HEAD, "user": {"login": APP_LOGIN}}],
        )
        message, http = run_approve(routes)
        assert http.posted_reviews() == []
        assert "review 500" in message

    @pytest.mark.parametrize(
        "review",
        [
            pytest.param(
                {"id": 1, "state": "APPROVED", "commit_id": MOVED, "user": {"login": APP_LOGIN}},
                id="the-apps-approval-of-an-earlier-head",
            ),
            pytest.param(
                {"id": 2, "state": "COMMENTED", "commit_id": HEAD, "user": {"login": APP_LOGIN}},
                id="a-comment-only-review-by-the-app",
            ),
            pytest.param(
                {"id": 3, "state": "APPROVED", "commit_id": HEAD, "user": {"login": "a-human"}},
                id="someone-elses-approval-at-the-head",
            ),
            pytest.param(
                {"id": 4, "state": "APPROVED", "commit_id": HEAD, "user": None},
                id="a-review-with-no-user-attached",
            ),
        ],
    )
    def test_a_near_miss_review_does_not_short_circuit_the_approval(
        self, review: dict[str, Any]
    ) -> None:
        routes = dict(BASE_ROUTES)
        routes[REVIEWS_PAGE_1] = (200, [review])
        _, http = run_approve(routes)
        assert len(http.posted_reviews()) == 1


class TestHeadMoved:
    def test_a_moved_live_head_refuses_without_posting_or_even_listing_reviews(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        http = transport(routes)
        with pytest.raises(PreconditionError) as caught:
            approve_pr(
                http=http,
                runner=signing_runner(),
                ref=REF,
                head_sha=HEAD,
                facts=FACTS,
                app_id=APP_ID,
                key_path=KEY_PATH,
                now=NOW,
            )
        assert caught.value.code is ErrorCode.PRECONDITION_APPROVER_HEAD_MOVED
        assert http.posted_reviews() == []
        assert not any("/reviews" in url for _, url, _, _ in http.calls)

    def test_the_refusal_detail_names_both_the_live_head_and_the_named_one(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", PULL)] = (200, {"head": {"sha": MOVED}})
        with pytest.raises(PreconditionError) as caught:
            run_approve(routes)
        assert MOVED in caught.value.detail
        assert HEAD in caught.value.detail


class TestAttestationBody:
    def test_names_itself_non_human_and_carries_the_head_and_facts(self) -> None:
        body = attestation_body(APP_LOGIN, HEAD, FACTS)
        assert "not a human review" in body
        assert f"`{HEAD}`" in body
        assert FACTS in body
        assert APP_LOGIN in body

    @pytest.mark.parametrize(
        "claim", ["CI", "green", "triage", "triaged", "policy", "satisfied", "passed"]
    )
    def test_claims_no_outcome_of_its_own(self, claim: str) -> None:
        # The body must not assert a CI, triage, or policy result it never
        # checked; the caller's facts carry whatever was actually established.
        assert claim not in attestation_body(APP_LOGIN, HEAD, "{}")

    def test_the_body_says_authorization_is_decided_elsewhere(self) -> None:
        assert "authorization is decided outside this review" in attestation_body(
            APP_LOGIN, HEAD, "{}"
        )


class TestResolveKeyPath:
    def test_reads_the_path_from_the_environment_variable_the_config_names(
        self, tmp_path: Path
    ) -> None:
        key = tmp_path / "app.pem"
        key.write_text("-----BEGIN PRIVATE KEY-----\n")
        approver = ApproverConfig(app_id=1, key_path_env="APP_KEY")
        assert resolve_key_path(approver, {"APP_KEY": str(key)}) == key

    def test_an_unset_variable_is_its_own_code(self) -> None:
        approver = ApproverConfig(app_id=1, key_path_env="APP_KEY")
        with pytest.raises(PreconditionError) as caught:
            resolve_key_path(approver, {})
        assert caught.value.code is ErrorCode.PRECONDITION_APPROVER_KEY_ENV_UNSET

    def test_a_blank_variable_is_treated_as_unset_not_as_a_path(self) -> None:
        approver = ApproverConfig(app_id=1, key_path_env="APP_KEY")
        with pytest.raises(PreconditionError) as caught:
            resolve_key_path(approver, {"APP_KEY": "   "})
        assert caught.value.code is ErrorCode.PRECONDITION_APPROVER_KEY_ENV_UNSET

    def test_an_unreadable_key_is_a_different_code_from_an_unset_variable(
        self, tmp_path: Path
    ) -> None:
        approver = ApproverConfig(app_id=1, key_path_env="APP_KEY")
        missing = tmp_path / "nowhere" / "app.pem"
        with pytest.raises(PreconditionError) as caught:
            resolve_key_path(approver, {"APP_KEY": str(missing)})
        assert caught.value.code is ErrorCode.PRECONDITION_APPROVER_KEY_UNREADABLE


def test_the_facts_string_reaches_the_body_byte_for_byte() -> None:
    # Non-canonical on purpose: spacing and key order json.dumps would not
    # reproduce, so a body built by re-serializing the input fails here.
    facts = '{ "rule":"instructed",   "b":1,\t"a":[2,3] }'
    http = transport(dict(BASE_ROUTES))
    approve_pr(
        http=http,
        runner=signing_runner(),
        ref=REF,
        head_sha=HEAD,
        facts=facts,
        app_id=APP_ID,
        key_path=KEY_PATH,
        now=NOW,
    )
    (posted,) = http.posted_reviews()
    assert facts in posted["body"]


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param("/pulls/5", id="the-live-head-read"),
        pytest.param("&page=1", id="the-reviews-listing"),
        pytest.param("/reviews", id="the-review-submission"),
    ],
)
def test_every_call_after_the_mint_carries_the_installation_token(tail: str) -> None:
    # The JWT authenticates the App, not its installation; a PR-scoped call made
    # with it would be refused, and one made with no credential would act as
    # whoever the transport happens to be.
    _, http = run_approve(dict(BASE_ROUTES))
    authorized = [
        headers.get("Authorization") for _, url, headers, _ in http.calls if url.endswith(tail)
    ]
    assert authorized
    assert set(authorized) == {"Bearer tok"}


def test_a_key_that_exists_but_cannot_be_read_is_the_unreadable_error(tmp_path: Path) -> None:
    # Distinct from a path that is not there: the key is present and the process
    # simply may not open it, which a handler narrowed to a missing file misses.
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file, so the failure cannot be provoked")
    key = tmp_path / "app.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\n")
    key.chmod(0o000)
    approver = ApproverConfig(app_id=1, key_path_env="APP_KEY")
    try:
        with pytest.raises(PreconditionError) as caught:
            resolve_key_path(approver, {"APP_KEY": str(key)})
    finally:
        key.chmod(0o600)
    assert caught.value.code is ErrorCode.PRECONDITION_APPROVER_KEY_UNREADABLE


def test_a_full_page_with_no_match_is_followed_by_the_next_one() -> None:
    # A page of exactly the page size is the boundary: it carries no signal that
    # it is the last, so the walk must ask again before concluding there is no
    # approval and posting one.
    routes = dict(BASE_ROUTES)
    routes[REVIEWS_PAGE_1] = (
        200,
        [
            {"id": i, "state": "COMMENTED", "commit_id": HEAD, "user": {"login": "a-human"}}
            for i in range(REVIEWS_PER_PAGE)
        ],
    )
    routes[REVIEWS_PAGE_2] = (200, [])
    _, http = run_approve(routes)
    listings = [url for _, url, _, _ in http.calls if "/reviews?" in url]
    assert len(listings) == 2
    assert len(http.posted_reviews()) == 1


def test_a_match_on_a_page_reached_only_by_the_boundary_walk_short_circuits() -> None:
    routes = dict(BASE_ROUTES)
    routes[REVIEWS_PAGE_1] = (
        200,
        [
            {"id": i, "state": "COMMENTED", "commit_id": HEAD, "user": {"login": "a-human"}}
            for i in range(REVIEWS_PER_PAGE)
        ],
    )
    routes[REVIEWS_PAGE_2] = (
        200,
        [{"id": 500, "state": "APPROVED", "commit_id": HEAD, "user": {"login": APP_LOGIN}}],
    )
    message, http = run_approve(routes)
    assert http.posted_reviews() == []
    assert "review 500" in message
