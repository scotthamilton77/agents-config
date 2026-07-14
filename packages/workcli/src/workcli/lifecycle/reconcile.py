"""`reconcile` -- handle-driven recovery sweep (plan L10).

Candidate sets are enumerated **only** through removable completion handles
(labels), never inferred from external state such as a design child's status or
a spec file's contents. Because `query()`/`list`-sourced Items always have
`children == []` and no deps (bd `list` has no `dependents` key -- see
`adapters/bd/parse.py`), every candidate is re-fetched via `get()` before its
children/deps/notes are read. Recovery replays toward the in-band
`[work] manifest:` snapshot recorded at first delivery, so the spec file is
never re-read here. `--dry-run` performs zero mutating bd calls; repairs are
idempotent (a second sweep over a healed tree finds nothing).
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import JsonValue
from workcli.lifecycle import DELIVERED_MARKER, has_marker, manifest_snapshot
from workcli.lifecycle.deliver import reconcile_placeholder
from workcli.lifecycle.nouns import DESIGN_CHILD_LABEL, IMPL_PLACEHOLDER_LABEL
from workcli.model import Item, QueryFilters


def _finding(item_id: str, kind: str, *, repaired: bool) -> dict[str, JsonValue]:
    return {"id": item_id, "kind": kind, "repaired": repaired}


def _sweep_interrupted_delivers(backend: Backend, *, dry_run: bool) -> list[JsonValue]:
    """An `in_progress` leaf carrying `[work] delivered:` but still open -> close
    it. Enumerated via `query(status="in_progress")`, then `get()`-filtered on
    the note marker (query results carry no notes worth trusting for this)."""
    findings: list[JsonValue] = []
    for candidate in backend.query(QueryFilters(status="in_progress")):
        item = backend.get(candidate.id)
        if not has_marker(item.notes, DELIVERED_MARKER):
            continue
        if not dry_run:
            backend.close([item.id])
        findings.append(_finding(item.id, "interrupted_deliver", repaired=not dry_run))
    return findings


def _sweep_pending_placeholders(backend: Backend, *, dry_run: bool) -> list[JsonValue]:
    """Enumerate `impl-placeholder` handles; replay the shared completion toward
    the recorded `[work] manifest:` snapshot **regardless of the design child's
    status** -- the handle, not the design status, is the signal. The shared
    routine mints only the missing children, closes the design child, and
    removes the handle last. A placeholder with no snapshot has no recorded
    target to replay toward, so it surfaces as an attention finding without
    auto-repair rather than a guess from residual state."""
    findings: list[JsonValue] = []
    for candidate in backend.query(QueryFilters(label=IMPL_PLACEHOLDER_LABEL)):
        placeholder = backend.get(candidate.id)
        snapshot = manifest_snapshot(placeholder.notes)
        if snapshot is None:
            findings.append(_finding(placeholder.id, "needs_spec", repaired=False))
            continue
        if not dry_run:
            reconcile_placeholder(backend, placeholder.id, snapshot)
        findings.append(_finding(placeholder.id, "unreconciled_placeholder", repaired=not dry_run))
    return findings


def _placeholder_reconciled(backend: Backend, design: Item) -> bool:
    """True iff the design child's container has a non-design sibling that no
    longer carries `impl-placeholder` -- i.e. the placeholder's delivery already
    completed and only the design child's own close is outstanding. False when
    the design has no parent or no such sibling (nothing proves the delivery
    finished, so its close is not this sweep's to make)."""
    if design.parent is None:
        return False
    container = backend.get(design.parent)
    for child_id in container.children:
        if child_id == design.id:
            continue
        sibling = backend.get(child_id)
        if IMPL_PLACEHOLDER_LABEL not in sibling.labels:
            return True
    return False


def _sweep_orphaned_designs(backend: Backend, *, dry_run: bool) -> list[JsonValue]:
    """Enumerate `shape-design` children; close any still open whose sibling
    placeholder is already reconciled (no `impl-placeholder`). Finishes a
    delivery interrupted between the placeholder's reconciliation and the design
    child's close -- and recovers an old-code delivery that closed in that
    order. When the pending-placeholder sweep above just healed a tree, the
    design child is already closed here, so this never double-reports."""
    findings: list[JsonValue] = []
    for candidate in backend.query(QueryFilters(label=DESIGN_CHILD_LABEL)):
        design = backend.get(candidate.id)
        if design.status == "closed":
            continue
        if not _placeholder_reconciled(backend, design):
            continue
        if not dry_run:
            backend.close([design.id])
        findings.append(_finding(design.id, "orphaned_design", repaired=not dry_run))
    return findings


def reconcile(backend: Backend, args: Namespace) -> JsonValue:
    """`work reconcile [--dry-run]` (plan L10). Reads no external state (no spec
    file); every candidate is found through a completion handle."""
    dry_run = bool(args.dry_run)
    findings = _sweep_interrupted_delivers(backend, dry_run=dry_run)
    findings += _sweep_pending_placeholders(backend, dry_run=dry_run)
    findings += _sweep_orphaned_designs(backend, dry_run=dry_run)
    return {"findings": findings}
