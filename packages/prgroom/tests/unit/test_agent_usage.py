"""Token-usage JSONL emitter (§5 token-usage logging).

MVP baseline-capture only: one JSON line per agent invocation appended to
``$XDG_STATE_HOME/prgroom/usage.jsonl``. No aggregation. The tests pin the §5
record schema, the XDG path resolution, the append (not truncate) semantics, and
the "absent usage line is a no-op, not an error" rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prgroom.agent.usage import UsageRecord, append_usage
from prgroom.prsession.pr_ref import PRRef


def _record() -> UsageRecord:
    return UsageRecord(
        ts="2026-06-10T12:00:00+00:00",
        pr=PRRef(owner="octo", repo="demo", number=7),
        contract="cluster",
        provider="ollama",
        model="gemma4",
        input_tokens=1200,
        output_tokens=80,
        duration_ms=1450,
        outcome="success",
    )


def test_append_writes_schema_line_to_xdg_state_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    append_usage(_record())

    usage_file = tmp_path / "prgroom" / "usage.jsonl"
    lines = usage_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "ts": "2026-06-10T12:00:00+00:00",
        "pr": "octo/demo#7",
        "contract": "cluster",
        "provider": "ollama",
        "model": "gemma4",
        "input_tokens": 1200,
        "output_tokens": 80,
        "duration_ms": 1450,
        "outcome": "success",
    }


def test_append_is_additive_not_truncating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    append_usage(_record())
    append_usage(_record())

    usage_file = tmp_path / "prgroom" / "usage.jsonl"
    assert len(usage_file.read_text(encoding="utf-8").splitlines()) == 2


def test_append_creates_parent_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "deep" / "nested"))
    append_usage(_record())

    assert (tmp_path / "deep" / "nested" / "prgroom" / "usage.jsonl").is_file()


def test_none_token_counts_serialize_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No usage-line parser exists yet, so the dispatcher emits records with unknown
    # token counts — those must serialize as JSON null, not crash or be dropped.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    record = UsageRecord(
        ts="2026-06-12T00:00:00+00:00",
        pr=PRRef(owner="octo", repo="demo", number=7),
        contract="cluster",
        provider="ollama",
        model="gemma4",
        input_tokens=None,
        output_tokens=None,
        duration_ms=10,
        outcome="timeout",
    )
    append_usage(record)

    usage_file = tmp_path / "prgroom" / "usage.jsonl"
    line = json.loads(usage_file.read_text(encoding="utf-8").splitlines()[0])
    assert line["input_tokens"] is None
    assert line["output_tokens"] is None
    assert line["outcome"] == "timeout"


def test_absent_usage_is_a_noop_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # §5: "logs per-contract token usage WHEN the agent CLI emits a usage line".
    # A None record (no usage parsed from the agent output) writes nothing and
    # does not raise — the file must not even be created.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    append_usage(None)

    assert not (tmp_path / "prgroom" / "usage.jsonl").exists()
