#!/usr/bin/env python3
"""Unit tests for approve_pr.py (stdlib unittest; run via approve_pr_test.sh).

All GitHub traffic goes through an injected fake transport; signing through a
fake signer. No network, no keys, no repo-internal paths.
"""
import base64
import json
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


if __name__ == "__main__":
    unittest.main()
