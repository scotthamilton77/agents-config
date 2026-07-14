"""Integration tests for LegacyExportStore (bead abn9.8.13.1).

The wrapping Store persists inner state (primary, must not be weakened) and THEN
best-effort emits merge-guard's legacy pr-inventory files to an injected export
dir. A failing export must never propagate from ``write`` nor lose inner state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.legacy_export import LegacyExportStore
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)

_T = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
_REF = PRRef("octo", "demo", 7)


def _state() -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=PRPhase.QUIESCED,
        pr_review_retries_used=0,
        last_polled_at=_T,
        last_activity_at=_T,
        quiescence=QuiescenceState(),
        last_poll_sha="headsha",
        items=[
            ReviewItem(
                kind=ItemKind.REVIEW_SUMMARY,
                identity=Identity(gh_id="555"),
                author="copilot",
                body_excerpt="...",
                seen_at=_T,
                disposition=Disposition(
                    kind=DispositionKind.SKIPPED, decided_at=_T, decided_by="fix"
                ),
                own_reply_id=42,
            )
        ],
    )


def test_write_persists_inner_and_emits_legacy(tmp_path: Path) -> None:
    inner = InMemoryStore()
    store = LegacyExportStore(inner, export_dir=tmp_path)

    store.write(_REF, _state())

    # Inner state persisted and readable back through the wrapper.
    assert store.read(_REF).phase == PRPhase.QUIESCED
    # Legacy files emitted to the injected dir.
    assert (tmp_path / "octo-demo-7-headsha.json").is_file()
    assert (tmp_path / "octo-demo-7-headsha.json.replyids").is_file()


def test_export_failure_does_not_propagate_and_inner_persists(tmp_path: Path) -> None:
    inner = InMemoryStore()
    # Point the export dir at a path whose parent is a FILE, so mkdir raises.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    store = LegacyExportStore(inner, export_dir=blocker / "sub")

    # Best-effort: the export blows up internally but write() returns normally.
    store.write(_REF, _state())

    # Primary persist survived the export failure.
    assert store.read(_REF).phase == PRPhase.QUIESCED


def test_delegates_lock_list_and_delete(tmp_path: Path) -> None:
    inner = InMemoryStore()
    store = LegacyExportStore(inner, export_dir=tmp_path)
    store.write(_REF, _state())

    assert store.list_refs() == [_REF]
    with store.lock(_REF):
        pass
    store.delete(_REF)
    assert store.list_refs() == []
