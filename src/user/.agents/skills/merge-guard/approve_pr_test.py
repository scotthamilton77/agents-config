#!/usr/bin/env python3
"""Unit tests for approve_pr.py (stdlib unittest; run via approve_pr_test.sh).

All GitHub traffic goes through an injected fake transport; signing through a
fake signer. No network, no keys, no repo-internal paths.
"""
import base64
import json
import subprocess
import unittest

import approve_pr


def b64pad(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


FAKE_SIGNER = lambda data: b"SIGNATURE"  # noqa: E731 - deliberate tiny fake
NOW = 1_000_000


class TestJwt(unittest.TestCase):
    def test_claims_pin_our_construction_choices(self):
        token = approve_pr.build_jwt(app_id=123456, now=NOW, signer=FAKE_SIGNER)
        header_b64, claims_b64, sig_b64 = token.split(".")
        self.assertEqual(json.loads(b64pad(header_b64)),
                         {"alg": "RS256", "typ": "JWT"})
        self.assertEqual(json.loads(b64pad(claims_b64)),
                         {"iat": NOW - 60, "exp": NOW + 540, "iss": "123456"})
        self.assertEqual(b64pad(sig_b64), b"SIGNATURE")

    def test_no_base64_padding_in_any_segment(self):
        token = approve_pr.build_jwt(app_id=1, now=NOW, signer=FAKE_SIGNER)
        self.assertNotIn("=", token)


class TestAttestationBody(unittest.TestCase):
    """The body is an honest attestation: it names itself as non-human, carries
    the head SHA and the verbatim facts, and asserts NO rule-specific outcome
    (CI status, triage state) that varies by which merge rule authorized it."""

    def test_names_itself_non_human_and_carries_head_and_facts(self):
        body = approve_pr.attestation_body(
            "merge-guard-approver", HEAD, '{"rule": "agent-ruling"}')
        self.assertIn("not a human review", body)
        self.assertIn(f"`{HEAD}`", body)
        self.assertIn('{"rule": "agent-ruling"}', body)

    def test_makes_no_rule_specific_outcome_claim(self):
        body = approve_pr.attestation_body("slug", HEAD, "{}")
        self.assertIn("authorized under this repo's merge policy", body)
        self.assertNotIn("CI green", body)
        self.assertNotIn("triaged", body)


class TestOpensslSigner(unittest.TestCase):
    """openssl invocation failures are expected environment errors, not bugs:
    they must surface as ApproveError (fail-loud, one-line diagnostic), not fall
    through to the generic 'unexpected' catch-all."""

    class _FakeSubprocess:
        TimeoutExpired = subprocess.TimeoutExpired

        def __init__(self, run_impl):
            self.run = run_impl

    def _sign_with(self, run_impl):
        original = approve_pr.subprocess
        approve_pr.subprocess = self._FakeSubprocess(run_impl)
        try:
            return approve_pr.openssl_signer("/irrelevant/key.pem")(b"payload")
        finally:
            approve_pr.subprocess = original

    def test_missing_openssl_binary_raises_approve_error(self):
        def raise_not_found(*a, **k):
            raise FileNotFoundError(2, "No such file or directory", "openssl")
        with self.assertRaises(approve_pr.ApproveError) as ctx:
            self._sign_with(raise_not_found)
        self.assertIn("openssl", str(ctx.exception).lower())

    def test_signing_timeout_raises_approve_error(self):
        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd="openssl", timeout=30)
        with self.assertRaises(approve_pr.ApproveError) as ctx:
            self._sign_with(raise_timeout)
        self.assertIn("timed out", str(ctx.exception).lower())


class FakeHttp:
    """Route-table fake transport. Records every call for behavior assertions."""

    def __init__(self, routes):
        self.routes = routes  # {(method, url-suffix-after-API): (status, payload)}
        self.calls = []       # [(method, url, headers, body)]

    def __call__(self, method, url, headers, body=None):
        self.calls.append((method, url, headers, body))
        for (m, suffix), response in self.routes.items():
            if m == method and url == approve_pr.API + suffix:
                return response
        raise AssertionError(f"unexpected call: {method} {url}")

    def posted_reviews(self):
        return [json.loads(b) for m, u, _, b in self.calls
                if m == "POST" and u.endswith("/reviews")]


HEAD = "a" * 40
MOVED = "b" * 40

BASE_ROUTES = {
    ("GET", "/app"): (200, {"slug": "merge-guard-approver"}),
    ("GET", "/repos/o/r/installation"): (200, {"id": 42}),
    ("POST", "/app/installations/42/access_tokens"): (201, {"token": "tok"}),
    ("GET", "/repos/o/r/pulls/5"): (200, {"head": {"sha": HEAD}}),
    ("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=1"): (200, []),
    ("POST", "/repos/o/r/pulls/5/reviews"): (200, {"id": 99}),
}

ARGS = ["--repo", "o/r", "--pr", "5", "--head-sha", HEAD,
        "--app-id", "123456", "--key-path", "/dev/null",
        "--facts", '{"rule": "bot-quiescence"}']


def run_main(routes):
    http = FakeHttp(routes)
    code = approve_pr.main(
        ARGS, http=http, signer_factory=lambda path: FAKE_SIGNER,
        clock=lambda: NOW)
    return code, http


