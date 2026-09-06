"""Behaviour tests for the GitHub App client.

All GitHub traffic goes through an injected route-table transport and all signing
through the recorded-runner fake, so nothing here reaches the network, a key, or
``openssl``. Each test pins a decision the client makes — the JWT's claims, the
token's scope, the pagination walk — never a stdlib behaviour.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from prgroom.errors import ErrorCode, PrgroomError
from prgroom.gh.app import (
    GITHUB_API,
    REVIEWS_PER_PAGE,
    build_jwt,
    iter_reviews,
    mint_installation_token,
    openssl_signer,
    read_head_sha,
    submit_review,
)
from prgroom.proc import CommandResult
from prgroom.prsession.pr_ref import PRRef
from tests.fakes import (
    MissingBinaryRunner,
    RecordedRunner,
    RouteTableHttp,
    TimeoutRunner,
)

NOW = 1_000_000
HEAD = "a" * 40
KEY_PATH = Path("/keys/app.pem")
REF = PRRef(owner="octo", repo="demo", number=5)


def fake_signer(payload: str) -> bytes:  # noqa: ARG001  # fixed signature for determinism
    return b"SIGNATURE"


BASE_ROUTES: dict[tuple[str, str], tuple[int, Any]] = {
    ("GET", "/app"): (200, {"slug": "pr-hater"}),
    ("GET", "/repos/octo/demo/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", "/repos/octo/demo/pulls/5"): (200, {"head": {"sha": HEAD}}),
    ("GET", f"/repos/octo/demo/pulls/5/reviews?per_page={REVIEWS_PER_PAGE}&page=1"): (200, []),
    ("POST", "/repos/octo/demo/pulls/5/reviews"): (200, {"id": 99}),
}


def unpad_b64url(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


class TestJwt:
    def test_claims_carry_backdated_iat_short_exp_and_the_app_id_as_issuer(self) -> None:
        token = build_jwt(123456, NOW, fake_signer)
        header_b64, claims_b64, signature_b64 = token.split(".")
        assert json.loads(unpad_b64url(header_b64)) == {"alg": "RS256", "typ": "JWT"}
        assert json.loads(unpad_b64url(claims_b64)) == {
            "iat": NOW - 60,
            "exp": NOW + 540,
            "iss": "123456",
        }
        assert unpad_b64url(signature_b64) == b"SIGNATURE"

    def test_no_segment_carries_base64_padding(self) -> None:
        # JOSE segments are unpadded base64url; a '=' anywhere means the encoding
        # is wrong and GitHub rejects the token.
        assert "=" not in build_jwt(1, NOW, fake_signer)

    def test_the_signed_input_is_the_header_and_claims_segments(self) -> None:
        seen: list[str] = []

        def recording_signer(payload: str) -> bytes:
            seen.append(payload)
            return b"S"

        token = build_jwt(7, NOW, recording_signer)
        assert seen == [token.rsplit(".", 1)[0]]


class TestOpensslSigner:
    def test_signs_via_the_runner_seam_with_hex_output_and_no_passphrase_prompt(self) -> None:
        runner = RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 0a0b0c\n", "")])
        signature = openssl_signer(runner, KEY_PATH)("header.claims")
        assert signature == bytes.fromhex("0a0b0c")
        (argv,) = runner.calls
        assert argv[:5] == ["openssl", "dgst", "-sha256", "-sign", str(KEY_PATH)]
        assert "-hex" in argv
        # An empty passphrase makes an encrypted key fail immediately instead of
        # blocking on a terminal prompt the runner would never answer.
        assert argv[-2:] == ["-passin", "pass:"]
        assert runner.inputs == ["header.claims"]

    def test_hex_body_is_taken_after_the_algorithm_label_whatever_it_is(self) -> None:
        # Older openssl labels the line "RSA-SHA256(stdin)="; the parse must not
        # depend on which label this build prints.
        runner = RecordedRunner([CommandResult(0, "RSA-SHA256(stdin)= ff00\n", "")])
        assert openssl_signer(runner, KEY_PATH)("x") == b"\xff\x00"

    def test_missing_openssl_binary_is_a_coded_sign_failure(self) -> None:
        with pytest.raises(PrgroomError) as caught:
            openssl_signer(MissingBinaryRunner(), KEY_PATH)("x")
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_SIGN_FAILED

    def test_a_hung_openssl_is_a_coded_sign_failure_not_a_raw_timeout(self) -> None:
        with pytest.raises(PrgroomError) as caught:
            openssl_signer(TimeoutRunner(), KEY_PATH)("x")
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_SIGN_FAILED

    def test_nonzero_openssl_exit_surfaces_its_stderr_in_the_detail(self) -> None:
        runner = RecordedRunner([CommandResult(1, "", "bad decrypt")])
        with pytest.raises(PrgroomError) as caught:
            openssl_signer(runner, KEY_PATH)("x")
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_SIGN_FAILED
        assert "bad decrypt" in caught.value.detail

    def test_empty_signature_output_fails_rather_than_signing_with_nothing(self) -> None:
        runner = RecordedRunner([CommandResult(0, "SHA2-256(stdin)= \n", "")])
        with pytest.raises(PrgroomError) as caught:
            openssl_signer(runner, KEY_PATH)("x")
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_SIGN_FAILED

    def test_non_hex_signature_output_fails_rather_than_being_truncated(self) -> None:
        runner = RecordedRunner([CommandResult(0, "SHA2-256(stdin)= zzzz\n", "")])
        with pytest.raises(PrgroomError) as caught:
            openssl_signer(runner, KEY_PATH)("x")
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_SIGN_FAILED


class TestMint:
    def test_token_is_scoped_to_the_single_repo_and_pull_requests_write(self) -> None:
        http = RouteTableHttp(BASE_ROUTES)
        minted = mint_installation_token(http, "jwt", REF)
        assert minted.token == "tok"  # noqa: S105  # a fake mint response, not a secret
        (scope,) = http.bodies_posted_to("/access_tokens")
        assert scope["repositories"] == ["demo"]
        assert scope["permissions"] == {"pull_requests": "write"}

    def test_login_is_derived_from_the_slug_the_api_reports(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", "/app")] = (200, {"slug": "renamed-app"})
        assert (
            mint_installation_token(RouteTableHttp(routes), "jwt", REF).login == "renamed-app[bot]"
        )

    def test_a_404_installation_is_its_own_code_not_a_generic_api_failure(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/octo/demo/installation")] = (404, {"message": "Not Found"})
        with pytest.raises(PrgroomError) as caught:
            mint_installation_token(RouteTableHttp(routes), "jwt", REF)
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_NOT_INSTALLED

    def test_a_rejected_mint_fails_loud_with_the_status_in_the_detail(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("POST", "/app/installations/42/access_tokens")] = (
            401,
            {"message": "bad credentials"},
        )
        with pytest.raises(PrgroomError) as caught:
            mint_installation_token(RouteTableHttp(routes), "jwt", REF)
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED
        assert "401" in caught.value.detail

    def test_a_failed_app_lookup_fails_before_any_installation_call(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", "/app")] = (500, {"message": "boom"})
        http = RouteTableHttp(routes)
        with pytest.raises(PrgroomError) as caught:
            mint_installation_token(http, "jwt", REF)
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED
        assert [url for _, url, _, _ in http.calls] == [f"{GITHUB_API}/app"]

    def test_an_installation_status_that_is_neither_200_nor_404_fails_loud(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/octo/demo/installation")] = (403, {"message": "no"})
        with pytest.raises(PrgroomError) as caught:
            mint_installation_token(RouteTableHttp(routes), "jwt", REF)
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED


class TestReads:
    def test_head_sha_is_read_from_the_live_pull_request(self) -> None:
        assert read_head_sha(RouteTableHttp(BASE_ROUTES), "tok", REF) == HEAD

    def test_reviews_walk_every_page_when_the_first_comes_back_full(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("GET", f"/repos/octo/demo/pulls/5/reviews?per_page={REVIEWS_PER_PAGE}&page=1")] = (
            200,
            [{"id": i} for i in range(REVIEWS_PER_PAGE)],
        )
        routes[("GET", f"/repos/octo/demo/pulls/5/reviews?per_page={REVIEWS_PER_PAGE}&page=2")] = (
            200,
            [{"id": 500}],
        )
        ids = [review["id"] for review in iter_reviews(RouteTableHttp(routes), "tok", REF)]
        assert ids[-1] == 500
        assert len(ids) == REVIEWS_PER_PAGE + 1

    def test_a_short_first_page_stops_the_walk(self) -> None:
        http = RouteTableHttp(BASE_ROUTES)
        assert list(iter_reviews(http, "tok", REF)) == []
        assert len(http.calls) == 1


class TestSubmitReview:
    def test_the_event_is_a_parameter_so_a_comment_review_rides_the_same_call(self) -> None:
        http = RouteTableHttp(BASE_ROUTES)
        review_id = submit_review(
            http, "tok", REF, event="COMMENT", body="a verdict", commit_id=HEAD
        )
        assert review_id == 99
        (posted,) = http.bodies_posted_to("/reviews")
        assert posted == {"event": "COMMENT", "commit_id": HEAD, "body": "a verdict"}

    def test_a_rejected_submission_fails_loud(self) -> None:
        routes = dict(BASE_ROUTES)
        routes[("POST", "/repos/octo/demo/pulls/5/reviews")] = (422, {"message": "unprocessable"})
        with pytest.raises(PrgroomError) as caught:
            submit_review(
                RouteTableHttp(routes), "tok", REF, event="APPROVE", body="b", commit_id=HEAD
            )
        assert caught.value.code is ErrorCode.RUNTIME_APPROVER_API_FAILED
        assert "422" in caught.value.detail


class TestSignerTimeoutIsBounded:
    def test_the_signer_passes_a_timeout_so_a_hung_openssl_cannot_block_forever(self) -> None:
        runner = RecordedRunner([CommandResult(0, "SHA2-256(stdin)= 00\n", "")])
        openssl_signer(runner, KEY_PATH)("x")
        assert runner.timeouts == [pytest.approx(30.0)]


def test_timeout_fake_raises_the_stdlib_timeout_the_signer_catches() -> None:
    # Guards the fake itself: if TimeoutRunner stopped raising TimeoutExpired the
    # signer's timeout arm above would pass for the wrong reason.
    with pytest.raises(subprocess.TimeoutExpired):
        TimeoutRunner().run(["openssl"])
