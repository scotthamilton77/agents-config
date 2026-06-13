"""§8.6 memory-channel + containment audit (pure).

:func:`audit_memory` validates the §8.5 fix-output memory channel. It is pure:
the caller supplies ``written_paths`` (what counts as "written" is the caller's
decision — see :mod:`prgroom.agent.fix`) and ``known_thread_ids``, so the audit
touches no filesystem and no network.

Rules (§8.6):

* **Containment (HARD, security)** — every ``memory_writes`` path must resolve
  INSIDE ``memory_dir``. The check is **purely lexical** (``os.path.normpath`` +
  prefix test): it never calls ``.resolve()`` / ``os.path.realpath`` (which would
  hit the fs and follow symlinks). An absolute escape, a ``..`` traversal that
  leaves the dir, or a sibling-prefix path (``/x/mem-evil`` vs ``/x/mem``) is a
  ``Severity.BLOCK`` violation that flips the cluster. NEVER soft-failed.
* **Classification enum** — each ``memory[].classification`` must be one of the
  five taxonomy classes; an unknown/empty value is a WARN audit failure.
* **Exactly one of content|path** — neither or both set is an audit failure.
* **CONTEXTUAL routability** — a CONTEXTUAL entry whose ``target_hint`` is set
  must name a thread in ``known_thread_ids``; an unknown hint is an audit failure.
  A thread-less CONTEXTUAL entry is fine (it routes to the ``## Decisions`` block —
  that ROUTING is a later bead).
* **Non-CONTEXTUAL** — accepted, returned in ``deferred``, never an error
  (forward-compat with the repo-wide memory router).
* **Declared-but-unwritten** — a ``memory_writes`` path not in ``written_paths``
  is a SOFT warning (returned in ``unwritten``), never a cluster failure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prgroom.agent.errors import AuditViolation
from prgroom.errors import ErrorCode
from prgroom.escalation import Severity

if TYPE_CHECKING:
    from prgroom.agent.contracts import FixOutput, MemoryEntry

# The project's five-class memory taxonomy (§8.6). Home for the names is here —
# the design forbids a classification enum in enums.py (it is not a serialization
# contract prgroom owns; it is forward-compat surface for the repo-wide router).
_VALID_CLASSES = frozenset({"UNIVERSAL", "PROJECT", "PLANNED", "HISTORICAL", "CONTEXTUAL"})
_CONTEXTUAL = "CONTEXTUAL"


@dataclass(frozen=True, slots=True)
class MemoryAuditResult:
    """The computed result of a memory audit (8.7 returns; 8.15 applies).

    ``violations`` are HARD breaches (containment BLOCK + per-entry WARNs);
    ``deferred`` are accepted non-CONTEXTUAL entries the repo-wide router will
    later home; ``unwritten`` are declared-but-unwritten paths (soft warnings).
    """

    violations: list[AuditViolation] = field(default_factory=list)
    deferred: list[MemoryEntry] = field(default_factory=list)
    unwritten: list[str] = field(default_factory=list)


def _is_contained(path: str, memory_dir: str) -> bool:
    """Pure lexical containment: is ``path`` inside ``memory_dir``? No fs access.

    Normalizes both lexically (collapsing ``.``/``..`` and separators) and tests
    that the normalized path equals the dir or sits under ``dir + os.sep``. The
    ``+ sep`` guard rejects sibling-prefix escapes (``/x/mem-evil`` is not under
    ``/x/mem``). An absolute path under a relative dir (or vice-versa) cannot be
    contained, which the prefix test correctly rejects.
    """
    norm_dir = os.path.normpath(memory_dir)
    norm_path = os.path.normpath(path)
    if norm_path == norm_dir:
        return True
    return norm_path.startswith(norm_dir + os.sep)


def audit_memory(
    out: FixOutput,
    *,
    memory_dir: str,
    written_paths: set[str],
    known_thread_ids: set[str],
) -> MemoryAuditResult:
    """Validate the §8.5 memory channel. Pure; returns a :class:`MemoryAuditResult`."""
    violations: list[AuditViolation] = []
    deferred: list[MemoryEntry] = []

    for write_path in out.memory_writes:
        if not _is_contained(write_path, memory_dir):
            violations.append(
                AuditViolation(
                    code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED,
                    detail=f"memory containment violation: {write_path}",
                    severity=Severity.BLOCK,
                )
            )

    for entry in out.memory:
        _audit_entry(
            entry, known_thread_ids=known_thread_ids, violations=violations, deferred=deferred
        )

    unwritten = [p for p in out.memory_writes if p not in written_paths]
    return MemoryAuditResult(violations=violations, deferred=deferred, unwritten=unwritten)


def _audit_entry(
    entry: MemoryEntry,
    *,
    known_thread_ids: set[str],
    violations: list[AuditViolation],
    deferred: list[MemoryEntry],
) -> None:
    if entry.classification not in _VALID_CLASSES:
        violations.append(
            AuditViolation(
                code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED,
                detail=f"unknown memory classification: {entry.classification!r}",
            )
        )
        return

    has_content = entry.content is not None
    has_path = entry.path is not None
    if has_content == has_path:  # neither or both
        violations.append(
            AuditViolation(
                code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED,
                detail="memory entry must set exactly one of content|path",
            )
        )
        return

    if entry.classification != _CONTEXTUAL:
        deferred.append(entry)
        return

    if entry.target_hint is not None and entry.target_hint not in known_thread_ids:
        violations.append(
            AuditViolation(
                code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED,
                detail=f"CONTEXTUAL memory target_hint names unknown thread {entry.target_hint!r}",
            )
        )
