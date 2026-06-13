"""Tests for the §8.6 memory-channel + containment audit (pure).

``audit_memory`` validates the §8.5 memory channel. The containment check is the
security-critical rule: every ``memory_writes`` path must resolve INSIDE
``memory_dir`` by a PURE LEXICAL check (no filesystem access, no symlink
following), and a breach is a HARD ``Severity.BLOCK`` violation that flips the
cluster — it is never soft-failed.
"""

from __future__ import annotations

from prgroom.agent.contracts import FixOutput, MemoryEntry
from prgroom.agent.memory_audit import audit_memory
from prgroom.errors import ErrorCode
from prgroom.escalation import Severity

_MEM = "/run/scratch/mem"


def _out(
    *, memory_writes: list[str] | None = None, memory: list[MemoryEntry] | None = None
) -> FixOutput:
    return FixOutput(items=[], memory_writes=memory_writes or [], memory=memory or [])


# ───────────────────────── containment (HARD, security) ─────────────────────────


def test_path_inside_memory_dir_is_clean() -> None:
    out = _out(memory_writes=[f"{_MEM}/note.md", f"{_MEM}/sub/deep.md"])
    res = audit_memory(
        out,
        memory_dir=_MEM,
        written_paths={f"{_MEM}/note.md", f"{_MEM}/sub/deep.md"},
        known_thread_ids=set(),
    )
    assert res.violations == []


def test_absolute_path_outside_memory_dir_is_block_violation() -> None:
    out = _out(memory_writes=["/etc/passwd"])
    res = audit_memory(out, memory_dir=_MEM, written_paths={"/etc/passwd"}, known_thread_ids=set())
    assert len(res.violations) == 1
    assert res.violations[0].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED
    assert res.violations[0].severity is Severity.BLOCK
    assert "/etc/passwd" in res.violations[0].detail


def test_dotdot_traversal_escaping_memory_dir_is_block_violation() -> None:
    out = _out(memory_writes=[f"{_MEM}/../../etc/shadow"])
    res = audit_memory(
        out, memory_dir=_MEM, written_paths={f"{_MEM}/../../etc/shadow"}, known_thread_ids=set()
    )
    assert len(res.violations) == 1
    assert res.violations[0].severity is Severity.BLOCK


def test_dotdot_that_stays_inside_memory_dir_is_clean() -> None:
    # a/../b normalizes to b, still inside — lexical normpath, not a breach.
    p = f"{_MEM}/a/../b.md"
    out = _out(memory_writes=[p])
    res = audit_memory(out, memory_dir=_MEM, written_paths={p}, known_thread_ids=set())
    assert res.violations == []


def test_memory_dir_itself_is_contained() -> None:
    # A write path equal to memory_dir (after normalization) is inside it, not an
    # escape — the boundary case of the containment check.
    out = _out(memory_writes=[f"{_MEM}/"])  # trailing slash normalizes to _MEM
    res = audit_memory(out, memory_dir=_MEM, written_paths={f"{_MEM}/"}, known_thread_ids=set())
    assert res.violations == []


def test_sibling_prefix_path_is_a_block_violation() -> None:
    # /run/scratch/mem-evil shares the string prefix but is NOT inside the dir.
    out = _out(memory_writes=["/run/scratch/mem-evil/x.md"])
    res = audit_memory(
        out, memory_dir=_MEM, written_paths={"/run/scratch/mem-evil/x.md"}, known_thread_ids=set()
    )
    assert len(res.violations) == 1
    assert res.violations[0].severity is Severity.BLOCK


def test_root_memory_dir_contains_every_absolute_path() -> None:
    # memory_dir == "/" is pathological but must not produce false BLOCKs: normpath
    # "/" already ends in os.sep, so a naive `norm_dir + os.sep` ("//") rejects every
    # real path. Root contains everything absolute.
    out = _out(memory_writes=["/etc/passwd", "/"])
    res = audit_memory(
        out, memory_dir="/", written_paths={"/etc/passwd", "/"}, known_thread_ids=set()
    )
    assert res.violations == []


# ───────────────────────── classification enum ─────────────────────────


def test_unknown_classification_is_warn_audit_failure() -> None:
    out = _out(memory=[MemoryEntry(classification="BOGUS", content="x")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert len(res.violations) == 1
    assert res.violations[0].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED
    assert res.violations[0].severity is Severity.WARN


def test_empty_classification_is_audit_failure() -> None:
    out = _out(memory=[MemoryEntry(classification="", content="x")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert any(v.severity is Severity.WARN for v in res.violations)


# ───────────────────────── exactly one of content|path ─────────────────────────


def test_neither_content_nor_path_is_audit_failure() -> None:
    out = _out(memory=[MemoryEntry(classification="CONTEXTUAL")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert any(v.code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED for v in res.violations)


def test_both_content_and_path_is_audit_failure() -> None:
    out = _out(memory=[MemoryEntry(classification="CONTEXTUAL", content="x", path="p")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert any(v.code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED for v in res.violations)


# ───────────────────────── CONTEXTUAL routability ─────────────────────────


def test_contextual_with_known_target_hint_is_clean() -> None:
    out = _out(memory=[MemoryEntry(classification="CONTEXTUAL", content="x", target_hint="PRT_1")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids={"PRT_1"})
    assert res.violations == []


def test_contextual_with_unknown_target_hint_is_audit_failure() -> None:
    out = _out(
        memory=[MemoryEntry(classification="CONTEXTUAL", content="x", target_hint="PRT_GHOST")]
    )
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids={"PRT_1"})
    assert any(v.code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED for v in res.violations)


def test_threadless_contextual_is_clean() -> None:
    # A CONTEXTUAL entry with no target_hint routes to the ## Decisions block.
    out = _out(memory=[MemoryEntry(classification="CONTEXTUAL", content="pr-wide decision")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert res.violations == []


# ───────────────────────── non-CONTEXTUAL deferred ─────────────────────────


def test_non_contextual_classes_are_deferred_not_errors() -> None:
    entries = [
        MemoryEntry(classification="UNIVERSAL", content="u"),
        MemoryEntry(classification="PROJECT", content="p"),
        MemoryEntry(classification="PLANNED", content="pl"),
        MemoryEntry(classification="HISTORICAL", content="h"),
    ]
    out = _out(memory=entries)
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert res.violations == []
    assert res.deferred == entries


def test_contextual_is_not_deferred() -> None:
    out = _out(memory=[MemoryEntry(classification="CONTEXTUAL", content="x")])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert res.deferred == []


# ───────────────────────── declared-but-unwritten (soft) ─────────────────────────


def test_declared_but_unwritten_path_is_a_soft_warning_not_a_violation() -> None:
    out = _out(memory_writes=[f"{_MEM}/declared.md"])
    res = audit_memory(out, memory_dir=_MEM, written_paths=set(), known_thread_ids=set())
    assert res.violations == []  # soft — never a cluster failure
    assert res.unwritten == [f"{_MEM}/declared.md"]


def test_written_declared_path_is_not_in_unwritten() -> None:
    p = f"{_MEM}/declared.md"
    out = _out(memory_writes=[p])
    res = audit_memory(out, memory_dir=_MEM, written_paths={p}, known_thread_ids=set())
    assert res.unwritten == []
