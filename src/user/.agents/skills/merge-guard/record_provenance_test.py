#!/usr/bin/env python3
"""Unit tests for record_provenance.py (stdlib unittest; run via *_test.sh)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "record_provenance.py")


def run(state_dir, *args):
    env = dict(os.environ, MERGE_JUDGE_STATE_HOME=state_dir)
    proc = subprocess.run([sys.executable, SCRIPT, *args],
                          capture_output=True, text=True, timeout=30, env=env)
    return proc.returncode, proc.stdout, proc.stderr


class TestRecordProvenance(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()

    def test_writes_first_hand_record(self):
        code, out, err = run(
            self.state, "--owner", "o", "--repo", "r", "--pr", "5",
            "--head-sha", "abc123",
            "--commit", "abc123:openai:first-hand",
            "--commit", "def456:human:first-hand",
            "--recorded-by", "session-xyz")
        self.assertEqual(code, 0, err)
        path = os.path.join(self.state, "pr-provenance", "o~r~5~abc123.provenance.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            rec = json.load(fh)
        self.assertEqual(rec["head_sha"], "abc123")
        self.assertEqual(rec["recorded_by"], "session-xyz")
        self.assertEqual(len(rec["commits"]), 2)
        self.assertEqual(rec["commits"][0],
                         {"sha": "abc123", "author_families": ["openai"], "attestation": "first-hand"})

    def test_multi_family_commit(self):
        code, _, err = run(
            self.state, "--owner", "o", "--repo", "r", "--pr", "5",
            "--head-sha", "h", "--commit", "h:openai+anthropic:first-hand",
            "--recorded-by", "s")
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.state, "pr-provenance", "o~r~5~h.provenance.json")) as fh:
            rec = json.load(fh)
        self.assertEqual(rec["commits"][0]["author_families"], ["openai", "anthropic"])

    def test_bad_attestation_rejected(self):
        code, _, err = run(
            self.state, "--owner", "o", "--repo", "r", "--pr", "5",
            "--head-sha", "h", "--commit", "h:openai:guessed", "--recorded-by", "s")
        self.assertEqual(code, 1)
        self.assertIn("attestation", err)

    def test_missing_required_flag_errors(self):
        code, _, err = run(self.state, "--owner", "o", "--repo", "r")
        self.assertNotEqual(code, 0)

    def test_owner_path_traversal_rejected(self):
        code, _, err = run(
            self.state, "--owner", "../../etc", "--repo", "r", "--pr", "5",
            "--head-sha", "h", "--commit", "h:openai:first-hand", "--recorded-by", "s")
        self.assertNotEqual(code, 0)
        self.assertIn("illegal path characters", err)
        out_dir = os.path.join(self.state, "pr-provenance")
        self.assertEqual(os.listdir(out_dir) if os.path.isdir(out_dir) else [], [])

    def test_repo_with_slash_rejected(self):
        code, _, err = run(
            self.state, "--owner", "o", "--repo", "a/b", "--pr", "5",
            "--head-sha", "h", "--commit", "h:openai:first-hand", "--recorded-by", "s")
        self.assertNotEqual(code, 0)
        self.assertIn("illegal path characters", err)
        out_dir = os.path.join(self.state, "pr-provenance")
        self.assertEqual(os.listdir(out_dir) if os.path.isdir(out_dir) else [], [])

    def test_head_sha_dotdot_rejected(self):
        code, _, err = run(
            self.state, "--owner", "o", "--repo", "r", "--pr", "5",
            "--head-sha", "..)", "--commit", "h:openai:first-hand", "--recorded-by", "s")
        self.assertNotEqual(code, 0)
        self.assertIn("illegal path characters", err)
        out_dir = os.path.join(self.state, "pr-provenance")
        self.assertEqual(os.listdir(out_dir) if os.path.isdir(out_dir) else [], [])


if __name__ == "__main__":
    unittest.main()
