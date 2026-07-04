#!/usr/bin/env python3
"""Unit tests for protected_paths.py (stdlib unittest; run via *_test.sh)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from protected_paths import scan_protected  # noqa: E402


class TestScanProtected(unittest.TestCase):
    def _hit(self, path):
        return scan_protected([path])

    def test_merge_policy_toml(self):
        self.assertIsNotNone(self._hit("project-config.toml"))

    def test_merge_guard_source(self):
        self.assertIsNotNone(self._hit("src/user/.agents/skills/merge-guard/judge_merge.py"))

    def test_delivery_workflow(self):
        self.assertIsNotNone(self._hit("src/user/.agents/skills/finishing-a-development-branch/SKILL.md"))

    def test_codex_routing(self):
        self.assertIsNotNone(self._hit("src/plugins/codex/.claude/rules/codex-routing.md"))

    def test_github_workflows(self):
        self.assertIsNotNone(self._hit(".github/workflows/ci.yml"))

    def test_settings_template(self):
        self.assertIsNotNone(self._hit("src/user/.claude/settings.json.template"))

    def test_hooks_dir(self):
        self.assertIsNotNone(self._hit("hooks/pre-commit.sh"))

    def test_installer(self):
        self.assertIsNotNone(self._hit("packages/installer/src/installer/cli.py"))

    def test_secret_file(self):
        self.assertIsNotNone(self._hit(".env.local"))

    def test_instruction_template(self):
        self.assertIsNotNone(self._hit("src/user/.agents/AGENTS.md.template"))

    def test_prompt_and_rubric_self_protected(self):
        self.assertIsNotNone(self._hit("src/user/.agents/skills/merge-guard/merge_judge_prompt.md"))

    def test_ordinary_code_not_protected(self):
        self.assertIsNone(self._hit("src/app/widget.py"))

    def test_dir_class_not_matched_as_segment_suffix(self):
        # A protected dir class must match a whole path segment, not a suffix
        # of a longer one. "rules/" and "hooks/" must NOT fire on these.
        self.assertIsNone(self._hit("src/app/business_rules/foo.py"))
        self.assertIsNone(self._hit("src/webhooks/handler.py"))

    def test_dir_class_matches_at_repo_root(self):
        # Leading-slash classes still match a protected segment at repo root,
        # via the "/" + path normalization in scan_protected.
        self.assertIsNotNone(self._hit("rules/delegation.md"))
        self.assertIsNotNone(self._hit("merge-guard/SKILL.md"))

    def test_returns_first_matching_path(self):
        hit = scan_protected(["src/app/widget.py", ".github/workflows/ci.yml"])
        self.assertEqual(hit, ".github/workflows/ci.yml")

    def test_empty_diff_no_hit(self):
        self.assertIsNone(scan_protected([]))


if __name__ == "__main__":
    unittest.main()
