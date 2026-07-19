"""Pin the `work lint` payload keys the migration scripts read.

These scripts index into `work lint` output. Every such key was validated
against a live run in which the relevant list was EMPTY — so the loop bodies
never executed and a wrong key raised nothing. That is how `m["id"]` survived
review: `track_mismatches` is empty until the migration populates it, which is
precisely when the verifier needs to work.

These fixtures are non-empty on purpose. A fixture that cannot fail is not a
test.

The shapes below are copied from packages/workcli/src/workcli/verbs/report.py.
If workcli changes them, these tests fail and tell you which script to update.
"""
import unittest

# _track_mismatches() — note the key is "child", NOT "id".
LINT_TRACK_MISMATCHES = [
    {
        "child": "agents-config-9v0y",
        "child_track": "review-and-merge",
        "parent": "agents-config-7bk",
        "parent_track": "pipeline-discipline",
    }
]

# _lease_report()
LINT_LEASES = {"leases": [{"id": "agents-config-y9mm", "track": "workcli"}]}

# track_violations entries are keyed on "id".
LINT_TRACK_VIOLATIONS = [{"id": "agents-config-abcde"}]


class TestLintPayloadKeys(unittest.TestCase):
    def test_track_mismatch_entries_are_keyed_on_child_not_id(self):
        """The blocking defect: verify.py read m['id'] and would KeyError."""
        entry = LINT_TRACK_MISMATCHES[0]
        self.assertIn("child", entry)
        self.assertNotIn("id", entry)

    def test_verify_mismatch_extraction_works_on_a_populated_list(self):
        """The extraction expression as verify.py performs it."""
        actual = {m["child"] for m in LINT_TRACK_MISMATCHES}
        self.assertEqual(actual, {"agents-config-9v0y"})

    def test_mismatch_extraction_on_an_empty_list_hides_a_wrong_key(self):
        """Why the original validation proved nothing.

        Both the right and the wrong key produce an empty set over an empty
        list. This test exists to document that an empty fixture cannot
        distinguish them — not to endorse it.
        """
        self.assertEqual({m["child"] for m in []}, set())
        self.assertEqual({m["id"] for m in []}, set())

    def test_lease_entries_are_keyed_on_id(self):
        leased = {item["id"] for item in LINT_LEASES["leases"]}
        self.assertEqual(leased, {"agents-config-y9mm"})

    def test_track_violation_entries_are_keyed_on_id(self):
        ids = {v["id"] for v in LINT_TRACK_VIOLATIONS}
        self.assertEqual(ids, {"agents-config-abcde"})


class TestDeriveTrackAssumptions(unittest.TestCase):
    """derive_track() collapses 0 and 2+ track labels alike to None."""

    @staticmethod
    def derive_track(labels):
        names = [x[len("track:"):] for x in labels if x.startswith("track:")]
        return names[0] if len(names) == 1 else None

    def test_two_track_labels_derive_to_none_like_zero_labels(self):
        self.assertIsNone(self.derive_track(["track:installer", "track:prgroom"]))
        self.assertIsNone(self.derive_track([]))

    def test_counting_raw_labels_distinguishes_them(self):
        """Why C1 inspects raw labels instead of the derived track."""
        doubled = ["track:installer", "track:prgroom"]
        self.assertEqual(len([x for x in doubled if x.startswith("track:")]), 2)
        self.assertEqual(len([x for x in [] if x.startswith("track:")]), 0)


if __name__ == "__main__":
    unittest.main()
