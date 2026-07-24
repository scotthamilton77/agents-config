#!/usr/bin/env python3
"""Unit tests for model_family.py (stdlib unittest; run via model_family_test.sh)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from model_family import family_of  # noqa: E402


class TestFamilyOf(unittest.TestCase):
    def test_openai_gpt(self):
        self.assertEqual(family_of("gpt-5.5"), "openai")

    def test_openai_o_series(self):
        self.assertEqual(family_of("o3-mini"), "openai")

    def test_anthropic(self):
        self.assertEqual(family_of("claude-opus-4-8"), "anthropic")

    def test_google(self):
        self.assertEqual(family_of("gemini-2.5-pro"), "google")

    def test_case_insensitive(self):
        self.assertEqual(family_of("GPT-5.5"), "openai")

    def test_unknown_is_none(self):
        self.assertIsNone(family_of("llama-3"))

    def test_empty_is_none(self):
        self.assertIsNone(family_of(""))


if __name__ == "__main__":
    unittest.main()
