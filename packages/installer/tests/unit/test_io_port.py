"""Unit tests for installer.core.io_port.

Each test pins a design decision recorded in the A.3 design doc
(docs/specs/2026-05-19-w1qls.1.3-io-port-design.md §5). Tests that would
only verify Python language semantics or third-party-library behaviour
are deliberately absent — see §5.1 of the design doc.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from installer.core.io_port import (
    IOPort,
    PerItemResult,
    ScriptedIO,
    TerminalIO,
)

# ───────────────────────── Protocol conformance ─────────────────────────


def test_terminal_io_satisfies_ioport_protocol() -> None:
    """Pins: TerminalIO structurally implements every IOPort method."""
    assert isinstance(TerminalIO(), IOPort)


def test_scripted_io_satisfies_ioport_protocol() -> None:
    """Pins: the test fake stays in sync with the protocol surface."""
    assert isinstance(ScriptedIO(), IOPort)


# ───────────────────────── PerItemResult ─────────────────────────


def test_per_item_result_equality_and_frozen() -> None:
    a = PerItemResult(decisions={"x": True}, quit=False)
    b = PerItemResult(decisions={"x": True}, quit=False)
    assert a == b
    with pytest.raises(FrozenInstanceError):
        a.quit = True


def test_per_item_result_quit_flag_breaks_equality() -> None:
    """Pins: quit is part of equality, not a hidden field."""
    a = PerItemResult(decisions={"a": True}, quit=False)
    b = PerItemResult(decisions={"a": True}, quit=True)
    assert a != b
