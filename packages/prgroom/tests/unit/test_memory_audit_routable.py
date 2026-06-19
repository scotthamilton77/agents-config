"""§8.3 routability: valid CONTEXTUAL entries surface in ``MemoryAuditResult.routable``.

A CONTEXTUAL entry that clears every gate (valid class, exactly-one-of
content|path, known/absent ``target_hint``) is the set the lifecycle (``_reply``)
will route. Invalid entries still land in ``violations``; non-CONTEXTUAL still in
``deferred``.
"""

from __future__ import annotations

from prgroom.agent.contracts import FixOutput, MemoryEntry
from prgroom.agent.memory_audit import audit_memory


def _out(entries: list[MemoryEntry]) -> FixOutput:
    return FixOutput(items=[], memory_writes=[], memory=entries)


def test_valid_contextual_content_is_routable() -> None:
    e = MemoryEntry(classification="CONTEXTUAL", content="decided X")
    res = audit_memory(_out([e]), memory_dir="/m", written_paths=set(), known_thread_ids=set())
    assert res.routable == [e]
    assert res.violations == []
    assert res.deferred == []


def test_valid_contextual_thread_hint_is_routable() -> None:
    e = MemoryEntry(classification="CONTEXTUAL", content="x", target_hint="PRRT_a")
    res = audit_memory(_out([e]), memory_dir="/m", written_paths=set(), known_thread_ids={"PRRT_a"})
    assert res.routable == [e]


def test_unknown_target_hint_not_routable_is_violation() -> None:
    e = MemoryEntry(classification="CONTEXTUAL", content="x", target_hint="PRRT_unknown")
    res = audit_memory(_out([e]), memory_dir="/m", written_paths=set(), known_thread_ids=set())
    assert res.routable == []
    assert len(res.violations) == 1


def test_non_contextual_is_deferred_not_routable() -> None:
    e = MemoryEntry(classification="PROJECT", content="x")
    res = audit_memory(_out([e]), memory_dir="/m", written_paths=set(), known_thread_ids=set())
    assert res.routable == []
    assert res.deferred == [e]


def test_both_content_and_path_not_routable() -> None:
    e = MemoryEntry(classification="CONTEXTUAL", content="x", path="p")
    res = audit_memory(_out([e]), memory_dir="/m", written_paths=set(), known_thread_ids=set())
    assert res.routable == []
    assert len(res.violations) == 1
