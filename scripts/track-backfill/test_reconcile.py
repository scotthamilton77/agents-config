"""Tests for track-backfill reconciliation."""
import unittest

from reconcile import reconcile


class TestReconcile(unittest.TestCase):
    def test_untracked_live_items_are_all_applied(self):
        result = reconcile(
            assignment={"a": "installer", "b": "prgroom"},
            live_tracks={"a": None, "b": None},
            lint_violations={"a", "b"},
        )
        self.assertEqual(result.to_apply, {"a": "installer", "b": "prgroom"})
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.residue, [])

    def test_item_absent_from_live_set_is_skipped_not_written(self):
        """An item closed since generation must not be written to."""
        result = reconcile(
            assignment={"a": "installer", "closed": "prgroom"},
            live_tracks={"a": None},
            lint_violations={"a"},
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.skipped, ["closed"])

    def test_live_item_with_wrong_track_is_corrected(self):
        """The regression the lint-as-liveness conflation caused.

        An item already carrying a valid but *different* track is lint-clean, so
        keying off lint violations classified it as closed and silently declined
        to correct it — and re-running could never repair it. Liveness comes from
        the live set, not from lint.
        """
        result = reconcile(
            assignment={"a": "installer"},
            live_tracks={"a": "prgroom"},
            lint_violations=set(),
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.skipped, [])
        self.assertEqual(result.already_correct, [])

    def test_live_item_already_on_target_track_is_not_rewritten(self):
        """Idempotency: a second run must be a genuine no-op."""
        result = reconcile(
            assignment={"a": "installer"},
            live_tracks={"a": "installer"},
            lint_violations=set(),
        )
        self.assertEqual(result.to_apply, {})
        self.assertEqual(result.already_correct, ["a"])
        self.assertEqual(result.skipped, [])

    def test_second_run_after_full_apply_writes_nothing(self):
        """The whole-artifact form of the idempotency claim (criterion 7)."""
        assignment = {"a": "installer", "b": "prgroom", "c": "ops-meta"}
        result = reconcile(
            assignment=assignment,
            live_tracks=dict(assignment),
            lint_violations=set(),
        )
        self.assertEqual(result.to_apply, {})
        self.assertEqual(result.already_correct, ["a", "b", "c"])

    def test_partial_run_reapplies_only_the_unwritten_remainder(self):
        result = reconcile(
            assignment={"done": "installer", "pending": "prgroom"},
            live_tracks={"done": "installer", "pending": None},
            lint_violations={"pending"},
        )
        self.assertEqual(result.to_apply, {"pending": "prgroom"})
        self.assertEqual(result.already_correct, ["done"])

    def test_live_violation_absent_from_artifact_is_residue(self):
        """A new untracked item is reported, never guessed at."""
        result = reconcile(
            assignment={"a": "installer"},
            live_tracks={"a": None, "brand_new": None},
            lint_violations={"a", "brand_new"},
        )
        self.assertEqual(result.to_apply, {"a": "installer"})
        self.assertEqual(result.residue, ["brand_new"])

    def test_residue_never_includes_assigned_ids(self):
        result = reconcile(
            assignment={"a": "installer"},
            live_tracks={"a": "installer"},
            lint_violations={"a"},
        )
        self.assertEqual(result.residue, [])

    def test_lists_are_sorted_for_stable_reporting(self):
        result = reconcile(
            assignment={"z": "ops-meta", "y": "ops-meta"},
            live_tracks={},
            lint_violations={"q", "b"},
        )
        self.assertEqual(result.skipped, ["y", "z"])
        self.assertEqual(result.residue, ["b", "q"])

    def test_empty_assignment_makes_every_violation_residue(self):
        result = reconcile(
            assignment={},
            live_tracks={"a": None, "b": None},
            lint_violations={"a", "b"},
        )
        self.assertEqual(result.to_apply, {})
        self.assertEqual(result.residue, ["a", "b"])

    def test_is_clean_true_only_when_no_residue(self):
        clean = reconcile(
            assignment={"a": "installer"},
            live_tracks={"a": None},
            lint_violations={"a"},
        )
        self.assertTrue(clean.is_clean)
        dirty = reconcile(
            assignment={"a": "installer"},
            live_tracks={"a": None, "n": None},
            lint_violations={"a", "n"},
        )
        self.assertFalse(dirty.is_clean)


if __name__ == "__main__":
    unittest.main()
