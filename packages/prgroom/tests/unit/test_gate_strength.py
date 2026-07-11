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
