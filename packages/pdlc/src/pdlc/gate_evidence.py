"""Gate-evidence schema — the YAML a worker emits, read back at REAP.

Structural fields mirror the orchestrator core design's "Gate-evidence schema"
table. Reap reads the file, validates the schema, and — in the real system —
*independently re-runs* the gate command rather than trusting the worker's
claimed `verdict`. For the tracer that independent re-run is stubbed: a
schema-valid file with ``verdict == "pass"`` is treated as a gate pass. The
re-verification seam lands with the real worker subprocess in a later bead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

import yaml

VALID_VERDICTS: Final = frozenset({"pass", "fail", "error"})


class GateEvidenceError(ValueError):
    """Raised when a gate-evidence document is missing or schema-invalid."""


@dataclass(frozen=True, slots=True)
class GateEvidence:
    """One gate's evidence, as written by a worker and validated at reap."""

    gate_id: str
    gate_version: str
    objective_id: str
    session_id: str
    attempt_number: int
    started_ts: int
    ended_ts: int
    verdict: str
    evidence_artifacts: list[str] = field(default_factory=list)
    failure_class: str | None = None


def write_evidence(path: Path, evidence: GateEvidence) -> None:
    """Serialise gate evidence to YAML at `path`, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(evidence), sort_keys=True), encoding="utf-8")


def read_and_validate(path: Path) -> GateEvidence:
    """Read and schema-validate a gate-evidence document.

    Raises `GateEvidenceError` if the file is absent, unparseable, or violates
    the schema (missing required field, unknown field, or invalid verdict).
    """
    # Diagnostic messages are formatted at the raise site (path + cause); the
    # single error class is the right granularity for a structural validator.
    if not path.exists():
        raise GateEvidenceError(f"gate-evidence file not found: {path}")  # noqa: TRY003
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise GateEvidenceError(f"gate-evidence is not a mapping: {path}")  # noqa: TRY003
    try:
        evidence = GateEvidence(**raw)
    except TypeError as exc:  # missing/unexpected fields
        raise GateEvidenceError(f"gate-evidence schema mismatch in {path}: {exc}") from exc  # noqa: TRY003
    if evidence.verdict not in VALID_VERDICTS:
        raise GateEvidenceError(f"invalid verdict {evidence.verdict!r} in {path}")  # noqa: TRY003
    return evidence
