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
from workcli.tracks import TRACK_PREFIX, derive_track, require_known_track, track_label

# The reserved-namespace wall for additive `--label` (S2-D7): labels that
# forge lifecycle state are refused at usage-validation time, before any
# backend call. `parked` is a string literal until the park verbs (slice
# S2-B) mint its constant.
_RESERVED_LABEL_EXACT = frozenset(
    {PLANNED_LABEL, CREATING_SPEC_LABEL, IMPL_PLACEHOLDER_LABEL, SPEC_READY_LABEL, "parked"}
)
_RESERVED_LABEL_PREFIXES = ("shape-", TRACK_PREFIX)


def instantiate_spec_shape(
    backend: Backend, container_id: str, title: str, track: str | None = None
) -> tuple[str, str]:
    """Find-or-create the design child + blocked placeholder under a container.

    Returns (design_child_id, placeholder_id). **Idempotent** (spec §6, L16):
    a child already carrying `shape-design` / `impl-placeholder` under the
    container is reused, never duplicated -- so the `reconcile` sweep (or a
    re-run) that replays an interrupted instantiation mints only what a partial
    crash left missing. Does NOT stamp `planned` or touch `creating-spec` -- the
    caller owns that ordering (planned last, `creating-spec` removed after).

    `track` defaults to None for the `promote`/`reconcile`/crash-replay call
    sites, which self-derive from the container's own labels below -- a
    tracked container finished by those paths still stamps its children
    (pure derivation, no config needed).
    """
    container = backend.get(container_id)
    if track is None:
        # promote/reconcile/crash-replay path: children inherit the
        # container's own derived track so an interrupted tracked create
        # never mints lint violations (config-free derivation).
        track = derive_track(container.labels)
    design_child_id: str | None = None
    placeholder_id: str | None = None
    for child_id in container.children:
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
                labels=(DESIGN_CHILD_LABEL,) + ((track_label(track),) if track is not None else ()),
            )
        )
    if placeholder_id is None:
        placeholder_id = backend.create(
            CreateFields(
                title=f"[Impl] {title} (scope: per spec)",
                type="task",
                parent=container_id,
                labels=(IMPL_PLACEHOLDER_LABEL,)
                + ((track_label(track),) if track is not None else ()),
                blocked_by=design_child_id,
            )
        )
    return design_child_id, placeholder_id


def finalize_spec_instantiation(
    backend: Backend, container_id: str, title: str, track: str | None = None
) -> tuple[str, str]:
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
    design_child_id, placeholder_id = instantiate_spec_shape(backend, container_id, title, track)
    backend.label_mutate("add", container_id, [PLANNED_LABEL])
    backend.label_mutate("remove", container_id, [CREATING_SPEC_LABEL])
    return design_child_id, placeholder_id


