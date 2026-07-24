"""derive_track: the single label->track rule every consumer shares."""

from __future__ import annotations

from workcli.tracks import derive_track


def test_single_track_label_derives_its_name() -> None:
    assert derive_track(["shape-task", "track:installer", "planned"]) == "installer"


def test_no_track_label_derives_none() -> None:
    assert derive_track(["shape-task", "planned"]) is None


def test_multiple_track_labels_derive_none() -> None:
    # Reachable via raw label writes; the rule pins null, lint invariant 1 flags it.
    assert derive_track(["track:installer", "track:prgroom"]) is None


def test_non_track_prefix_lookalikes_ignored() -> None:
    assert derive_track(["tracking:x", "track", "backtrack:y"]) is None
