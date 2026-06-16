"""Tests for the run-loop terminal-signal flush hooks (§3.3, §4.7).

Two best-effort hooks fired at the run-loop's two terminal sites:
``escalate_if_needed`` (one Sink event per un-filed ESCALATED/FAILED item + one per
lifecycle gate, deduped by ``escalation_filed`` / ``lifecycle_escalation_filed``) and
``request_human_review_if_needed`` (the §4.7 ``human-review-required`` label add,
deduped by ``human_review_label_added``). Both swallow Sink/label failures so the
lifecycle never blocks; a failed emit leaves the dedup flag unset for the next pass.

The Sink is a recording fake (not a mock) — the dedup behavior is asserted by the
COUNT and content of recorded escalations, and persistence via ``store.read``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prgroom.errors import ErrorCode
from prgroom.escalation import Escalation
from prgroom.lifecycle.escalation import (
    escalate_if_needed,
    request_human_review_if_needed,
    should_request_human_review,
)
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_LABEL = "human-review-required"


class RecordingSink:
    """A Sink that records every emitted Escalation. Structurally satisfies ``Sink``."""

    def __init__(self) -> None:
        self.emitted: list[Escalation] = []

    def emit(self, escalation: Escalation) -> None:
        self.emitted.append(escalation)


class RaisingSink:
    """A Sink whose emit always fails — exercises the best-effort swallow (§3.3)."""

    def __init__(self) -> None:
        self.calls = 0

    def emit(self, _escalation: Escalation) -> None:
        self.calls += 1
        msg = "sink down"
        raise OSError(msg)


class FakeGh:
    """Records ``add_label`` calls; optionally raises to drive the §4.7 swallow path."""

    def __init__(self, *, fail: bool = False) -> None:
        self.added: list[tuple[PRRef, str]] = []
        self._fail = fail

    def add_label(self, ref: PRRef, label: str) -> None:
        self.added.append((ref, label))
        if self._fail:
            msg = "no triage scope"
            raise RuntimeError(msg)


def _disp(kind: DispositionKind, *, filed: bool = False) -> Disposition:
    return Disposition(
        kind=kind, decided_at=_T0, decided_by="claude opus[1m]", escalation_filed=filed
    )


def _item(*, gh_id: str = "1", disposition: Disposition | None = None) -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=f"PRRT_{gh_id}"),
        author="copilot",
        body_excerpt="fix this",
        seen_at=_T0,
        disposition=disposition,
    )


def _state(
    *items: ReviewItem,
    last_error: str | None = None,
    lifecycle_filed: bool = False,
    label_added: bool = False,
    phase: PRPhase = PRPhase.HUMAN_GATED,
) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=phase,
        round=2,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(),
        items=list(items),
        last_error=last_error,
        lifecycle_escalation_filed=lifecycle_filed,
        human_review_label_added=label_added,
    )


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


# ── escalate_if_needed ──────────────────────────────────────────────────────


def test_escalate_emits_one_event_per_unfiled_blocker_item(store: InMemoryStore) -> None:
    sink = RecordingSink()
    state = _state(
        _item(gh_id="1", disposition=_disp(DispositionKind.ESCALATED)),
        _item(gh_id="2", disposition=_disp(DispositionKind.FAILED)),
        _item(gh_id="3", disposition=_disp(DispositionKind.FIXED)),  # not a blocker
    )
    out = escalate_if_needed(state, sink=sink, store=store, ref=_REF)
    # One emit each for the ESCALATED + FAILED items; the FIXED item is silent.
    assert len(sink.emitted) == 2
    assert {e.item.identity.gh_id for e in sink.emitted if e.item} == {"1", "2"}
    # Flags set on the emitted items, persisted to the store.
    assert out.items[0].disposition.escalation_filed is True
    assert out.items[1].disposition.escalation_filed is True
    assert store.read(_REF).items[1].disposition.escalation_filed is True


def test_escalate_dedups_already_filed_items(store: InMemoryStore) -> None:
    sink = RecordingSink()
    state = _state(_item(disposition=_disp(DispositionKind.ESCALATED, filed=True)))
    escalate_if_needed(state, sink=sink, store=store, ref=_REF)
    assert sink.emitted == []  # already filed — no re-emit


def test_escalate_emits_one_lifecycle_event_for_last_error(store: InMemoryStore) -> None:
    sink = RecordingSink()
    state = _state(last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value)
    out = escalate_if_needed(state, sink=sink, store=store, ref=_REF)
    assert len(sink.emitted) == 1
    assert sink.emitted[0].item is None
    assert ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value in sink.emitted[0].reason
    assert out.lifecycle_escalation_filed is True
    assert store.read(_REF).lifecycle_escalation_filed is True


def test_escalate_dedups_filed_lifecycle_gate(store: InMemoryStore) -> None:
    sink = RecordingSink()
    state = _state(last_error="LIFECYCLE_HARD_CAP_EXCEEDED", lifecycle_filed=True)
    escalate_if_needed(state, sink=sink, store=store, ref=_REF)
    assert sink.emitted == []


def test_escalate_swallows_sink_failure_and_leaves_flag_unset(store: InMemoryStore) -> None:
    sink = RaisingSink()
    warnings: list[str] = []
    state = _state(_item(disposition=_disp(DispositionKind.FAILED)), last_error="X")
    # Best-effort: a raising Sink must NOT propagate, and the flags stay unset so the
    # next pass retries. The item + lifecycle gate are both attempted, and each swallow
    # is logged via warn so a dead Sink is observable (not silent).
    out = escalate_if_needed(state, sink=sink, store=store, ref=_REF, warn=warnings.append)
    assert sink.calls == 2  # item + lifecycle both attempted
    assert out.items[0].disposition.escalation_filed is False
    assert out.lifecycle_escalation_filed is False
    assert len(warnings) == 2  # each swallowed failure surfaced


def test_escalate_no_work_does_not_write(store: InMemoryStore) -> None:
    sink = RecordingSink()
    state = _state(_item(disposition=_disp(DispositionKind.FIXED)))
    escalate_if_needed(state, sink=sink, store=store, ref=_REF)
    assert sink.emitted == []
    with pytest.raises(Exception, match="demo"):  # nothing written — read raises NotFound
        store.read(_REF)


# ── should_request_human_review ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (_state(last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value), True),
        (_state(_item(disposition=_disp(DispositionKind.ESCALATED))), True),
        (_state(_item(disposition=_disp(DispositionKind.FAILED))), True),
        (_state(last_error=ErrorCode.RUNTIME_GH_TERMINAL.value), False),  # §4.7 non-trigger
        (_state(_item(disposition=_disp(DispositionKind.FIXED))), False),
        (_state(), False),
    ],
)
def test_should_request_human_review_matrix(state: PRGroomingState, *, expected: bool) -> None:
    assert should_request_human_review(state) is expected


# ── request_human_review_if_needed ──────────────────────────────────────────


def test_request_human_review_adds_label_once(store: InMemoryStore) -> None:
    gh = FakeGh()
    state = _state(last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value)
    out = request_human_review_if_needed(state, gh=gh, store=store, ref=_REF, auto_request=True)
    assert gh.added == [(_REF, _LABEL)]
    assert out.human_review_label_added is True
    assert store.read(_REF).human_review_label_added is True


def test_request_human_review_short_circuits_when_disabled(store: InMemoryStore) -> None:
    gh = FakeGh()
    state = _state(_item(disposition=_disp(DispositionKind.FAILED)))
    request_human_review_if_needed(state, gh=gh, store=store, ref=_REF, auto_request=False)
    assert gh.added == []


def test_request_human_review_short_circuits_when_already_added(store: InMemoryStore) -> None:
    # Operator-removed-label intent: once added this gating event, do not re-add (§4.7).
    gh = FakeGh()
    state = _state(_item(disposition=_disp(DispositionKind.FAILED)), label_added=True)
    request_human_review_if_needed(state, gh=gh, store=store, ref=_REF, auto_request=True)
    assert gh.added == []


def test_request_human_review_no_op_on_non_trigger(store: InMemoryStore) -> None:
    gh = FakeGh()
    state = _state(last_error=ErrorCode.RUNTIME_GH_TERMINAL.value)  # infra, not review-content
    request_human_review_if_needed(state, gh=gh, store=store, ref=_REF, auto_request=True)
    assert gh.added == []


def test_request_human_review_swallows_label_failure(store: InMemoryStore) -> None:
    gh = FakeGh(fail=True)
    warnings: list[str] = []
    state = _state(last_error=ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED.value)
    out = request_human_review_if_needed(
        state, gh=gh, store=store, ref=_REF, auto_request=True, warn=warnings.append
    )
    # Best-effort: failure is logged, the flag stays unset, nothing propagates.
    assert out.human_review_label_added is False
    assert len(warnings) == 1
    assert _LABEL in warnings[0]
