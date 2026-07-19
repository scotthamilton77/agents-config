"""`grind.jsonio.loads`: the strict decoder that refuses non-standard
non-finite JSON constants (`NaN`, `Infinity`, `-Infinity`) at every boundary."""

from __future__ import annotations

import math

import pytest

from grind.jsonio import NonFiniteJsonError, loads


def test_loads_accepts_ordinary_json() -> None:
    assert loads('{"a": 1, "b": [true, null, 2.5], "c": "x"}') == {
        "a": 1,
        "b": [True, None, 2.5],
        "c": "x",
    }


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_loads_rejects_top_level_non_finite_constant(constant: str) -> None:
    with pytest.raises(NonFiniteJsonError):
        loads(constant)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_loads_rejects_nested_non_finite_constant(constant: str) -> None:
    with pytest.raises(NonFiniteJsonError):
        loads('{"mission": {"goal": ' + constant + "}}")


def test_non_finite_json_error_is_a_value_error() -> None:
    # A ValueError subclass so boundary catch sites can group it with the
    # stdlib `json.JSONDecodeError` (itself a ValueError) as malformed input.
    assert issubclass(NonFiniteJsonError, ValueError)


def test_loads_still_produces_finite_floats_for_valid_numbers() -> None:
    value = loads('{"n": 1.5}')
    assert isinstance(value, dict)
    assert math.isfinite(value["n"])  # type: ignore[arg-type]
