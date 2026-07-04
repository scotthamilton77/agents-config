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


class TestProtectedGate(unittest.TestCase):
    def test_protected_path_hit(self):
        def fake_git(args):
            return "project-config.toml\nsrc/app/x.py\n"
        hit = jm.protected_diff_path("base", "head", git_runner=fake_git)
        self.assertEqual(hit, "project-config.toml")

    def test_clean_diff_no_hit(self):
        def fake_git(args):
            return "src/app/x.py\nsrc/app/y.py\n"
        self.assertIsNone(jm.protected_diff_path("base", "head", git_runner=fake_git))


class TestProvenanceGate(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.state, "pr-provenance"))

    def _write(self, head, commits):
        path = os.path.join(self.state, "pr-provenance", f"o-r-5-{head}.provenance.json")
        json.dump({"head_sha": head, "commits": commits, "recorded_by": "s"}, open(path, "w"))

    def _rev_list(self, shas):
        return lambda args: "\n".join(shas) + "\n"

    def test_all_first_hand_cross_model_passes(self):
        self._write("h", [{"sha": "c1", "author_families": ["anthropic"], "attestation": "first-hand"}])
        ok, reason, fams = jm.provenance_gate(self.state, "o", "r", "5", "b", "h",
                                              judge_family="openai", git_runner=self._rev_list(["c1"]))
        self.assertTrue(ok, reason)
        self.assertEqual(fams, ["anthropic"])

    def test_no_record_abstains(self):
        ok, reason, _ = jm.provenance_gate(self.state, "o", "r", "5", "b", "h",
                                           judge_family="openai", git_runner=self._rev_list(["c1"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "no-provenance")

    def test_trailer_derived_commit_abstains(self):
        self._write("h", [{"sha": "c1", "author_families": ["anthropic"], "attestation": "trailer-derived"}])
        ok, reason, _ = jm.provenance_gate(self.state, "o", "r", "5", "b", "h",
                                           judge_family="openai", git_runner=self._rev_list(["c1"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "unattested-commit")

    def test_judge_family_in_set_abstains(self):
        self._write("h", [{"sha": "c1", "author_families": ["openai"], "attestation": "first-hand"}])
        ok, reason, _ = jm.provenance_gate(self.state, "o", "r", "5", "b", "h",
                                           judge_family="openai", git_runner=self._rev_list(["c1"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "same-family")

    def test_human_only_never_disqualifies(self):
        self._write("h", [{"sha": "c1", "author_families": ["human"], "attestation": "first-hand"}])
        ok, reason, _ = jm.provenance_gate(self.state, "o", "r", "5", "b", "h",
                                           judge_family="openai", git_runner=self._rev_list(["c1"]))
        self.assertTrue(ok, reason)

    def test_commit_missing_from_record_abstains(self):
        self._write("h", [{"sha": "c1", "author_families": ["anthropic"], "attestation": "first-hand"}])
        ok, reason, _ = jm.provenance_gate(self.state, "o", "r", "5", "b", "h",
                                           judge_family="openai", git_runner=self._rev_list(["c1", "c2"]))
        self.assertFalse(ok)
        self.assertEqual(reason, "unattested-commit")


class TestDiffAssembly(unittest.TestCase):
    def test_assembles_and_hashes(self):
        diff_text = "diff --git a/x b/x\n+hello\n"
        got = jm.assemble_diff("base", "head", git_runner=lambda a: diff_text)
        self.assertEqual(got.text, diff_text)
        self.assertEqual(len(got.diff_sha), 64)  # sha256 hex
        # same diff -> same sha (deterministic)
        self.assertEqual(got.diff_sha, jm.assemble_diff("base", "head", git_runner=lambda a: diff_text).diff_sha)

    def test_empty_diff_flagged(self):
        got = jm.assemble_diff("base", "head", git_runner=lambda a: "")
        self.assertTrue(got.is_empty)

    def test_oversized_flagged(self):
        big = "x\n" * 10
        got = jm.assemble_diff("base", "head", git_runner=lambda a: big, max_bytes=5)
        self.assertTrue(got.is_oversized)


class TestCurrency(unittest.TestCase):
    def test_head_and_base_current(self):
        def fake_gh(args):
            return '{"headRefOid":"h","baseRefOid":"b"}'
        self.assertTrue(jm.refs_current("o", "r", "5", "h", "b", gh_runner=fake_gh))

    def test_moved_head_not_current(self):
        def fake_gh(args):
            return '{"headRefOid":"h2","baseRefOid":"b"}'
        self.assertFalse(jm.refs_current("o", "r", "5", "h", "b", gh_runner=fake_gh))


if __name__ == "__main__":
    unittest.main()
