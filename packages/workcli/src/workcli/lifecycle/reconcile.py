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
from workcli.envelope import JsonValue, WorkError
from workcli.lifecycle import (
    DELIVERED_MARKER,
    MANIFEST_MARKER,
    SPEC_MARKER,
    has_marker,
    manifest_snapshot,
)
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
    routine mints only the missing children, closes the design child, and removes
    the handle last. A placeholder with no snapshot has no recorded target, so it
    surfaces as an attention finding without auto-repair. A corrupt snapshot is
    one poisoned bead, reported as its own finding rather than aborting recovery
    of every healthy placeholder (L10) -- the typed drift `manifest_snapshot`
    raises is caught per-item here."""
    findings: list[JsonValue] = []
    for candidate in backend.query(QueryFilters(label=IMPL_PLACEHOLDER_LABEL)):
        placeholder = backend.get(candidate.id)
        try:
            snapshot = manifest_snapshot(placeholder.notes)
        except WorkError:
            findings.append(_finding(placeholder.id, "corrupt_snapshot", repaired=False))
            continue
        if snapshot is None:
            findings.append(_finding(placeholder.id, "needs_spec", repaired=False))
            continue
        if not dry_run:
            reconcile_placeholder(backend, placeholder.id, snapshot)
        findings.append(_finding(placeholder.id, "unreconciled_placeholder", repaired=not dry_run))
    return findings


def _placeholder_reconciled(backend: Backend, design: Item) -> bool:
    """True iff this design child's own placeholder has completed its delivery.

    The placeholder is the item `instantiate_spec_shape` minted `blocks`-linked
    behind the design child (spec §6). Identify it by that structural edge *plus*
    a placeholder note marker (`[work] manifest:`, or legacy `[work] spec:`) -- a
    design may carry other `blocks`-dependents for unrelated reasons, and "any
    dependent lacks impl-placeholder" would wrongly close the design on one of
    those. Its delivery is done once that placeholder no longer carries the
    `impl-placeholder` handle. No marker-bearing blocks-dependent means nothing
    proves the delivery finished, so the design's close is not this sweep's to
    make."""
    for edge in backend.dep_list(design.id).dependents:
        if edge.type != "blocks":
            continue
        placeholder = backend.get(edge.id)
        if not has_marker(placeholder.notes, MANIFEST_MARKER) and not has_marker(
            placeholder.notes, SPEC_MARKER
        ):
            continue
        return IMPL_PLACEHOLDER_LABEL not in placeholder.labels
    return False


def _sweep_orphaned_designs(backend: Backend, *, dry_run: bool) -> list[JsonValue]:
    """Enumerate `shape-design` children; close any still open whose own
    (`blocks`-linked) placeholder is already reconciled. Finishes a delivery
    interrupted between the placeholder's reconciliation and the design child's
    close -- and recovers an old-code delivery that closed in that order. When
    the pending-placeholder sweep above just healed a tree, the design child is
    already closed here, so this never double-reports."""
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
