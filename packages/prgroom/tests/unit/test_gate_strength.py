"""GateStrength enum + lenient parse (fix-verify spec §6.1)."""

from __future__ import annotations

import pytest

from prgroom.prsession.enums import GateStrength


def test_values_are_the_serialization_contract() -> None:
    assert GateStrength.FULL.value == "full"
    assert GateStrength.LITE.value == "lite"


@pytest.mark.parametrize(
    ("raw", "want"), [("full", GateStrength.FULL), ("lite", GateStrength.LITE)]
)
def test_parse_accepts_valid_values(raw: str, want: GateStrength) -> None:
    assert GateStrength.parse(raw) is want


@pytest.mark.parametrize("raw", ["", "banana", "FULL", " full"])
def test_parse_returns_none_for_invalid(raw: str) -> None:
    assert GateStrength.parse(raw) is None


@pytest.mark.parametrize("raw", [None, 5, 5.0, True, ["full"], {"x": 1}])
def test_parse_returns_none_for_non_str(raw: object) -> None:
    # The leniency is EXPLICIT, not incidental: a provider emitting JSON null (Python
    # None) or any other non-str for recommended_gate must yield None, not raise —
    # so a malformed gate lands as a CONTRACT_FIX_AUDIT_FAILED violation downstream.
    assert GateStrength.parse(raw) is None
