"""Pin C1's sweep, and the premise change that broke it.

C1 originally failed any item carrying a track the artifact did not mention.
That was sound while the artifact was the only way a track could arrive. It is
not any more: `work create --track` threads one through the lifecycle gate at
creation, and the enforcement flip makes that mandatory — so the old check fails
a correct run once, then fails harder every week as correctly created items
accumulate. It fired on a real run of this migration, against nine items the
applicator had never touched.

The replacement asks the question the old check was reaching for — did the
applicator write outside what was decided? — of the run log, which records
writers, rather than of end state, which cannot tell one writer from another.
"""

import unittest

from verify import applied_ids, audit_tracks


def item(item_id, *, track=None, status="open", labels=None):
    if labels is None:
        labels = [f"track:{track}"] if track else []
    return {"id": item_id, "track": track, "status": status, "labels": labels}


class TestAuditTracks(unittest.TestCase):
    def test_a_live_item_on_its_decided_track_is_clean(self):
        audit = audit_tracks([item("a", track="workcli")], [], {"a": "workcli"}, {"a"})
        self.assertEqual(audit["mismatched"], [])
        self.assertEqual(audit["wrote_outside_artifact"], [])

    def test_a_live_item_on_the_wrong_track_is_mismatched(self):
        audit = audit_tracks([item("a", track="installer")], [], {"a": "workcli"}, {"a"})
        self.assertEqual(audit["mismatched"], [("a", "workcli", "installer", "open")])

    def test_a_track_the_artifact_never_mentions_is_not_a_failure(self):
        """The regression: created-with-a-track is now the normal path."""
        audit = audit_tracks([item("newborn", track="workcli")], [], {}, set())
        self.assertEqual(audit["mismatched"], [])
        self.assertEqual(audit["doubled"], [])
        self.assertEqual(audit["wrote_outside_artifact"], [])

    def test_a_run_log_write_outside_the_artifact_is_a_failure(self):
        """What the old check was reaching for, asked of the writer."""
        audit = audit_tracks(
            [item("a", track="workcli"), item("rogue", track="installer")],
            [],
            {"a": "workcli"},
            {"a", "rogue"},
        )
        self.assertEqual(audit["wrote_outside_artifact"], ["rogue"])

    def test_run_log_ids_from_a_retired_database_are_not_a_failure(self):
        """The log is cumulative across migrations, including ones whose
        database was replaced. Those ids exist nowhere now and prove nothing."""
        audit = audit_tracks(
            [item("a", track="workcli")], [], {"a": "workcli"}, {"a", "gone-with-the-old-db"}
        )
        self.assertEqual(audit["wrote_outside_artifact"], [])

    def test_two_track_labels_are_a_failure_whatever_the_status(self):
        doubled = item("a", labels=["track:workcli", "track:installer"], track=None)
        closed_doubled = item("b", labels=["track:a", "track:b"], status="closed")
        audit = audit_tracks([doubled], [closed_doubled], {}, set())
        self.assertEqual([entry[0] for entry in audit["doubled"]], ["a", "b"])

    def test_an_artifact_item_that_closed_is_skipped_not_mismatched(self):
        audit = audit_tracks([], [item("a", status="closed")], {"a": "workcli"}, set())
        self.assertEqual(audit["mismatched"], [])
        self.assertEqual(audit["skipped_closed"], ["a"])


class TestAppliedIds(unittest.TestCase):
    def test_parses_tab_separated_ids(self):
        self.assertEqual(applied_ids("a\tworkcli\nb\tinstaller\n"), {"a", "b"})

    def test_ignores_blank_and_untabbed_lines(self):
        self.assertEqual(applied_ids("a\tworkcli\n\n   \nnoise\n"), {"a"})

    def test_an_absent_log_reads_as_no_writes(self):
        self.assertEqual(applied_ids(""), set())


if __name__ == "__main__":
    unittest.main()
