"""Contract tests for gate-evidence serialization and the validator's taxonomy.

The validator is the orchestrator's defence against a malformed worker report
at REAP. Its error taxonomy — absent file, non-mapping, schema mismatch,
invalid verdict — is real, decision-bearing behaviour, so each rejection is
pinned here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pdlc.gate_evidence import GateEvidence, GateEvidenceError, read_and_validate, write_evidence

_VALID = GateEvidence(
    gate_id="green-gate",
    gate_version="tracer-v1",
    objective_id="obj-1",
    session_id="session-1",
    attempt_number=1,
    started_ts=1,
    ended_ts=2,
    verdict="pass",
)


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "evidence.yml"
    write_evidence(path, _VALID)
    assert read_and_validate(path) == _VALID


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GateEvidenceError):
        read_and_validate(tmp_path / "absent.yml")


def test_non_mapping_document_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "scalar.yml"
    path.write_text("just a string", encoding="utf-8")
    with pytest.raises(GateEvidenceError):
        read_and_validate(path)


def test_schema_mismatch_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "partial.yml"
    path.write_text(yaml.safe_dump({"gate_id": "green-gate"}), encoding="utf-8")
    with pytest.raises(GateEvidenceError):
        read_and_validate(path)


def test_invalid_verdict_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad-verdict.yml"
    payload = {
        "gate_id": "green-gate",
        "gate_version": "tracer-v1",
        "objective_id": "obj-1",
        "session_id": "session-1",
        "attempt_number": 1,
        "started_ts": 1,
        "ended_ts": 2,
        "verdict": "maybe",
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(GateEvidenceError):
        read_and_validate(path)