def _validate_usage(args: Namespace, noun: Noun) -> None:
    if args.type is not None:
        raise WorkError(
            ErrorCode.USAGE,
            f"create {noun}: --type is set by the noun; omit it",
        )
    for user_label in args.label:
        # Additive user labels are welcome (single-call atomicity, V2 audit
        # row mint (c)); lifecycle/track state is not label-forgeable.
        reserved = user_label in _RESERVED_LABEL_EXACT or user_label.startswith(
            _RESERVED_LABEL_PREFIXES
        )
        if reserved:
            raise WorkError(
                ErrorCode.USAGE,
                f"create {noun}: label {user_label!r} is reserved (lifecycle/track "
                f"state is set by the noun and --track, never --label)",
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


def _resolve_track(
    backend: Backend, args: Namespace, parent: str | None
) -> tuple[str | None, list[str]]:
    """Track resolution for `work create <noun>`: derive, else enforce (track spec §4).

    Explicit --track wins; else a tracked parent's derived track is inherited
    (a track-less parent falls through); else enforcement decides. A repo with
    no resolvable config behaves exactly as before the track layer existed
    (criterion 17); an INVALID config skips the gate with a warning instead of
    breaking `create` (spec §3: a broken config fails only the track layer).
    """
    try:
        config = args.load_config()
    except WorkError as not_configured:
        if not_configured.code is not ErrorCode.NOT_CONFIGURED or args.track is not None:
            raise
        if not_configured.detail.get("reason") == "invalid":
            return None, [f"track gate skipped: {not_configured.message}"]
        return None, []
    if args.track is not None:
        require_known_track(args.track, config)
        return args.track, []
    warnings: list[str] = []
    if parent is not None:
        parent_track = derive_track(backend.get(parent).labels)
        if parent_track is not None:
            if parent_track in config.names:
                return parent_track, []
            # An out-of-vocabulary parent track (raw label writes) is never
            # inherited: it would be invisible to list --track and
            # unrepairable through track set. Fall through to enforcement.
            warnings.append(
                f"parent {parent} carries unknown track {parent_track!r}; not "
                "inherited -- repair the parent via work track set"
            )
    if config.enforcement == "required":
        raise WorkError(
            ErrorCode.TRACK_REQUIRED,
            "track is required: pass --track NAME or create under a parent with a "
            f"configured track (configured tracks: {', '.join(config.names)})",
        )
    warnings.append("created untracked: no --track and no tracked parent (advisory mode)")
    return None, warnings


def _with_warnings(data: dict[str, JsonValue], warnings: list[str]) -> JsonValue:
    if warnings:
        data["warnings"] = list(warnings)
    return data


def _create_spec_container(
    backend: Backend,
    args: Namespace,
    template: NounTemplate,
    parent: str | None,
    track: str | None,
) -> dict[str, JsonValue]:
    container_id = backend.create(
        CreateFields(
            title=args.title,
            description=args.description,
            type=template.bd_type,
            priority=args.priority,
            parent=parent,
            labels=(template.shape_label, CREATING_SPEC_LABEL)
            + ((track_label(track),) if track is not None else ())
            + tuple(args.label),
            acceptance=args.acceptance,
        )
    )
    if args.orphan:
        _append_orphan_marker(backend, container_id)
    # The completion tail (mint children, stamp `planned`, drop `creating-spec`
    # strictly last -- L16) is shared with `promote` and the `reconcile` sweep.
    # A crash anywhere before the handle comes off leaves a `shape-spec`
    # container that is NOT `planned` and still carries `creating-spec`: it
    # self-reports into the Planning queue (visible) AND is finished by the sweep
    # through the handle (auto-recoverable). Both nets fire.
    design_child_id, placeholder_id = finalize_spec_instantiation(
        backend, container_id, args.title, track
    )
    return {"id": container_id, "design_child": design_child_id, "placeholder": placeholder_id}


def create_noun(backend: Backend, args: Namespace) -> JsonValue:
    """`work create <noun> --title T (--parent ID | --orphan) [...]` (plan L9/L13/L14/L16)."""
    noun = Noun(args.noun)
    template = NOUN_TEMPLATES[noun]

    _validate_usage(args, noun)
    _check_duplicate_title(backend, args.title)

    parent = None if args.orphan else args.parent
    track, warnings = _resolve_track(backend, args, parent)

    if noun is Noun.SPEC:
        return _with_warnings(
            _create_spec_container(backend, args, template, parent, track), warnings
        )

    labels = [template.shape_label]
    if template.expects_evidence and (args.spec is not None or args.trivial):
        labels.append(SPEC_READY_LABEL)
    if track is not None:
        labels.append(track_label(track))
    labels.extend(args.label)

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
        _append_orphan_marker(backend, new_id)
    return _with_warnings({"id": new_id}, warnings)


def _append_orphan_marker(backend: Backend, item_id: str) -> None:
    """Append the orphan marker, surfacing `item_id` on failure (discover spec §3.2).

    The mint (`backend.create`) already returned by the time this runs, so a
    failure here leaves a created-but-unmarked bead. `detail.created_id` lets
    the caller replay only this step against the already-minted id, rather
    than discarding it behind a bare error.
    """
    try:
        backend.append_note(item_id, ORPHAN_MARKER)
    except WorkError as append_error:
        raise WorkError(
            append_error.code,
            append_error.message,
            {**append_error.detail, "created_id": item_id},
        ) from append_error
