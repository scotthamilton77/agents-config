"""`work create <noun>` -- noun-templated creation (plan Task 3).

`create_noun` is the lifecycle layer's public creation mode, dispatched to
from `verbs/__init__.py`'s `create` router (never called directly by
`--raw`, which stays the transport primitive in `verbs/write.py`).
`instantiate_spec_shape` is shared with `promote` (Task 4): it mints the
design child + blocked placeholder under an existing container and never
stamps `planned` -- the caller stamps it strictly last (L16).
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.lifecycle import ORPHAN_MARKER
from workcli.lifecycle.nouns import (
    CREATING_SPEC_LABEL,
    DESIGN_CHILD_LABEL,
    IMPL_PLACEHOLDER_LABEL,
    NOUN_TEMPLATES,
    PLANNED_LABEL,
    SPEC_READY_LABEL,
    Noun,
    NounTemplate,
)
from workcli.model import CreateFields


def instantiate_spec_shape(backend: Backend, container_id: str, title: str) -> tuple[str, str]:
    """Find-or-create the design child + blocked placeholder under a container.

    Returns (design_child_id, placeholder_id). **Idempotent** (spec §6, L16):
    a child already carrying `shape-design` / `impl-placeholder` under the
    container is reused, never duplicated -- so the `reconcile` sweep (or a
    re-run) that replays an interrupted instantiation mints only what a partial
    crash left missing. Does NOT stamp `planned` or touch `creating-spec` -- the
    caller owns that ordering (planned last, `creating-spec` removed after).
    """
    design_child_id: str | None = None
    placeholder_id: str | None = None
    for child_id in backend.get(container_id).children:
        child = backend.get(child_id)
        if DESIGN_CHILD_LABEL in child.labels:
            design_child_id = child_id
        elif IMPL_PLACEHOLDER_LABEL in child.labels:
            placeholder_id = child_id

    if design_child_id is None:
        design_child_id = backend.create(
            CreateFields(
                title=f"Design: {title}",
                type="task",
                parent=container_id,
                labels=(DESIGN_CHILD_LABEL,),
            )
        )
    if placeholder_id is None:
        placeholder_id = backend.create(
            CreateFields(
                title=f"[Impl] {title} (scope: per spec)",
                type="task",
                parent=container_id,
                labels=(IMPL_PLACEHOLDER_LABEL,),
                blocked_by=design_child_id,
            )
        )
    return design_child_id, placeholder_id


def finalize_spec_instantiation(backend: Backend, container_id: str, title: str) -> tuple[str, str]:
    """Idempotently complete a spec container born under `creating-spec`.

    The single source of the L16 completion tail shared by `create spec`,
    `promote`, and the `reconcile` sweep -- triplicating it is what let the
    `promote` crash window drift open. Every step is idempotent, so replaying it
    over any crash point (or a fully healed container) converges:

    1. Ensure the container *shape* (`shape-spec` on, `shape-feat` off). `create
       spec` births the container already `shape-spec`, so this is a no-op there;
       `promote` adds `creating-spec` before its own swap, so a crash in that
       window leaves a `shape-feat` item -- this is the *only* path that
       reconstructs the swap, without which the sweep would heal a children-
       bearing item that `is_container` rejects (a claimable leaf with children).
    2. Mint only the template children a partial crash left missing.
    3. Stamp `planned`, then remove the `creating-spec` handle STRICTLY LAST.

    Returns (design_child_id, placeholder_id).
    """
    backend.label_mutate("add", container_id, ["shape-spec"])
    backend.label_mutate("remove", container_id, ["shape-feat"])
    design_child_id, placeholder_id = instantiate_spec_shape(backend, container_id, title)
    backend.label_mutate("add", container_id, [PLANNED_LABEL])
    backend.label_mutate("remove", container_id, [CREATING_SPEC_LABEL])
    return design_child_id, placeholder_id


def _validate_usage(args: Namespace, noun: Noun) -> None:
    if args.type is not None:
        raise WorkError(
            ErrorCode.USAGE,
            f"create {noun}: --type is set by the noun; omit it",
        )
    if args.label:
        raise WorkError(
            ErrorCode.USAGE,
            f"create {noun}: labels are set by the noun; omit --label",
        )
    if args.spec is not None and args.trivial:
        raise WorkError(
            ErrorCode.USAGE,
            f"create {noun}: --spec and --trivial are mutually exclusive",
        )
    has_parent = args.parent is not None
    if has_parent == args.orphan:
        raise WorkError(
            ErrorCode.USAGE,
            f"create {noun}: exactly one of --parent or --orphan is required",
        )


def _check_duplicate_title(backend: Backend, title: str) -> None:
    matches = backend.search(title)
    collision = next((item for item in matches if item.title == title), None)
    if collision is not None:
        raise WorkError(
            ErrorCode.DUPLICATE_TITLE,
            f"an item titled {title!r} already exists: {collision.id}",
            detail={"id": collision.id},
        )


def _create_spec_container(
    backend: Backend, args: Namespace, template: NounTemplate, parent: str | None
) -> JsonValue:
    container_id = backend.create(
        CreateFields(
            title=args.title,
            description=args.description,
            type=template.bd_type,
            priority=args.priority,
            parent=parent,
            labels=(template.shape_label, CREATING_SPEC_LABEL),
            acceptance=args.acceptance,
        )
    )
    if args.orphan:
        backend.append_note(container_id, ORPHAN_MARKER)
    # The completion tail (mint children, stamp `planned`, drop `creating-spec`
    # strictly last -- L16) is shared with `promote` and the `reconcile` sweep.
    # A crash anywhere before the handle comes off leaves a `shape-spec`
    # container that is NOT `planned` and still carries `creating-spec`: it
    # self-reports into the Planning queue (visible) AND is finished by the sweep
    # through the handle (auto-recoverable). Both nets fire.
    design_child_id, placeholder_id = finalize_spec_instantiation(backend, container_id, args.title)
    return {"id": container_id, "design_child": design_child_id, "placeholder": placeholder_id}


def create_noun(backend: Backend, args: Namespace) -> JsonValue:
    """`work create <noun> --title T (--parent ID | --orphan) [...]` (plan L9/L13/L14/L16)."""
    noun = Noun(args.noun)
    template = NOUN_TEMPLATES[noun]

    _validate_usage(args, noun)
    _check_duplicate_title(backend, args.title)

    parent = None if args.orphan else args.parent

    if noun is Noun.SPEC:
        return _create_spec_container(backend, args, template, parent)

    labels = [template.shape_label]
    if template.expects_evidence and (args.spec is not None or args.trivial):
        labels.append(SPEC_READY_LABEL)

    new_id = backend.create(
        CreateFields(
            title=args.title,
            description=args.description,
            type=template.bd_type,
            priority=args.priority,
            parent=parent,
            labels=tuple(labels),
            acceptance=args.acceptance,
        )
    )
    if args.orphan:
        backend.append_note(new_id, ORPHAN_MARKER)
    return {"id": new_id}
