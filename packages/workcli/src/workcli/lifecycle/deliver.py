"""`deliver` -- evidence-gated leaf delivery + design-spec placeholder
reconciliation (plan Task 5, test-plan items 4, 5, 6).

Dispatches on the `shape-design` label (CLI surface table): a design
child's `deliver` parses the merged spec's `## Continuations` manifest and
reconciles the sibling placeholder (L7/L8); a leaf's `deliver` verifies
bd-observable evidence before recording the `[work] delivered:` marker and
closing. A container is refused outright -- it completes via close-walk when
its children close, never through `deliver`. `reconcile_placeholder` is
exported for reuse by `reconcile` (Task 6) -- it is short-circuit idempotent
on the `impl-placeholder` label's absence.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle import (
    DELIVERED_MARKER,
    MANIFEST_MARKER,
    SPEC_MARKER,
    has_marker,
    is_container,
    manifest_snapshot,
    spec_path,
)
from workcli.lifecycle.manifest import Manifest, parse_continuations, serialize_manifest
from workcli.lifecycle.nouns import (
    DESIGN_CHILD_LABEL,
    IMPL_CONTAINER_LABEL,
    IMPL_PLACEHOLDER_LABEL,
    NOUN_TEMPLATES,
    SPEC_READY_LABEL,
    Noun,
)
from workcli.model import CreateFields, Item, UpdateFields


def _closed(item_id: str) -> JsonValue:
    return {"id": item_id, "status": "closed"}


def _sibling_placeholder(backend: Backend, design_item: Item) -> Item:
    """The design child's one sibling under their shared container.

    `instantiate_spec_shape` mints exactly two children under a spec
    container -- the design child and the placeholder -- and reconciliation
    never adds a third (multi-unit expansion mints under the *placeholder*,
    not the container), so "the other child" is always the placeholder,
    identified structurally rather than by its `impl-placeholder` label
    (which a fully-reconciled placeholder no longer carries).

    Backend state that breaks that spec-shape invariant is corruption, not
    an internal bug, so each break surfaces as a typed `E_BACKEND_DRIFT`
    carrying the offending ids for repair rather than an opaque
    `TypeError`/`StopIteration` reported as `E_INTERNAL`:
    a design child with no parent container, a container with no sibling
    placeholder, or a container with an ambiguous (>1) non-design sibling set.
    """
    if design_item.parent is None:
        raise WorkError(
            ErrorCode.BACKEND_DRIFT,
            f"deliver {design_item.id}: design item has no parent container",
            detail={"design_id": design_item.id},
        )
    parent = backend.get(design_item.parent)
    siblings = [child_id for child_id in parent.children if child_id != design_item.id]
    if not siblings:
        raise WorkError(
            ErrorCode.BACKEND_DRIFT,
            f"deliver {design_item.id}: container {parent.id} has no sibling placeholder",
            detail={"design_id": design_item.id, "container_id": parent.id, "sibling_ids": []},
        )
    if len(siblings) > 1:
        raise WorkError(
            ErrorCode.BACKEND_DRIFT,
            (
                f"deliver {design_item.id}: container {parent.id} has an ambiguous sibling "
                f"set (expected exactly one placeholder, found {len(siblings)})"
            ),
            detail={
                "design_id": design_item.id,
                "container_id": parent.id,
                "sibling_ids": [child_id for child_id in siblings],
            },
        )
    return backend.get(siblings[0])


def _deliver_design(backend: Backend, args: Namespace, design_item: Item) -> JsonValue:
    leaf_flags = [
        name
        for name, value in (("--pr", args.pr), ("--items", args.items), ("--trivial", args.trivial))
        if value
    ]
    if leaf_flags:
        raise WorkError(
            ErrorCode.USAGE,
            f"deliver {args.id}: {', '.join(leaf_flags)} belong to leaf delivery; "
            f"omit for a design child",
        )
    if args.spec is None:
        raise WorkError(ErrorCode.USAGE, f"deliver {args.id}: design delivery requires --spec")

    placeholder = _sibling_placeholder(backend, design_item)
    if design_item.status == "closed" and IMPL_PLACEHOLDER_LABEL not in placeholder.labels:
        return _closed(args.id)

    # Guard against recovery drift: a partial/previous run may have recorded a
    # spec path on the placeholder. If it differs from this run's --spec,
    # reconciling now would leave the recorded marker stale, so a later
    # `work reconcile` would parse the wrong manifest. Refuse before any read
    # or mutation; a matching path is an idempotent replay (skip the append).
    recorded_spec = spec_path(placeholder.notes)
    if recorded_spec is not None and recorded_spec != args.spec:
        raise WorkError(
            ErrorCode.USAGE,
            (
                f"deliver {args.id}: placeholder {placeholder.id} already recorded spec "
                f"'{recorded_spec}'; the design reconciled against that path. Re-run with "
                f"--spec '{recorded_spec}' (or run `work reconcile`) instead of --spec "
                f"'{args.spec}' to avoid recovery drift."
            ),
            detail={
                "design_id": args.id,
                "placeholder_id": placeholder.id,
                "recorded_spec": recorded_spec,
                "requested_spec": args.spec,
            },
        )

    # Replay toward the frozen in-band snapshot when one exists; only the first
    # delivery parses the spec file and records the target (spec §6, L7), so a
    # post-delivery edit to the file can never alter a committed unit. `manifest:`
    # and `spec:` are written together at first delivery, but the appends are
    # gated independently: an old bead carrying only a `spec:` marker (pre-snapshot
    # delivery, interrupted) gets the snapshot added without a duplicate `spec:`.
    manifest = manifest_snapshot(placeholder.notes)
    if manifest is None:
        manifest = parse_continuations(args.read_file(args.spec))
        if recorded_spec is None:
            backend.append_note(placeholder.id, f"{SPEC_MARKER} {args.spec}")
        backend.append_note(placeholder.id, f"{MANIFEST_MARKER} {serialize_manifest(manifest)}")
    # reconcile_placeholder re-fetches the placeholder by id: its contract is a
    # standalone idempotent entry point that `reconcile` reuses with only an id
    # in hand, so the second get() is the price of that reuse. It also closes
    # the design child (args.id) as its shared completion tail -- deliver no
    # longer closes it separately, so the sweep reaches the identical routine.
    reconcile_placeholder(backend, placeholder.id, manifest)
    return _closed(args.id)


def _leaf_evidence(backend: Backend, args: Namespace) -> str:
    """Verify + describe the evidence for a leaf `deliver` (plan L8).

    `--pr` is caller-attested (no bd verification); `--items` is verified
    via `batch_get` -- a miss surfaces `E_NOT_FOUND`, translated here to
    `E_EVIDENCE` because the items themselves ARE the evidence, not a lookup
    target; `--trivial` records a bare acknowledgement. Absent all three,
    there is no evidence to record.
    """
    if args.pr is not None:
        return str(args.pr)
    if args.items is not None:
        try:
            backend.batch_get(args.items.split(","))
        except WorkError as not_found:
            if not_found.code != ErrorCode.NOT_FOUND:
                raise
            raise WorkError(
                ErrorCode.EVIDENCE,
                f"deliver {args.id}: --items evidence not found: {not_found.message}",
                detail=not_found.detail,
            ) from not_found
        return f"items:{args.items}"
    if args.trivial:
        return "trivial"
    raise WorkError(
        ErrorCode.EVIDENCE,
        f"deliver {args.id}: requires one of --pr, --items, or --trivial",
    )


def _deliver_leaf(backend: Backend, args: Namespace, item: Item) -> JsonValue:
    if args.spec is not None:
        raise WorkError(
            ErrorCode.USAGE,
            f"deliver {args.id}: --spec belongs to design delivery; omit for a leaf",
        )
    if item.status == "closed":
        return _closed(args.id)

    evidence = _leaf_evidence(backend, args)
    if not has_marker(item.notes, DELIVERED_MARKER):
        backend.append_note(args.id, f"{DELIVERED_MARKER} {evidence}")
    backend.close([args.id])
    return _closed(args.id)


def deliver(backend: Backend, args: Namespace) -> JsonValue:
    """`work deliver ID [--spec PATH] [--pr REF] [--items ID,ID] [--trivial]` (plan L8)."""
    item = backend.get(args.id)
    if DESIGN_CHILD_LABEL in item.labels:
        return _deliver_design(backend, args, item)
    # A container is never delivered directly: it closes via close-walk when its
    # children close (spec §6/§8). Refuse at dispatch -- before any evidence
    # check or leaf mutation -- so `deliver` on a spec/epic/`shape-impl-container`
    # fails loud instead of silently recording a leaf delivery on a container.
    if is_container(item):
        raise WorkError(
            ErrorCode.USAGE,
            (
                f"deliver {args.id}: {args.id} is a container; a container closes via "
                f"close-walk when its children close, not through `deliver`"
            ),
        )
    return _deliver_leaf(backend, args, item)


def _reconcile_single(backend: Backend, placeholder_id: str, manifest: Manifest) -> None:
    # Add the shape + spec-ready labels here; `impl-placeholder` is removed by
    # the shared completion tail, STRICTLY LAST (C2 -- an add-then-remove-here
    # order would, on a crash between the two, strand the placeholder without
    # its shape label yet already off the sweep's handle).
    item = manifest.items[0]
    template = NOUN_TEMPLATES[Noun(item.noun)]
    backend.set_type(placeholder_id, template.bd_type)
    backend.set_fields(placeholder_id, UpdateFields(title=item.title))
    backend.set_acceptance(placeholder_id, item.acceptance)
    backend.label_mutate("add", placeholder_id, [template.shape_label, SPEC_READY_LABEL])


def _reconcile_multi(backend: Backend, placeholder: Item, manifest: Manifest) -> None:
    # One order-preserving batch_get instead of an N+1 get()-per-child loop
    # (empty children -> zero bd calls, per the batch_get empty-ids pin).
    existing_titles = {child.title for child in backend.batch_get(list(placeholder.children))}
    for item in manifest.items:
        if item.title in existing_titles:
            continue
        template = NOUN_TEMPLATES[Noun(item.noun)]
        backend.create(
            CreateFields(
                title=item.title,
                type=template.bd_type,
                parent=placeholder.id,
                labels=(template.shape_label,),
                acceptance=item.acceptance,
            )
        )
    # Stamp the placeholder as the impl sub-container so `claim` and the router
    # treat it as a declared-state container (spec §6 -- keyed on the label, not
    # child count). Idempotent (label add is set-union), so an interrupted
    # expansion replays through the still-present handle and re-stamps
    # harmlessly. Applied BEFORE the shared tail removes `impl-placeholder`
    # last: that handle is the queryable signal `reconcile` enumerates
    # interrupted expansions through, dropped only once every child exists AND
    # the design child has closed (L10).
    backend.label_mutate("add", placeholder.id, [IMPL_CONTAINER_LABEL])


def _design_sibling(backend: Backend, placeholder: Item) -> Item | None:
    """The `shape-design` child sharing the placeholder's container, or None.

    `instantiate_spec_shape` mints exactly a design child + this placeholder
    under one container, so at most one sibling carries `shape-design`. None
    when the placeholder has no parent or no such sibling (a legacy or
    hand-built tree) -- the caller treats a missing design sibling as nothing
    to close, never an error: the placeholder handle alone drives completion.
    """
    if placeholder.parent is None:
        return None
    container = backend.get(placeholder.parent)
    for child_id in container.children:
        if child_id == placeholder.id:
            continue
        child = backend.get(child_id)
        if DESIGN_CHILD_LABEL in child.labels:
            return child
    return None


def reconcile_placeholder(backend: Backend, placeholder_id: str, manifest: Manifest) -> None:
    """Idempotently complete one placeholder's delivery against a parsed manifest
    (spec §6) -- the single completion routine both `deliver` and the `reconcile`
    sweep call, so every crash point heals to the same final state.

    Body, by manifest shape:
    none -> close the placeholder + reason note (only when non-empty);
    single -> set_type + retitle + set_acceptance + add shape label (+ spec-ready);
    multi -> mint the MISSING children (compared to existing by title) + stamp
    `shape-impl-container` on the placeholder.

    Then the shared tail, unconditionally: close the design child, then remove
    `impl-placeholder` STRICTLY LAST. That ordering (C1/C2, L10) makes the
    handle's absence the sole "delivery wholly done" signal -- no body path
    removes it -- so a replay short-circuits on its absence and a crash anywhere
    leaves it present for the sweep.
    """
    placeholder = backend.get(placeholder_id)
    if IMPL_PLACEHOLDER_LABEL not in placeholder.labels:
        return

    if manifest.none_reason is not None:
        backend.close([placeholder_id])
        # A bare `- none` carries an empty reason (manifest.py::_none_reason);
        # only record a note when there is real reason text -- never append an
        # empty note.
        if manifest.none_reason:
            backend.append_note(placeholder_id, manifest.none_reason)
    elif len(manifest.items) == 1:
        _reconcile_single(backend, placeholder_id, manifest)
    else:
        _reconcile_multi(backend, placeholder, manifest)

    design = _design_sibling(backend, placeholder)
    if design is not None and design.status != "closed":
        backend.close([design.id])
    backend.label_mutate("remove", placeholder_id, [IMPL_PLACEHOLDER_LABEL])
