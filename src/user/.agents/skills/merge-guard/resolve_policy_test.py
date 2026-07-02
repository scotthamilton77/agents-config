#!/usr/bin/env python3
"""Unit tests for resolve_policy.py (stdlib unittest; run via resolve_policy_test.sh)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "resolve_policy.py")


def run_resolver(*args):
    """Run the resolver CLI; return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TestDefaults(unittest.TestCase):
    def test_no_config_file_yields_builtin_defaults(self):
        missing = os.path.join(tempfile.mkdtemp(), "absent.toml")
        code, out, err = run_resolver("--project-config", missing)
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy, {
            "bot_review_expected": True,
            "bot_reviewers": ["Copilot", "copilot-pull-request-reviewer[bot]"],
            "bot_inactivity_timeout_seconds": 1200,
            "human_approvers_required": 0,
            "human_review_timeout_seconds": None,
            "merge_authorization": "explicit",
            "merge_rule": None,
        })


if __name__ == "__main__":
    unittest.main()
