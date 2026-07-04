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

    def test_returns_first_matching_path(self):
        hit = scan_protected(["src/app/widget.py", ".github/workflows/ci.yml"])
        self.assertEqual(hit, ".github/workflows/ci.yml")

    def test_empty_diff_no_hit(self):
        self.assertIsNone(scan_protected([]))


if __name__ == "__main__":
    unittest.main()
