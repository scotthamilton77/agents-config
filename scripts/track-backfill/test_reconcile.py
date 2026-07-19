"""Tests for track-backfill reconciliation."""
import unittest

from reconcile import reconcile


class TestReconcile(unittest.TestCase):
    def test_all_assigned_ids_live_applies_everything(self):
        result = reconcile(
            assignment={"a": "installer", "b": "prgroom"},
            live_violations={"a", "b"},
        )
        self.assertEqual(result.to_apply, {"a": "installer", "b": "prgroom"})
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.residue, [])

    def test_assigned_id_no_longer_live_is_skipped_not_applied(self):
        """An item closed since generation must not be written to."""
        result = reconcile(
            assignment={"a": "installer", "closed": "prgroom"},
            live_violations={"a"},
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.skipped, ["closed"])
        self.assertEqual(result.residue, [])

    def test_live_violation_absent_from_artifact_is_residue(self):
        """A new untracked item is reported, never guessed at."""
        result = reconcile(
            assignment={"a": "installer"},
            live_violations={"a", "brand_new"},
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.residue, ["brand_new"])

    def test_skipped_and_residue_are_sorted_for_stable_reporting(self):
        result = reconcile(
            assignment={"z": "ops-meta", "y": "ops-meta"},
            live_violations={"q", "b"},
        )
        self.assertEqual(result.skipped, ["y", "z"])
        self.assertEqual(result.residue, ["b", "q"])

    def test_empty_assignment_makes_every_violation_residue(self):
        result = reconcile(assignment={}, live_violations={"a", "b"})
        self.assertEqual(result.to_apply, {})
        self.assertEqual(result.residue, ["a", "b"])

    def test_is_clean_true_only_when_no_residue(self):
        clean = reconcile(assignment={"a": "installer"}, live_violations={"a"})
        self.assertTrue(clean.is_clean)
        dirty = reconcile(assignment={"a": "installer"}, live_violations={"a", "n"})
        self.assertFalse(dirty.is_clean)


if __name__ == "__main__":
    unittest.main()
