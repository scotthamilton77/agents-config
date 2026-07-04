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
            "judge_backend": "codex",
            "judge_model": "gpt-5.5",
            "judge_effort": "high",
            "judge_timeout_seconds": 900,
            "judge_max_attempts": 2,
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

    def test_unexpected_environment_error_exits_2_not_1(self):
        # A directory is not openable as a config file -> OSError (IsADirectoryError),
        # which is neither FileNotFoundError nor TOMLDecodeError. Must be exit 2,
        # not conflated with PolicyError's exit 1, and no raw traceback on stderr.
        directory = tempfile.mkdtemp()
        code, out, err = run_resolver("--project-config", directory)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("Traceback", err)


class TestValidation(unittest.TestCase):
    def _resolve(self, toml_body: str):
        return run_resolver("--project-config", write_toml(toml_body))

    def test_negative_approvers_rejected_in_every_mode(self):
        code, _, err = self._resolve('[review-expectations]\nhuman-approvers-required = -1\n')
        self.assertEqual(code, 1)
        self.assertIn("human-approvers-required", err)

    def test_bad_merge_authorization_enum(self):
        code, _, err = self._resolve('[merge-policy]\nmerge-authorization = "auto"\n')
        self.assertEqual(code, 1)
        self.assertIn("merge-authorization", err)

    def test_rule_based_without_rule(self):
        code, _, err = self._resolve('[merge-policy]\nmerge-authorization = "rule-based"\n')
        self.assertEqual(code, 1)
        self.assertIn("merge-rule", err)

    def test_rule_set_while_not_rule_based(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "explicit"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 1)

    def test_bad_rule_enum(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "vibes"\n')
        self.assertEqual(code, 1)
        self.assertIn("merge-rule", err)

    def test_human_approvals_rule_requires_at_least_one(self):
        code, _, err = self._resolve(
            '[review-expectations]\nhuman-approvers-required = 0\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "human-approvals"\n')
        self.assertEqual(code, 1)
        self.assertIn("human-approvals", err)

    def test_bot_quiescence_requires_trusted_bot(self):
        code, _, err = self._resolve(
            '[review-expectations]\nbot-reviewers = []\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 1)
        self.assertIn("bot-reviewers", err)

    def test_bot_quiescence_requires_bot_expected(self):
        code, _, err = self._resolve(
            '[review-expectations]\nbot-review-expected = false\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 1)
        self.assertIn("bot-review-expected", err)

    def test_agent_ruling_resolves(self):
        code, out, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n')
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy["merge_rule"], "agent-ruling")
        self.assertEqual(policy["merge_authorization"], "rule-based")
        # judge defaults present
        self.assertEqual(policy["judge_backend"], "codex")
        self.assertEqual(policy["judge_model"], "gpt-5.5")
        self.assertEqual(policy["judge_effort"], "high")
        self.assertEqual(policy["judge_timeout_seconds"], 900)
        self.assertEqual(policy["judge_max_attempts"], 2)

    def test_agent_ruling_resolves_bot_false_humans_zero(self):
        code, out, err = self._resolve(
            '[review-expectations]\nbot-review-expected = false\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n')
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertFalse(policy["bot_review_expected"])
        self.assertEqual(policy["human_approvers_required"], 0)

    def test_bad_judge_effort_rejected(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n'
            'judge-effort = "extreme"\n')
        self.assertEqual(code, 1)
        self.assertIn("judge-effort", err)

    def test_bad_judge_backend_rejected(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n'
            'judge-backend = "ollama"\n')
        self.assertEqual(code, 1)
        self.assertIn("judge-backend", err)

    def test_underivable_judge_model_family_rejected(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n'
            'judge-model = "llama-3"\n')
        self.assertEqual(code, 1)
        self.assertIn("judge-model", err)

    def test_non_int_judge_max_attempts_rejected(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "agent-ruling"\n'
            'judge-max-attempts = "lots"\n')
        self.assertEqual(code, 1)
        self.assertIn("judge-max-attempts", err)

    def test_judge_keys_without_agent_ruling_rejected(self):
        code, _, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n'
            'judge-model = "gpt-5.5"\n')
        self.assertEqual(code, 1)
        self.assertIn("judge", err)

    def test_valid_rule_based_bot_quiescence_resolves(self):
        code, out, err = self._resolve(
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "bot-quiescence"\n')
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy["merge_authorization"], "rule-based")
        self.assertEqual(policy["merge_rule"], "bot-quiescence")


class TestAgentsConfigSettings(unittest.TestCase):
    def test_agents_config_policy_resolves(self):
        path = write_toml(
            '[review-expectations]\n'
            'bot-review-expected = true\n'
            'bot-reviewers = ["Copilot", "copilot-pull-request-reviewer[bot]"]\n'
            'human-approvers-required = 0\n'
            '[merge-policy]\n'
            'merge-authorization = "rule-based"\n'
            'merge-rule = "bot-quiescence"\n'
        )
        code, out, err = run_resolver("--project-config", path)
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertEqual(policy["merge_rule"], "bot-quiescence")
        self.assertEqual(policy["human_approvers_required"], 0)


class TestLabelOverrides(unittest.TestCase):
    def test_copilot_only_overrides_config(self):
        path = write_toml(
            '[review-expectations]\nbot-review-expected = false\nhuman-approvers-required = 3\n')
        code, out, err = run_resolver("--project-config", path,
                                      "--labels", "misc,review-exit-copilot-only")
        self.assertEqual(code, 0, err)
        policy = json.loads(out)
        self.assertTrue(policy["bot_review_expected"])
        self.assertEqual(policy["human_approvers_required"], 0)

    def test_human_approvers_label_sets_count(self):
        code, out, err = run_resolver("--project-config", "/nonexistent.toml",
                                      "--labels", "review-exit-human-approvers-3")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["human_approvers_required"], 3)

    def test_both_labels_conflict(self):
        code, _, err = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "review-exit-copilot-only,review-exit-human-approvers-2")
        self.assertEqual(code, 1)
        self.assertIn("mutually exclusive", err)

    def test_malformed_count_label_rejected(self):
        code, _, err = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "review-exit-human-approvers-lots")
        self.assertEqual(code, 1)

    def test_empty_count_label_rejected(self):
        code, _, err = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "review-exit-human-approvers-")
        self.assertEqual(code, 1)
        self.assertIn("review-exit-human-approvers-", err)

    def test_unicode_digit_count_label_rejected_not_traceback(self):
        code, _, err = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "review-exit-human-approvers-²")
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)

    def test_duplicate_count_labels_rejected(self):
        code, _, err = run_resolver(
            "--project-config", "/nonexistent.toml",
            "--labels", "review-exit-human-approvers-1,review-exit-human-approvers-2")
        self.assertEqual(code, 1)
        self.assertIn("multiple", err)

    def test_unrelated_labels_ignored(self):
        code, out, _ = run_resolver("--project-config", "/nonexistent.toml",
                                    "--labels", "install,formula-implement-feature")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["human_approvers_required"], 0)

    def test_label_override_still_validated(self):
        # copilot-only forces humans=0 — combined with human-approvals rule that must fail
        path = write_toml(
            '[review-expectations]\nhuman-approvers-required = 1\n'
            '[merge-policy]\nmerge-authorization = "rule-based"\nmerge-rule = "human-approvals"\n')
        code, _, err = run_resolver("--project-config", path,
                                    "--labels", "review-exit-copilot-only")
        self.assertEqual(code, 1)
        self.assertIn("human-approvals", err)


if __name__ == "__main__":
    unittest.main()