class TestFlow(unittest.TestCase):
    def test_happy_path_posts_pinned_attestation(self):
        code, http = run_main(dict(BASE_ROUTES))
        self.assertEqual(code, 0)
        (review,) = http.posted_reviews()
        self.assertEqual(review["event"], "APPROVE")
        self.assertEqual(review["commit_id"], HEAD)
        self.assertIn("not a human review", review["body"])
        self.assertIn('{"rule": "bot-quiescence"}', review["body"])

    def test_mint_scopes_installation_token_to_repo_and_pulls_write(self):
        code, http = run_main(dict(BASE_ROUTES))
        self.assertEqual(code, 0)
        (mint_body,) = [json.loads(b) for m, u, _, b in http.calls
                        if m == "POST" and u.endswith("/access_tokens")]
        self.assertEqual(mint_body["repositories"], ["r"])
        self.assertEqual(mint_body["permissions"], {"pull_requests": "write"})

    def test_paginates_reviews_to_find_prior_approval_beyond_page_one(self):
        # A full first page (100 reviews) forces a second GET; the App's
        # approval at HEAD lives on page 2. Without pagination it is missed
        # and a duplicate approval gets posted.
        page1 = [{"id": i, "state": "COMMENTED", "commit_id": HEAD,
                  "user": {"login": "some-human"}} for i in range(100)]
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=1")] = (
            200, page1)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=2")] = (
            200, [{"id": 500, "state": "APPROVED", "commit_id": HEAD,
                   "user": {"login": "merge-guard-approver[bot]"}}])
        code, http = run_main(routes)
        self.assertEqual(code, 0)
        self.assertEqual(http.posted_reviews(), [])

    def test_paginates_all_pages_then_posts_when_no_match(self):
        # Full first page forces a second GET; page 2 is short and still holds
        # no matching prior approval, so the loop exhausts (page += 1 then a
        # short page) and a fresh review is POSTed. Pins the exhaustion path.
        page1 = [{"id": i, "state": "COMMENTED", "commit_id": HEAD,
                  "user": {"login": "some-human"}} for i in range(100)]
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=1")] = (
            200, page1)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=2")] = (
            200, [{"id": 500, "state": "APPROVED", "commit_id": MOVED,
                   "user": {"login": "merge-guard-approver[bot]"}}])  # stale
        code, http = run_main(routes)
        self.assertEqual(code, 0)
        self.assertEqual(len(http.posted_reviews()), 1)

    def test_malformed_repo_exits_2_before_any_api_call(self):
        http = FakeHttp({})
        code = approve_pr.main(
            ["--repo", "no-slash", "--pr", "5", "--head-sha", HEAD,
             "--app-id", "1", "--key-path", "/dev/null", "--facts", "{}"],
            http=http, signer_factory=lambda path: FAKE_SIGNER,
            clock=lambda: NOW)
        self.assertEqual(code, 2)
        self.assertEqual(http.calls, [])

    def test_moved_head_refuses_without_posting(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5")] = (200, {"head": {"sha": MOVED}})
        code, http = run_main(routes)
        self.assertEqual(code, 1)
        self.assertEqual(http.posted_reviews(), [])

    def test_existing_app_approval_at_head_is_noop(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=1")] = (200, [{
            "id": 7, "state": "APPROVED", "commit_id": HEAD,
            "user": {"login": "merge-guard-approver[bot]"},
        }])
        code, http = run_main(routes)
        self.assertEqual(code, 0)
        self.assertEqual(http.posted_reviews(), [])

    def test_stale_or_foreign_approvals_do_not_shortcut(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/pulls/5/reviews?per_page=100&page=1")] = (200, [
            {"id": 1, "state": "APPROVED", "commit_id": MOVED,
             "user": {"login": "merge-guard-approver[bot]"}},   # stale commit
            {"id": 2, "state": "APPROVED", "commit_id": HEAD,
             "user": {"login": "some-human"}},                   # not our app
            {"id": 3, "state": "COMMENTED", "commit_id": HEAD,
             "user": {"login": "merge-guard-approver[bot]"}},    # not APPROVED
        ])
        code, http = run_main(routes)
        self.assertEqual(code, 0)
        self.assertEqual(len(http.posted_reviews()), 1)

    def test_token_mint_failure_exits_2_with_status(self):
        routes = dict(BASE_ROUTES)
        routes[("POST", "/app/installations/42/access_tokens")] = (
            401, {"message": "bad credentials"})
        code, http = run_main(routes)
        self.assertEqual(code, 2)
        self.assertEqual(http.posted_reviews(), [])

    def test_app_not_installed_exits_2(self):
        routes = dict(BASE_ROUTES)
        routes[("GET", "/repos/o/r/installation")] = (404, {"message": "Not Found"})
        code, _ = run_main(routes)
        self.assertEqual(code, 2)

    def test_missing_key_file_exits_2(self):
        http = FakeHttp({})
        code = approve_pr.main(
            [*ARGS[:-4], "--key-path", "/nonexistent/nope.pem",
             "--facts", "{}"],
            http=http, signer_factory=approve_pr.openssl_signer,
            clock=lambda: NOW)
        self.assertEqual(code, 2)
        self.assertEqual(http.calls, [])


if __name__ == "__main__":
    unittest.main()
