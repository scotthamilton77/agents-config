"""Tests for the EscalationSink abstraction (§5).

The CLI routes every escalation through a Sink so it works with or without
beads. Two adapters ship in the foundation: stderr (default) and file (append a
JSON line per escalation, for external watchers / cron). These pin the
*observable output* of each adapter — the stderr line content and the file's
JSONL contract — not that ``emit`` was called.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from prgroom.escalation import Escalation, FileSink, Severity, StderrSink
from prgroom.prsession.pr_ref import PRRef

_REF = PRRef(owner="octo", repo="demo", number=7)


def test_stderr_sink_writes_pr_and_reason_to_its_stream() -> None:
    buf = io.StringIO()
    StderrSink(stream=buf).emit(
        Escalation(pr=_REF, reason="3 rounds without quiescence", severity=Severity.BLOCK)
    )
    written = buf.getvalue()
    assert "octo/demo#7" in written
    assert "3 rounds without quiescence" in written
    assert "block" in written


def test_file_sink_appends_one_json_line_per_escalation(tmp_path: Path) -> None:
    target = tmp_path / "escalations.jsonl"
    sink = FileSink(path=target)
    sink.emit(Escalation(pr=_REF, reason="first", severity=Severity.WARN))
    sink.emit(Escalation(pr=_REF, reason="second", severity=Severity.INFO))

    lines = target.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["pr"] == "octo/demo#7"
    assert first["reason"] == "first"
    assert first["severity"] == "warn"
    assert json.loads(lines[1])["reason"] == "second"


def test_file_sink_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "escalations.jsonl"
    FileSink(path=target).emit(Escalation(pr=_REF, reason="x", severity=Severity.INFO))
    assert target.is_file()


def test_severity_values_are_the_documented_wire_strings() -> None:
    # Severity is part of the file-sink JSONL contract; pin the wire strings.
    assert [s.value for s in Severity] == ["info", "warn", "block"]


def test_file_sink_includes_triggering_item_gh_id_when_present(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from prgroom.prsession.enums import ItemKind
    from prgroom.prsession.state import Identity, ReviewItem

    item = ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="C_42", thread_id="PRT_42"),
        author="copilot",
        body_excerpt="x",
        seen_at=datetime(2026, 6, 9, tzinfo=UTC),
    )
    target = tmp_path / "e.jsonl"
    FileSink(path=target).emit(Escalation(pr=_REF, reason="r", severity=Severity.BLOCK, item=item))
    assert json.loads(target.read_text())["item_gh_id"] == "C_42"
