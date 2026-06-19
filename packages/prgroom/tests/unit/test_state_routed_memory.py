from datetime import UTC, datetime

from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import PRGroomingState, RoutedMemory, bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


def _ref() -> PRRef:
    return PRRef(owner="o", repo="r", number=1)


def test_routed_memory_roundtrip_thread_form() -> None:
    rm = RoutedMemory(
        content="decided X",
        round=2,
        source_item="c1#0",
        decided_by="claude -p opus[1m]",
        target_hint="PRRT_abc",
    )
    assert RoutedMemory.from_dict(rm.to_dict()) == rm


def test_routed_memory_omits_none_target_hint() -> None:
    rm = RoutedMemory(content="x", round=1, source_item="c1#0", decided_by="a")
    assert "target_hint" not in rm.to_dict()
    assert RoutedMemory.from_dict(rm.to_dict()).target_hint is None


def test_state_new_fields_default_empty_and_omit() -> None:
    state = bootstrap_state(_ref(), now=_NOW)
    assert state.pending_memory == []
    assert state.last_rereviewed_sha == ""
    assert state.last_review_invalidated_sha == ""
    d = state.to_dict()
    assert "pending_memory" not in d
    assert "last_rereviewed_sha" not in d
    assert "last_review_invalidated_sha" not in d


def test_state_new_fields_roundtrip_when_set() -> None:
    state = bootstrap_state(_ref(), now=_NOW)
    state.pending_memory = [RoutedMemory(content="m", round=1, source_item="c1#0", decided_by="a")]
    state.last_rereviewed_sha = "sha-rr"
    state.last_review_invalidated_sha = "sha-inv"
    back = PRGroomingState.from_dict(state.to_dict())
    assert back.pending_memory == state.pending_memory
    assert back.last_rereviewed_sha == "sha-rr"
    assert back.last_review_invalidated_sha == "sha-inv"


def test_old_state_file_loads_with_empty_defaults() -> None:
    state = bootstrap_state(_ref(), now=_NOW)
    raw = state.to_dict()  # no new keys present
    back = PRGroomingState.from_dict(raw)
    assert back.pending_memory == []
    assert back.last_rereviewed_sha == ""
    assert back.last_review_invalidated_sha == ""
