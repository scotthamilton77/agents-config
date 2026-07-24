"""State-based recovery contract.

These tests assert the *healed final state* of a bead tree after delivery and
after a recovery sweep -- labels, status, children, notes -- against a
`FakeBackend`, not the argv order a scripted runner would capture. Crash
recovery is exercised by hand-building the partially-delivered state a crash
would leave, running `reconcile`, and asserting it heals to the same final
state a clean run reaches. The single completion handle (`impl-placeholder`,
removed strictly last, after the design child closes) is what makes every
crash point recoverable.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable

import pytest

from tests.fake_backend import FakeBackend
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle import (
    DELIVERED_MARKER,
    MANIFEST_MARKER,
    SPEC_MARKER,
    is_container,
    manifest_snapshot,
)
from workcli.lifecycle.create import instantiate_spec_shape
from workcli.lifecycle.deliver import deliver, reconcile_placeholder
from workcli.lifecycle.manifest import Manifest, ManifestItem, serialize_manifest
from workcli.lifecycle.nouns import (
    CREATING_SPEC_LABEL,
    DESIGN_CHILD_LABEL,
    IMPL_CONTAINER_LABEL,
    IMPL_PLACEHOLDER_LABEL,
    SPEC_READY_LABEL,
)
from workcli.lifecycle.reconcile import reconcile
from workcli.model import DepEdge

SPEC_SINGLE = "## Continuations\n- feat: Ship the thing — AC: it works\n"
SPEC_MULTI = "## Continuations\n- feat: Alpha — AC: build alpha\n- bugfix: Beta — AC: fix beta\n"
SPEC_NONE = "## Continuations\n- none — this spec is the deliverable\n"
SPEC_BARE_NONE = "## Continuations\n- none\n"


def _reader(text: str) -> Callable[[str], str]:
    """A read_file that returns `text` for any path -- deliver reads one spec."""
    return lambda _path: text


def _deliver_design(
    backend: FakeBackend,
    *,
    design_id: str = "d",
    spec_path: str = "S",
    spec_text: str = SPEC_SINGLE,
) -> None:
    args = Namespace(
        id=design_id,
        spec=spec_path,
        pr=None,
        items=None,
        trivial=False,
        read_file=_reader(spec_text),
    )
    deliver(backend, args)


def _spec_tree(
    backend: FakeBackend,
    *,
    design_status: str = "in_progress",
    placeholder_notes: str = "",
) -> None:
    """A minted spec container: design child + impl placeholder under it.

    Mirrors `instantiate_spec_shape`'s output -- container `c`, design child
    `d` (`shape-design`), placeholder `p` (`impl-placeholder`, blocked by `d`).
    """
    backend.add("c", title="Objective", type="feature", labels=["shape-spec", "planned"])
    backend.add(
        "d",
        title="Design",
        type="task",
        status=design_status,
        parent="c",
        labels=[DESIGN_CHILD_LABEL],
    )
    backend.add(
        "p",
        title="[Impl] Objective",
        type="task",
        parent="c",
        labels=[IMPL_PLACEHOLDER_LABEL],
        notes=placeholder_notes,
        deps=[DepEdge(id="d", type="blocks", status=design_status)],  # blocked-by the design
    )


def _single(noun: str = "feat") -> Manifest:
    return Manifest(
        items=(ManifestItem(noun=noun, title="Ship the thing", acceptance="it works"),),
        none_reason=None,
    )


def _multi() -> Manifest:
    return Manifest(
        items=(
            ManifestItem(noun="feat", title="Alpha", acceptance="build alpha"),
            ManifestItem(noun="bugfix", title="Beta", acceptance="fix beta"),
        ),
        none_reason=None,
    )


def test_reconcile_single_closes_design_child_and_swaps_labels_last():
    backend = FakeBackend()
    _spec_tree(backend)

    reconcile_placeholder(backend, "p", _single())

    placeholder = backend.get("p")
    assert placeholder.type == "feature"
    assert placeholder.title == "Ship the thing"
    assert backend.acceptance_of("p") == "it works"
    assert set(placeholder.labels) == {"shape-feat", SPEC_READY_LABEL}
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    # C1: the design child closes as part of the shared completion, not a
    # separate step in `deliver` the sweep never reaches.
    assert backend.get("d").status == "closed"


def test_deliver_design_records_manifest_snapshot_in_band():
    # The frozen target: `deliver` parses the spec once and records the parsed
    # manifest as a `[work] manifest:` note, so every later reconcile replays
    # toward it without re-reading the (mutable) spec file.
    backend = FakeBackend()
    _spec_tree(backend)

    _deliver_design(backend, spec_text=SPEC_SINGLE)

    snapshot = manifest_snapshot(backend.get("p").notes)
    assert snapshot == _single()


def test_deliver_design_replay_uses_frozen_snapshot_not_the_spec_file():
    # A crash left the placeholder mid-delivery: snapshot recorded (single feat),
    # handle still on. A replay with a DIFFERENT spec text must reconcile toward
    # the recorded snapshot, not the file -- proving the file is never re-read.
    backend = FakeBackend()
    snapshot_note = f"{MANIFEST_MARKER} {serialize_manifest(_single())}"
    _spec_tree(backend, placeholder_notes=snapshot_note)

    _deliver_design(backend, spec_text=SPEC_MULTI)

    placeholder = backend.get("p")
    assert placeholder.type == "feature"  # single feat, not the multi spec text
    assert "shape-feat" in placeholder.labels
    assert placeholder.children == []  # multi would have minted children here
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    assert backend.get("d").status == "closed"


# --- reconcile sweep: handle-driven, no external-state gate ---


def _snapshot_note(manifest: Manifest) -> str:
    return f"{MANIFEST_MARKER} {serialize_manifest(manifest)}"


def _reconcile(backend: FakeBackend, *, dry_run: bool = False) -> dict:
    # reconcile no longer reads the spec file (it replays toward the in-band
    # snapshot); the injected reader is present only to satisfy the handler
    # signature and must never be consulted.
    args = Namespace(dry_run=dry_run, read_file=_reader("UNREAD"))
    return reconcile(backend, args)["findings"]


def test_reconcile_repairs_pending_placeholder_whose_design_is_still_open():
    # The C1 window: a crash left the handle on with the design child still
    # open. The old gate required the design closed first and skipped this; the
    # handle-driven sweep repairs it and closes the design regardless of status.
    backend = FakeBackend()
    _spec_tree(backend, design_status="in_progress", placeholder_notes=_snapshot_note(_single()))

    findings = _reconcile(backend)

    placeholder = backend.get("p")
    assert placeholder.type == "feature"
    assert "shape-feat" in placeholder.labels
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    assert backend.get("d").status == "closed"
    assert {"id": "p", "kind": "unreconciled_placeholder", "repaired": True} in findings


def test_reconcile_closes_orphaned_open_design_whose_placeholder_is_reconciled():
    # The other side of the C1 window (or an old-code delivery): the placeholder
    # is already fully reconciled (handle gone) but the design child never
    # closed. Enumerated via shape-design, closed via the shared completion.
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec", "planned"])
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add(
        "p",
        type="feature",
        parent="c",
        labels=["shape-feat", SPEC_READY_LABEL],
        notes=_snapshot_note(_single()),  # a reconciled placeholder keeps its snapshot note
        deps=[DepEdge(id="d", type="blocks", status="in_progress")],
    )

    findings = _reconcile(backend)

    assert backend.get("d").status == "closed"
    assert {"id": "d", "kind": "orphaned_design", "repaired": True} in findings


def test_reconcile_leaves_open_design_child_whose_container_has_no_placeholder():
    # A stray non-placeholder sibling must NOT be mistaken for a reconciled
    # placeholder: with no blocks-linked placeholder, nothing proves the delivery
    # finished, so the design child is not this sweep's to close.
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add("x", type="task", parent="c", labels=["shape-chore"])  # ordinary, not a placeholder

    findings = _reconcile(backend)

    assert backend.get("d").status == "in_progress"  # not closed
    assert findings == []


def test_reconcile_ignores_a_non_placeholder_blocks_dependent_of_a_design():
    # A design may be blocked-by unrelated items; only its marker-bearing
    # placeholder proves delivery. A blocks-dependent with no `[work] manifest:`
    # / `[work] spec:` marker must not trigger a close.
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add(
        "unrelated",
        type="task",
        labels=["shape-chore"],  # no placeholder marker, no impl-placeholder handle
        deps=[DepEdge(id="d", type="blocks", status="in_progress")],
    )

    findings = _reconcile(backend)

    assert backend.get("d").status == "in_progress"  # not closed
    assert findings == []


def test_reconcile_ignores_a_non_blocks_dependent_even_with_a_placeholder_marker():
    # Only the blocks-edge links a design to its placeholder; a related-to
    # dependent (even one carrying a manifest marker) is not that relationship.
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add(
        "relative",
        type="task",
        labels=["shape-feat"],
        notes=_snapshot_note(_single()),  # marker present, but linked related-to, not blocks
        deps=[DepEdge(id="d", type="related-to", status="in_progress")],
    )

    findings = _reconcile(backend)

    assert backend.get("d").status == "in_progress"  # not closed
    assert findings == []


def test_reconcile_reports_pending_placeholder_with_no_snapshot_without_repair():
    # No recorded target -> nothing to replay toward. Surface it as an attention
    # finding; never guess intent from residual state.
    backend = FakeBackend()
    _spec_tree(backend, design_status="closed", placeholder_notes="")

    findings = _reconcile(backend)

    assert IMPL_PLACEHOLDER_LABEL in backend.get("p").labels  # untouched
    assert {"id": "p", "kind": "needs_spec", "repaired": False} in findings


def test_reconcile_closes_interrupted_in_progress_leaf_carrying_delivered_marker():
    backend = FakeBackend()
    backend.add("leaf", type="task", status="in_progress", notes=f"{DELIVERED_MARKER} pr#7")

    findings = _reconcile(backend)

    assert backend.get("leaf").status == "closed"
    assert {"id": "leaf", "kind": "interrupted_deliver", "repaired": True} in findings


def test_reconcile_dry_run_reports_findings_without_mutating():
    backend = FakeBackend()
    _spec_tree(backend, design_status="in_progress", placeholder_notes=_snapshot_note(_single()))

    findings = _reconcile(backend, dry_run=True)

    assert IMPL_PLACEHOLDER_LABEL in backend.get("p").labels  # untouched
    assert backend.get("d").status == "in_progress"  # untouched
    assert {"id": "p", "kind": "unreconciled_placeholder", "repaired": False} in findings


def test_reconcile_over_a_healed_tree_finds_nothing():
    backend = FakeBackend()
    _spec_tree(backend, design_status="in_progress", placeholder_notes=_snapshot_note(_single()))

    _reconcile(backend)  # heal
    assert _reconcile(backend) == []  # idempotent second pass


# --- deliver body characterization (multi / none / replay / drift) ---


def test_deliver_design_multi_mints_children_under_placeholder_and_closes_design():
    backend = FakeBackend()
    _spec_tree(backend)

    _deliver_design(backend, spec_text=SPEC_MULTI)

    placeholder = backend.get("p")
    child_titles = {backend.get(cid).title for cid in placeholder.children}
    assert child_titles == {"Alpha", "Beta"}
    # The placeholder is now the impl sub-container: stamped so `claim`/the
    # router treat it as a declared-state container, with the
    # completion handle removed strictly last.
    assert IMPL_CONTAINER_LABEL in placeholder.labels
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    assert backend.get("d").status == "closed"


def test_reconcile_multi_mints_only_the_missing_children():
    # An interrupted expansion already minted "Alpha"; the replay mints only
    # "Beta" (idempotent by title), never a duplicate Alpha (conservation).
    backend = FakeBackend()
    _spec_tree(backend, design_status="in_progress", placeholder_notes=_snapshot_note(_multi()))
    backend.add("alpha", title="Alpha", type="feature", parent="p", labels=["shape-feat"])

    _reconcile(backend)

    titles = [backend.get(cid).title for cid in backend.get("p").children]
    assert sorted(titles) == ["Alpha", "Beta"]
    assert titles.count("Alpha") == 1
    # Re-stamped idempotently across the interrupted expansion's replay.
    assert IMPL_CONTAINER_LABEL in backend.get("p").labels
    assert IMPL_PLACEHOLDER_LABEL not in backend.get("p").labels
    assert backend.get("d").status == "closed"


def test_deliver_design_none_closes_placeholder_with_reason_and_design():
    backend = FakeBackend()
    _spec_tree(backend)

    _deliver_design(backend, spec_text=SPEC_NONE)

    placeholder = backend.get("p")
    assert placeholder.status == "closed"
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    assert "this spec is the deliverable" in placeholder.notes
    assert backend.get("d").status == "closed"


def test_deliver_design_bare_none_closes_without_appending_a_reason_note():
    backend = FakeBackend()
    _spec_tree(backend)

    _deliver_design(backend, spec_text=SPEC_BARE_NONE)

    placeholder = backend.get("p")
    assert placeholder.status == "closed"
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    # bare `- none` carries an empty reason -> only the deliver markers, no
    # spurious empty reason note.
    non_marker = [line for line in backend.note_lines("p") if not line.startswith("[work]")]
    assert non_marker == []


def test_deliver_design_replay_after_completion_is_a_noop():
    backend = FakeBackend()
    _spec_tree(backend)
    _deliver_design(backend, spec_text=SPEC_SINGLE)
    notes_after_first = backend.get("p").notes

    _deliver_design(backend, spec_text=SPEC_SINGLE)  # replay; handle already gone

    assert backend.get("p").notes == notes_after_first  # no new markers appended
    assert IMPL_PLACEHOLDER_LABEL not in backend.get("p").labels


def test_deliver_design_refuses_spec_path_that_mismatches_recorded_marker():
    # The drift guard: a recorded spec path must match this run's --spec, else a
    # later reconcile would replay a stale target. Refuse before any mutation.
    backend = FakeBackend()
    _spec_tree(backend, placeholder_notes=f"{SPEC_MARKER} recorded/path")

    with pytest.raises(WorkError) as exc_info:
        _deliver_design(backend, spec_path="different/path", spec_text=SPEC_SINGLE)

    assert exc_info.value.code == ErrorCode.USAGE
    assert IMPL_PLACEHOLDER_LABEL in backend.get("p").labels  # unmutated


def test_deliver_design_does_not_duplicate_a_spec_marker_already_recorded():
    # An old-code interrupted delivery recorded the spec marker but no snapshot.
    # Re-delivering with the matching --spec adds the snapshot without appending
    # a second spec marker.
    backend = FakeBackend()
    _spec_tree(backend, placeholder_notes=f"{SPEC_MARKER} S")

    _deliver_design(backend, spec_path="S", spec_text=SPEC_SINGLE)

    spec_markers = [line for line in backend.note_lines("p") if line.startswith(SPEC_MARKER)]
    assert len(spec_markers) == 1
    assert manifest_snapshot(backend.get("p").notes) == _single()


def test_reconcile_placeholder_finds_design_sibling_past_a_non_design_child():
    # `_design_sibling` iterates the container's children; a non-design sibling
    # encountered first must be skipped, not mistaken for the design child.
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add("extra", type="task", parent="c", labels=["shape-chore"])  # non-design, first
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add("p", type="task", parent="c", labels=[IMPL_PLACEHOLDER_LABEL])

    reconcile_placeholder(backend, "p", _single())

    assert backend.get("d").status == "closed"
    assert backend.get("extra").status != "closed"  # untouched


def test_reconcile_placeholder_short_circuits_when_handle_already_absent():
    # Idempotent replay: with the handle gone the routine returns before the
    # tail, so it neither relabels the placeholder nor closes the design child
    # (the orphaned-design sweep owns that residual case).
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add("p", type="feature", parent="c", labels=["shape-feat"])

    reconcile_placeholder(backend, "p", _single())

    assert backend.get("p").labels == ["shape-feat"]  # unchanged
    assert backend.get("d").status == "in_progress"  # short-circuit closed nothing


def test_reconcile_placeholder_repairs_a_parentless_placeholder():
    # A hand-built placeholder with no container: no design sibling to close,
    # but the handle still drives reconciliation to completion.
    backend = FakeBackend()
    backend.add("p", type="task", labels=[IMPL_PLACEHOLDER_LABEL])  # parent=None

    reconcile_placeholder(backend, "p", _single())

    assert "shape-feat" in backend.get("p").labels
    assert IMPL_PLACEHOLDER_LABEL not in backend.get("p").labels


def test_reconcile_leaves_a_parentless_open_design_child_alone():
    # The orphaned-design sweep needs a reconciled sibling to prove the delivery
    # finished; a parentless design child has none, so it is never closed.
    backend = FakeBackend()
    backend.add("d", type="task", status="in_progress", labels=[DESIGN_CHILD_LABEL])  # no parent

    findings = _reconcile(backend)

    assert backend.get("d").status == "in_progress"
    assert findings == []


def test_reconcile_dry_run_reports_leaf_and_orphaned_design_without_mutating():
    backend = FakeBackend()
    backend.add("leaf", type="task", status="in_progress", notes=f"{DELIVERED_MARKER} pr#1")
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add("d", type="task", status="in_progress", parent="c", labels=[DESIGN_CHILD_LABEL])
    backend.add(
        "p",
        type="feature",
        parent="c",
        labels=["shape-feat"],
        notes=_snapshot_note(_single()),
        deps=[DepEdge(id="d", type="blocks", status="in_progress")],
    )

    findings = _reconcile(backend, dry_run=True)

    assert backend.get("leaf").status == "in_progress"
    assert backend.get("d").status == "in_progress"
    assert {"id": "leaf", "kind": "interrupted_deliver", "repaired": False} in findings
    assert {"id": "d", "kind": "orphaned_design", "repaired": False} in findings


def test_reconcile_flags_a_corrupt_snapshot_without_aborting_the_sweep():
    # One poisoned placeholder must not block recovery of a healthy one: the
    # typed drift is caught per-item, reported, and the sweep continues.
    backend = FakeBackend()
    _spec_tree(backend, design_status="in_progress", placeholder_notes=_snapshot_note(_single()))
    backend.add("c2", type="feature", labels=["shape-spec"])
    backend.add("d2", type="task", status="in_progress", parent="c2", labels=[DESIGN_CHILD_LABEL])
    backend.add(
        "p2",
        type="task",
        parent="c2",
        labels=[IMPL_PLACEHOLDER_LABEL],
        notes=f"{MANIFEST_MARKER} {{not valid json",
        deps=[DepEdge(id="d2", type="blocks", status="in_progress")],
    )

    findings = _reconcile(backend)

    # healthy placeholder repaired; poisoned one flagged, handle intact
    assert IMPL_PLACEHOLDER_LABEL not in backend.get("p").labels
    assert IMPL_PLACEHOLDER_LABEL in backend.get("p2").labels
    assert {"id": "p2", "kind": "corrupt_snapshot", "repaired": False} in findings


def test_deliver_design_on_a_corrupt_snapshot_raises_typed_drift():
    backend = FakeBackend()
    _spec_tree(backend, placeholder_notes=f"{MANIFEST_MARKER} {{not valid json")

    with pytest.raises(WorkError) as exc_info:
        _deliver_design(backend, spec_text=SPEC_SINGLE)

    assert exc_info.value.code == ErrorCode.BACKEND_DRIFT


def test_reconcile_ignores_in_progress_leaf_without_a_delivered_marker():
    backend = FakeBackend()
    backend.add("leaf", type="task", status="in_progress", notes="just working on it")

    findings = _reconcile(backend)

    assert backend.get("leaf").status == "in_progress"  # not a delivery in flight
    assert findings == []


def test_reconcile_repairs_pending_placeholder_with_no_design_sibling():
    # The recorded snapshot -- written only at design delivery -- is itself the
    # "design done" signal, so a placeholder carrying one is repaired even when
    # no design child exists to close (a hand-built or legacy tree). The handle
    # is the sole gate; there is simply nothing to close.
    backend = FakeBackend()
    backend.add("c", type="feature", labels=["shape-spec"])
    backend.add(
        "p",
        type="task",
        parent="c",
        labels=[IMPL_PLACEHOLDER_LABEL],
        notes=_snapshot_note(_single()),
    )

    findings = _reconcile(backend)

    placeholder = backend.get("p")
    assert "shape-feat" in placeholder.labels
    assert IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    assert {"id": "p", "kind": "unreconciled_placeholder", "repaired": True} in findings


# --- creating-spec recovery: interrupted spec instantiation ---


def _creating_spec_container(backend: FakeBackend, *, with_design=False, with_placeholder=False):
    """A spec container mid-instantiation: carries `creating-spec`, not yet
    `planned`. `with_design`/`with_placeholder` seed the children a partial crash
    would have already minted before dying."""
    backend.add("c", title="T", type="feature", labels=["shape-spec", CREATING_SPEC_LABEL])
    if with_design:
        backend.add("d", title="Design: T", type="task", parent="c", labels=[DESIGN_CHILD_LABEL])
    if with_placeholder:
        backend.add(
            "p",
            title="[Impl] T (scope: per spec)",
            type="task",
            parent="c",
            labels=[IMPL_PLACEHOLDER_LABEL],
            deps=[DepEdge(id="d", type="blocks", status="open")],
        )


def test_instantiate_spec_shape_is_idempotent_when_both_children_exist():
    # A replay (reconcile sweep, or a re-run) over a container whose design child
    # and placeholder already exist must find-or-create: return the existing ids,
    # mint nothing new -- no duplicate template children.
    backend = FakeBackend()
    _creating_spec_container(backend, with_design=True, with_placeholder=True)

    design_id, placeholder_id = instantiate_spec_shape(backend, "c", "T")

    assert (design_id, placeholder_id) == ("d", "p")
    assert sorted(backend.get("c").children) == ["d", "p"]


def test_instantiate_spec_shape_ignores_children_that_are_neither_design_nor_placeholder():
    # Defensive: a stray child under the container (neither `shape-design` nor
    # `impl-placeholder`) is skipped by the find-or-create scan -- the real
    # design child + placeholder are still located, nothing duplicated.
    backend = FakeBackend()
    _creating_spec_container(backend, with_design=True, with_placeholder=True)
    backend.add("stray", title="unrelated", type="task", parent="c", labels=["shape-chore"])

    design_id, placeholder_id = instantiate_spec_shape(backend, "c", "T")

    assert (design_id, placeholder_id) == ("d", "p")
    assert sorted(backend.get("c").children) == ["d", "p", "stray"]


def _assert_instantiation_healed(backend: FakeBackend) -> None:
    """The healed end-state of an interrupted spec instantiation: `planned` on,
    `creating-spec` off, exactly one design child + one placeholder minted."""
    container = backend.get("c")
    assert "planned" in container.labels
    assert CREATING_SPEC_LABEL not in container.labels
    child_labels = [backend.get(cid).labels for cid in container.children]
    design = [ls for ls in child_labels if DESIGN_CHILD_LABEL in ls]
    placeholder = [ls for ls in child_labels if IMPL_PLACEHOLDER_LABEL in ls]
    assert len(design) == 1
    assert len(placeholder) == 1


def test_reconcile_heals_interrupted_instantiation_with_no_children():
    # A crash right after the container was born (`creating-spec` on, no children
    # yet): the sweep mints the whole template, stamps `planned`, drops the
    # handle last -- reaching the same state a clean `create spec` would.
    backend = FakeBackend()
    _creating_spec_container(backend)  # no children

    findings = _reconcile(backend)

    _assert_instantiation_healed(backend)
    assert {"id": "c", "kind": "interrupted_instantiation", "repaired": True} in findings


def test_reconcile_heals_interrupted_instantiation_with_only_design_child():
    # A crash after the design child was minted but before the placeholder: the
    # idempotent replay mints only the missing placeholder, never a second design.
    backend = FakeBackend()
    _creating_spec_container(backend, with_design=True)  # design only, no placeholder

    findings = _reconcile(backend)

    _assert_instantiation_healed(backend)
    # the pre-existing design child is reused, not duplicated
    designs = [
        cid for cid in backend.get("c").children if DESIGN_CHILD_LABEL in backend.get(cid).labels
    ]
    assert designs == ["d"]
    assert {"id": "c", "kind": "interrupted_instantiation", "repaired": True} in findings


def test_reconcile_heals_interrupted_instantiation_with_both_children_not_yet_planned():
    # A crash after both template children exist but before `planned` was stamped
    # (`creating-spec` still on): the sweep mints nothing, only stamps `planned`
    # and drops the handle -- no duplicate children.
    backend = FakeBackend()
    _creating_spec_container(backend, with_design=True, with_placeholder=True)

    findings = _reconcile(backend)

    _assert_instantiation_healed(backend)
    assert sorted(backend.get("c").children) == ["d", "p"]  # no duplicates minted
    assert {"id": "c", "kind": "interrupted_instantiation", "repaired": True} in findings


def test_reconcile_interrupted_instantiation_dry_run_reports_without_mutating():
    backend = FakeBackend()
    _creating_spec_container(backend)  # no children

    findings = _reconcile(backend, dry_run=True)

    container = backend.get("c")
    assert CREATING_SPEC_LABEL in container.labels  # untouched
    assert "planned" not in container.labels
    assert container.children == []  # nothing minted
    assert {"id": "c", "kind": "interrupted_instantiation", "repaired": False} in findings


def test_reconcile_over_a_healed_instantiation_finds_no_creating_spec():
    backend = FakeBackend()
    _creating_spec_container(backend)

    _reconcile(backend)  # heal
    second = _reconcile(backend)  # idempotent second pass

    assert not any(f["kind"] == "interrupted_instantiation" for f in second)


def test_reconcile_heals_promote_crash_before_the_shape_feat_to_spec_swap():
    # `promote` adds `creating-spec` FIRST, then swaps shape-feat->shape-spec in
    # later calls. A crash in that window leaves a still-`shape-feat` item under
    # the handle. The sweep must reconstruct the container shape (not just replay
    # create-spec's tail), else it heals a children-bearing item that is_container
    # rejects -- a claimable leaf with children, unrepairable once the handle is
    # gone. Healed state must be a real container: shape-spec on, shape-feat off.
    backend = FakeBackend()
    backend.add("c", title="T", type="feature", labels=["shape-feat", CREATING_SPEC_LABEL])

    findings = _reconcile(backend)

    container = backend.get("c")
    assert "shape-spec" in container.labels
    assert "shape-feat" not in container.labels
    assert is_container(container)  # claim() now correctly refuses it as a container
    _assert_instantiation_healed(backend)
    assert {"id": "c", "kind": "interrupted_instantiation", "repaired": True} in findings


# --- wgclw.9.8: leaked creating-spec on a container's own children ---
#
# bd copies a parent's current labels onto a `--parent` child by default, so
# before the adapter opted out (`--no-inherit-labels`), a design child /
# placeholder minted while their container still carried `creating-spec`
# (removed from the container STRICTLY LAST, after both children exist) came
# back from bd carrying `creating-spec` themselves -- verified against real
# bd 1.0.3. `_sweep_interrupted_instantiations` must never mistake such a
# leaf for a mid-instantiation container: it heals the leaked handle instead
# of re-finalizing the child as its own planned spec container.


def _legacy_spec_tree_with_leaked_creating_spec(backend: FakeBackend) -> None:
    """A fully instantiated, already-`planned` spec tree as a live bd install
    left it BEFORE the adapter disabled label inheritance: the container's own
    `creating-spec` is off (removed last, per `finalize_spec_instantiation`),
    but the design child and placeholder it minted while that label was still
    on the container inherited it -- unlike `_spec_tree()` above, which models
    the label set the fixed adapter now guarantees."""
    backend.add("c", title="Objective", type="feature", labels=["shape-spec", "planned"])
    backend.add(
        "d",
        title="Design: Objective",
        type="task",
        parent="c",
        labels=[DESIGN_CHILD_LABEL, CREATING_SPEC_LABEL],
    )
    backend.add(
        "p",
        title="[Impl] Objective (scope: per spec)",
        type="task",
        parent="c",
        labels=[IMPL_PLACEHOLDER_LABEL, CREATING_SPEC_LABEL],
        deps=[DepEdge(id="d", type="blocks", status="open")],
    )


def test_reconcile_leaves_a_healthy_spec_tree_byte_unchanged():
    # Acceptance criterion (wgclw.9.8): reconcile over an already-healthy,
    # already-`planned` spec tree (clean labels, as the fixed adapter mints
    # them) performs zero mutations. The undelivered placeholder still
    # surfaces as an attention finding (needs_spec) -- reporting is not
    # mutation.
    backend = FakeBackend()
    _spec_tree(backend, design_status="open")
    before = {item_id: backend.get(item_id) for item_id in ("c", "d", "p")}

    findings = _reconcile(backend)

    after = {item_id: backend.get(item_id) for item_id in ("c", "d", "p")}
    assert after == before
    assert findings == [{"id": "p", "kind": "needs_spec", "repaired": False}]


def test_reconcile_heals_leaked_creating_spec_children_without_refinalizing():
    # Legacy trees minted before the adapter's --no-inherit-labels opt-out:
    # the sweep strips the leaked handle from the container's own children and
    # must NOT finalize them as containers (no `planned`, no grandchildren).
    backend = FakeBackend()
    _legacy_spec_tree_with_leaked_creating_spec(backend)

    findings = _reconcile(backend)

    for child_id in ("d", "p"):
        child = backend.get(child_id)
        assert CREATING_SPEC_LABEL not in child.labels  # leak healed
        assert "planned" not in child.labels  # not re-finalized as a container
        assert "shape-spec" not in child.labels
        assert child.children == []  # no spurious grandchildren minted
    assert {"id": "d", "kind": "leaked_creating_spec", "repaired": True} in findings
    assert {"id": "p", "kind": "leaked_creating_spec", "repaired": True} in findings

    # Once healed, a second sweep performs zero mutations (true idempotency).
    before = {item_id: backend.get(item_id) for item_id in ("c", "d", "p")}
    second = _reconcile(backend)
    assert {item_id: backend.get(item_id) for item_id in ("c", "d", "p")} == before
    assert all(finding["repaired"] is False for finding in second)


def test_reconcile_dry_run_reports_leaked_creating_spec_without_mutating():
    backend = FakeBackend()
    _legacy_spec_tree_with_leaked_creating_spec(backend)
    before = {item_id: backend.get(item_id) for item_id in ("c", "d", "p")}

    findings = _reconcile(backend, dry_run=True)

    assert {item_id: backend.get(item_id) for item_id in ("c", "d", "p")} == before
    assert {"id": "d", "kind": "leaked_creating_spec", "repaired": False} in findings
    assert {"id": "p", "kind": "leaked_creating_spec", "repaired": False} in findings


def test_reconcile_does_not_clobber_a_freshly_reconciled_placeholders_manifest_shape():
    # Acceptance criterion (wgclw.9.8), crash-mid-deliver path on a legacy
    # tree: within ONE `reconcile` call, `_sweep_pending_placeholders`
    # reconciles the placeholder to its manifest noun (shape-feat) and strips
    # the leaked `creating-spec` with the handle, so the later
    # `_sweep_interrupted_instantiations` never sees the healed leaf and its
    # manifest-noun shape survives.
    backend = FakeBackend()
    backend.add("c", title="Objective", type="feature", labels=["shape-spec", "planned"])
    backend.add(
        "d",
        title="Design",
        type="task",
        status="in_progress",
        parent="c",
        labels=[DESIGN_CHILD_LABEL, CREATING_SPEC_LABEL],  # leaked (wgclw.9.8)
    )
    backend.add(
        "p",
        title="[Impl] Objective",
        type="task",
        parent="c",
        labels=[IMPL_PLACEHOLDER_LABEL, CREATING_SPEC_LABEL],  # leaked (wgclw.9.8)
        notes=_snapshot_note(_single()),
        deps=[DepEdge(id="d", type="blocks", status="in_progress")],
    )

    _reconcile(backend)

    placeholder = backend.get("p")
    assert "shape-feat" in placeholder.labels  # its manifest-noun shape survives
    assert "shape-spec" not in placeholder.labels  # not wrongly re-finalized as a container
    assert "planned" not in placeholder.labels
    assert CREATING_SPEC_LABEL not in placeholder.labels  # leak healed with the handle
    assert placeholder.children == []  # no spurious grandchildren minted
