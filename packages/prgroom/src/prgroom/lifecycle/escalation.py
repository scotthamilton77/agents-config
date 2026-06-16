"""Terminal-signal flush hooks for the run-loop (§3.3, §4.7).

The run-loop emits its terminal signals through two parallel best-effort hooks,
fired at exactly two dedup-safe sites (the loop-top terminal-for-CLI check and
immediately before each ``PROPAGATE`` re-raise):

- :func:`escalate_if_needed` — files one :class:`~prgroom.escalation.Sink` event per
  un-filed ESCALATED/FAILED item plus one lifecycle-tier event for a set
  ``last_error``, deduped by the per-item ``escalation_filed`` flag and the lifecycle
  ``lifecycle_escalation_filed`` flag.
- :func:`request_human_review_if_needed` — adds the GitHub ``human-review-required``
  label once per gating event (§4.7), deduped by ``human_review_label_added``, and
  ONLY for review-content gates (cap-trip, ESCALATED/FAILED items) — never for infra
  gates (auth expiry, state corruption, push rejection).

Both are idempotent and best-effort: a dedup flag is set ONLY after a successful
emit, and the state is persisted right after, so a failed emit leaves the flag unset
and the next pass retries — lifecycle progression never blocks on Sink/label
reachability. A crash between emit and write may double-fire on the next invocation,
absorbed by the Sink's own idempotency (``gh.add_label`` is server-idempotent; a
stderr sink accepts one extra log line). This module is git-free and writes state
through the injected :class:`~prgroom.prsession.store.Store`.

This is the **lifecycle** escalation surface; the top-level
:mod:`prgroom.escalation` owns the :class:`~prgroom.escalation.Sink` protocol and its
stderr/file adapters, which this module routes through.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from prgroom.errors import ErrorCode
from prgroom.escalation import Escalation, Severity
from prgroom.lifecycle.quiescence import BLOCKER_DISPOSITIONS
from prgroom.lifecycle.warn import default_warn

if TYPE_CHECKING:
    from collections.abc import Callable

    from prgroom.escalation import Sink
    from prgroom.gh.client import GhClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState
    from prgroom.prsession.store import Store

# §4.7 literal label string — the GitHub-visible "automation gave up here" marker.
HUMAN_REVIEW_LABEL = "human-review-required"


def escalate_if_needed(
    state: PRGroomingState,
    *,
    sink: Sink,
    store: Store,
    ref: PRRef,
    warn: Callable[[str], None] = default_warn,
) -> PRGroomingState:
    """File one Sink event per un-filed blocker item + one per lifecycle gate (§3.3).

    Walks ``state.items`` for ESCALATED/FAILED dispositions whose ``escalation_filed``
    is still ``False``, and fires one lifecycle-tier event when ``last_error`` is set
    and ``lifecycle_escalation_filed`` is still ``False``. Each dedup flag is set only
    after its emit succeeds; a raising Sink is swallowed (best-effort) AND logged via
    ``warn`` so a persistently-failing Sink is observable rather than silent, leaving
    the flag unset for the next pass. Persists once if anything changed. Mutates and
    returns ``state``.
    """
    changed = False
    for item in state.items:
        disp = item.disposition
        if disp is None or disp.kind not in BLOCKER_DISPOSITIONS or disp.escalation_filed:
            continue
        emitted = _emit(
            sink,
            Escalation(
                pr=ref,
                reason=f"item {item.identity.gh_id} dispositioned {disp.kind.value}",
                severity=Severity.BLOCK,
                item=item,
            ),
            warn,
        )
        if emitted:
            item.disposition = dataclasses.replace(disp, escalation_filed=True)
            changed = True

    if state.last_error is not None and not state.lifecycle_escalation_filed:
        emitted = _emit(
            sink,
            Escalation(
                pr=ref, reason=f"lifecycle gate: {state.last_error}", severity=Severity.BLOCK
            ),
            warn,
        )
        if emitted:
            state.lifecycle_escalation_filed = True
            changed = True

    if changed:
        store.write(ref, state)
    return state


def _emit(sink: Sink, escalation: Escalation, warn: Callable[[str], None]) -> bool:
    """Emit ``escalation``; return whether it succeeded, swallowing any Sink error (§3.3).

    A failed emit (stderr write error, bd-adapter blip) returns ``False`` so the caller
    leaves the dedup flag unset and the next pass retries — best-effort, never blocking
    lifecycle progression. The swallowed failure is logged via ``warn`` (symmetric with
    the §4.7 label-add hook) so a persistently-unreachable Sink surfaces in stderr
    instead of failing silently.
    """
    try:
        sink.emit(escalation)
    except Exception as exc:
        warn(f"escalation sink emit failed: {exc}")
        return False
    return True


def should_request_human_review(state: PRGroomingState) -> bool:
    """True iff a review-content gate is active (§4.7): cap-trip or an ESCALATED/FAILED item.

    Deliberately narrower than :func:`escalate_if_needed`'s lifecycle trigger: only the
    hard-cap ``last_error`` counts here. Infra gates (``RUNTIME_TERMINAL_USER``,
    ``STATE_CORRUPT``, ``RUNTIME_PUSH_REJECTED``, …) are §4.7 non-triggers — they are
    operator-infra problems, not review-content problems, so they never add the label.
    """
    if state.last_error == ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value:
        return True
    return any(
        item.disposition is not None and item.disposition.kind in BLOCKER_DISPOSITIONS
        for item in state.items
    )


def request_human_review_if_needed(
    state: PRGroomingState,
    *,
    gh: GhClient,
    store: Store,
    ref: PRRef,
    auto_request: bool,
    warn: Callable[[str], None] = default_warn,
) -> PRGroomingState:
    """Add the ``human-review-required`` label once per gating event (§4.7).

    Short-circuits when auto-request is off, no review-content gate is active, or the
    label was already added this gating event (which preserves an operator's deliberate
    label removal — the flag stays ``True`` until the §3.3 reset-on-success path clears
    it). Best-effort: a failed ``gh.add_label`` is logged via ``warn`` and leaves
    ``human_review_label_added`` unset so the next pass retries; it never tier-tags,
    blocks, or propagates. Mutates and returns ``state``.
    """
    if not auto_request or not should_request_human_review(state) or state.human_review_label_added:
        return state
    try:
        gh.add_label(ref, HUMAN_REVIEW_LABEL)
    except Exception as exc:
        warn(f"failed to add {HUMAN_REVIEW_LABEL} label: {exc}")
        return state
    state.human_review_label_added = True
    store.write(ref, state)
    return state
