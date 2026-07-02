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


def write_toml(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".toml")
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    return path


class TestConfigParsing(unittest.TestCase):
    def test_config_values_override_defaults(self):
        path = write_toml(
            '[review-expectations]\n'
            'bot-review-expected = false\n'
            'bot-reviewers = ["my-bot[bot]"]\n'
            'bot-inactivity-timeout = "45m"\n'
            'human-approvers-required = 2\n'
            'human-review-timeout = "48h"\n'
            '[merge-policy]\n'
            'merge-authorization = "never"\n'
        )
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertFalse(policy["bot_review_expected"])
        self.assertEqual(policy["bot_reviewers"], ["my-bot[bot]"])
        self.assertEqual(policy["bot_inactivity_timeout_seconds"], 2700)
        self.assertEqual(policy["human_approvers_required"], 2)
        self.assertEqual(policy["human_review_timeout_seconds"], 172800)
        self.assertEqual(policy["merge_authorization"], "never")

    def test_integer_duration_is_seconds(self):
        path = write_toml('[review-expectations]\nbot-inactivity-timeout = 900\n')
        code, out, _ = run_resolver("--project-config", path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["bot_inactivity_timeout_seconds"], 900)

    def test_unknown_key_fails_loud(self):
        path = write_toml('[review-expectations]\nbot-reviewer = ["typo"]\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("unknown key", err)
        self.assertIn("bot-reviewer", err)

    def test_bad_duration_fails_loud(self):
        path = write_toml('[review-expectations]\nbot-inactivity-timeout = "soon"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("duration", err)

    def test_wrong_type_fails_loud(self):
        path = write_toml('[review-expectations]\nbot-review-expected = "yes"\n')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)

    def test_unparseable_toml_fails_loud_not_defaults(self):
        path = write_toml('[review-expectations\nbroken')
        code, _, err = run_resolver("--project-config", path)
        self.assertEqual(code, 1)
        self.assertIn("unparseable", err)


if __name__ == "__main__":
    unittest.main()
