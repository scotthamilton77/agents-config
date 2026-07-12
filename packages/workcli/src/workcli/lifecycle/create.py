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
    """Create the design child + blocked placeholder under an existing container.

    Returns (design_child_id, placeholder_id). Does NOT stamp `planned` --
    the caller stamps it LAST (L16). Records the `impl-placeholder` label on
    the placeholder; the design child gets `shape-design`.
    """
    design_child_id = backend.create(
        CreateFields(
            title=f"Design: {title}",
            type="task",
            parent=container_id,
            labels=(DESIGN_CHILD_LABEL,),
        )
    )
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
            labels=(template.shape_label,),
            acceptance=args.acceptance,
        )
    )
    if args.orphan:
        backend.append_note(container_id, ORPHAN_MARKER)
    design_child_id, placeholder_id = instantiate_spec_shape(backend, container_id, args.title)
    # Stamped strictly last (L16): an interrupted create leaves an
    # unplanned, self-reporting container in the Planning queue rather than
    # a queue-invisible one.
    backend.label_mutate("add", container_id, [PLANNED_LABEL])
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
