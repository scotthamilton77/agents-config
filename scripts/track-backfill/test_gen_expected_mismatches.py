"""Pin `cross_track_edges` against the rule `work lint` actually applies.

The edge set this produces is the baseline `verify.py` criterion 5 compares
against, so any edge it emits that lint would never report is a criterion that
can never pass. Lint excludes milestones from *both* sides — it filters them out
of its item list before the walk (`non_milestone`) and skips them again as
parents — and the first of those is easy to omit, because a milestone carrying a
track is out of contract rather than impossible: raw label writes bypass the
validated gate. These fixtures therefore give a milestone a track on purpose.
"""

import unittest

from gen_expected_mismatches import cross_track_edges


def item(item_id, *, parent=None, kind="task", track=None):
    return {"id": item_id, "parent": parent, "type": kind, "track": track}


class TestCrossTrackEdges(unittest.TestCase):
    def test_differing_tracks_under_a_non_milestone_parent_are_an_edge(self):
        items = [item("parent", track="workcli"), item("child", parent="parent", track="installer")]
        self.assertEqual(
            cross_track_edges(items, {}),
            [
                {
                    "child": "child",
                    "child_track": "installer",
                    "parent": "parent",
                    "parent_track": "workcli",
                }
            ],
        )

    def test_matching_tracks_are_not_an_edge(self):
        items = [item("parent", track="workcli"), item("child", parent="parent", track="workcli")]
        self.assertEqual(cross_track_edges(items, {}), [])

    def test_a_milestone_child_is_never_an_edge(self):
        """The omission Copilot caught: lint filters milestone children first."""
        items = [
            item("parent", track="workcli"),
            item("child", parent="parent", kind="milestone", track="installer"),
        ]
        self.assertEqual(cross_track_edges(items, {}), [])

    def test_a_milestone_parent_is_never_an_edge(self):
        items = [
            item("parent", kind="milestone", track="workcli"),
            item("child", parent="parent", track="installer"),
        ]
        self.assertEqual(cross_track_edges(items, {}), [])

    def test_the_assignment_overrides_the_current_track(self):
        """Post-migration state is what the baseline must describe."""
        items = [item("parent", track="workcli"), item("child", parent="parent", track="workcli")]
        self.assertEqual(
            [edge["child_track"] for edge in cross_track_edges(items, {"child": "installer"})],
            ["installer"],
        )

    def test_an_untracked_side_is_not_an_edge(self):
        items = [item("parent"), item("child", parent="parent", track="installer")]
        self.assertEqual(cross_track_edges(items, {}), [])

    def test_a_parent_outside_the_live_set_is_skipped(self):
        items = [item("child", parent="gone", track="installer")]
        self.assertEqual(cross_track_edges(items, {}), [])


if __name__ == "__main__":
    unittest.main()
