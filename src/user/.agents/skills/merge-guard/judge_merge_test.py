#!/usr/bin/env python3
"""Unit tests for judge_merge.py (stdlib unittest; run via *_test.sh).

Tests import judge_merge as a sibling and drive its pure functions directly;
the codex subprocess and git are injected as fakes — no network, no codex CLI.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import judge_merge as jm  # noqa: E402


class TestEnvelope(unittest.TestCase):
    def test_build_envelope_shape(self):
        env = jm.build_envelope(
            head="h", base="b", diff_sha="d", verdict="abstain",
            abstain_reason="protected-path", judge_model="gpt-5.5",
            judge_effort="high", author_families=["openai"],
            summary="", merge_blocking_findings=[])
        self.assertEqual(env["verdict"], "abstain")
        self.assertEqual(env["abstain_reason"], "protected-path")
        self.assertEqual(env["judge_backend"], "codex")
        self.assertEqual(env["judge_model_family"], "openai")
        for key in ("head_ref_oid", "base_ref_oid", "diff_sha", "judge_model",
                    "judge_effort", "author_families", "summary", "merge_blocking_findings"):
            self.assertIn(key, env)

    def test_go_has_no_abstain_reason(self):
        env = jm.build_envelope(head="h", base="b", diff_sha="d", verdict="go",
                                abstain_reason=None, judge_model="gpt-5.5",
                                judge_effort="high", author_families=["openai"],
                                summary="clean", merge_blocking_findings=[])
        self.assertIsNone(env["abstain_reason"])


class TestNonce(unittest.TestCase):
    def test_nonce_is_long_hex_and_unique(self):
        a, b = jm.mint_nonce(), jm.mint_nonce()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 24)
        int(a, 16)  # raises if not hex


class TestAttemptBudget(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()

    def test_fresh_budget_not_exhausted(self):
        self.assertFalse(jm.budget_exhausted(self.state, "o", "r", "5", "base1", max_attempts=2))

    def test_bump_then_exhausted_at_max(self):
        jm.bump_attempts(self.state, "o", "r", "5", "base1")
        self.assertFalse(jm.budget_exhausted(self.state, "o", "r", "5", "base1", max_attempts=2))
        jm.bump_attempts(self.state, "o", "r", "5", "base1")
        self.assertTrue(jm.budget_exhausted(self.state, "o", "r", "5", "base1", max_attempts=2))

    def test_new_base_resets(self):
        jm.bump_attempts(self.state, "o", "r", "5", "base1")
        jm.bump_attempts(self.state, "o", "r", "5", "base1")
        self.assertFalse(jm.budget_exhausted(self.state, "o", "r", "5", "base2", max_attempts=2))


if __name__ == "__main__":
    unittest.main()
