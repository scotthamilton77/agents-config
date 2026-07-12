"""`reconcile` -- bd-observable recovery sweep (plan Task 6, test-plan items 7, 11).

Enumerates candidate sets only through queryable handles: `query()`-sourced
Items always have `children == []` and no deps (bd `list` has no
`dependents` key -- see `adapters/bd/parse.py`), so every candidate is
re-fetched via `get()` before its children/deps/notes are read (L10).
`--dry-run` performs zero mutating bd calls; repairs are idempotent (a
second sweep over a healed tree finds nothing).
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable

from workcli.backend import Backend
from workcli.envelope import JsonValue
from workcli.lifecycle import DELIVERED_MARKER, SPEC_MARKER, has_marker
from workcli.lifecycle.deliver import reconcile_placeholder
from workcli.lifecycle.manifest import parse_continuations
from workcli.lifecycle.nouns import DESIGN_CHILD_LABEL, IMPL_PLACEHOLDER_LABEL
from workcli.model import Item, QueryFilters


def _finding(item_id: str, kind: str, *, repaired: bool) -> dict[str, JsonValue]:
    return {"id": item_id, "kind": kind, "repaired": repaired}


def _sweep_interrupted_delivers(backend: Backend, *, dry_run: bool) -> list[JsonValue]:
    """Item 11 case 1: an `in_progress` leaf carrying `[work] delivered:` still
    open -> close it. Enumerated via `query(status="in_progress")`, then
    `get()`-filtered on the note marker (query results carry no notes worth
    trusting for this -- re-fetch full state per candidate, L10)."""
    findings: list[JsonValue] = []
    for candidate in backend.query(QueryFilters(status="in_progress")):
        item = backend.get(candidate.id)
        if not has_marker(item.notes, DELIVERED_MARKER):
            continue
        if not dry_run:
            backend.close([item.id])
        findings.append(_finding(item.id, "interrupted_deliver", repaired=not dry_run))
    return findings


def _spec_path(notes: str) -> str | None:
    for line in notes.splitlines():
        stripped = line.strip()
        if stripped.startswith(SPEC_MARKER):
            return stripped[len(SPEC_MARKER) :].strip()
    return None


def _design_sibling_closed(backend: Backend, placeholder: Item) -> bool:
    """Locate the design-child sibling under the placeholder's container and
    report whether the design phase is done (§L10: `instantiate_spec_shape`
    mints exactly a design child + this placeholder under one container, so
    "the sibling carrying `shape-design`" always resolves to it -- a missing
    sibling, or one not yet closed, means this placeholder is legitimately
    blocked, not a reconcile target)."""
    if placeholder.parent is None:
        return False
    container = backend.get(placeholder.parent)
    for child_id in container.children:
        if child_id == placeholder.id:
            continue
        child = backend.get(child_id)
        if DESIGN_CHILD_LABEL in child.labels:
            return child.status == "closed"
    return False


def _sweep_unreconciled_placeholders(
    backend: Backend, read_file: Callable[[str], str], *, dry_run: bool
) -> list[JsonValue]:
    """Item 7 (interrupted expansion) / item 11 case 2 (unreconciled
    placeholder): enumerated via `query(label=impl-placeholder)`, `get()`-ed,
    then gated on a closed design-child sibling. A present `[work] spec:`
    note re-parses the manifest and reuses `reconcile_placeholder` (mints
    only missing children, idempotent); an absent note is reported without
    mutation -- there is no path to parse a manifest from."""
    findings: list[JsonValue] = []
    for candidate in backend.query(QueryFilters(label=IMPL_PLACEHOLDER_LABEL)):
        placeholder = backend.get(candidate.id)
        if not _design_sibling_closed(backend, placeholder):
            continue

        spec_path = _spec_path(placeholder.notes)
        if spec_path is None:
            findings.append(_finding(placeholder.id, "needs_spec", repaired=False))
            continue

        if not dry_run:
            manifest = parse_continuations(read_file(spec_path))
            reconcile_placeholder(backend, placeholder.id, manifest)
        findings.append(_finding(placeholder.id, "unreconciled_placeholder", repaired=not dry_run))
    return findings


def reconcile(backend: Backend, args: Namespace) -> JsonValue:
    """`work reconcile [--dry-run]` (plan L10)."""
    dry_run = bool(args.dry_run)
    findings = _sweep_interrupted_delivers(backend, dry_run=dry_run)
    findings += _sweep_unreconciled_placeholders(backend, args.read_file, dry_run=dry_run)
    return {"findings": findings}
