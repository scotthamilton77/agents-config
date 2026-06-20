"""Unit tests for installer.core.io_port.

Each test pins a design decision recorded in the A.3 design doc
(docs/specs/2026-05-19-w1qls.1.3-io-port-design.md §5). Tests that would
only verify Python language semantics or third-party-library behaviour
are deliberately absent — see §5.1 of the design doc.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from installer.core.io_port import (
    IOPort,
    PerItemResult,
    ScriptedIO,
    ScriptExhaustedError,
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


# ───────────────────────── ScriptedIO — script consumption ─────────────────────────


def test_scripted_confirm_pops_in_order() -> None:
    io = ScriptedIO(confirms=[True, False])
    assert io.confirm("first?") is True
    assert io.confirm("second?") is False


def test_scripted_three_way_pops_in_order() -> None:
    io = ScriptedIO(three_ways=["all", "cancel"])
    assert io.confirm_three_way("how?", choices=("all", "one-by-one", "cancel")) == "all"
    assert io.confirm_three_way("how?", choices=("all", "one-by-one", "cancel")) == "cancel"


def test_scripted_per_item_pops_in_order() -> None:
    a = PerItemResult(decisions={"x": True}, quit=False)
    b = PerItemResult(decisions={"y": False}, quit=True)
    io = ScriptedIO(per_items=[a, b])
    assert io.confirm_per_item("prune?", items=["x"]) == a
    assert io.confirm_per_item("prune?", items=["y"]) == b


def test_scripted_per_method_queues_are_independent() -> None:
    """Pins the per-method-queue design - interleaved prompts pop from
    their own queues without cross-contamination."""
    io = ScriptedIO(
        confirms=[True, False],
        three_ways=["all"],
    )
    assert io.confirm("a?") is True
    assert io.confirm_three_way("b?", choices=("all", "one", "cancel")) == "all"
    assert io.confirm("c?") is False


# ───────────────────────── ScriptedIO — exhaustion ─────────────────────────


def test_scripted_confirm_exhaustion_raises_with_queue_name() -> None:
    io = ScriptedIO()  # empty confirms queue
    with pytest.raises(ScriptExhaustedError) as exc_info:
        io.confirm("Install?")
    msg = str(exc_info.value)
    assert "confirms" in msg
    assert "Install?" in msg


def test_scripted_three_way_exhaustion_raises_with_queue_name() -> None:
    io = ScriptedIO()
    with pytest.raises(ScriptExhaustedError) as exc_info:
        io.confirm_three_way("How?", choices=("a", "b", "c"))
    msg = str(exc_info.value)
    assert "three_ways" in msg
    assert "How?" in msg


def test_scripted_per_item_exhaustion_raises_with_queue_name() -> None:
    io = ScriptedIO()
    with pytest.raises(ScriptExhaustedError) as exc_info:
        io.confirm_per_item("Prune?", items=["a", "b"])
    msg = str(exc_info.value)
    assert "per_items" in msg
    assert "Prune?" in msg


def test_scripted_exhaustion_message_includes_transcript_tail() -> None:
    """Pins the self-diagnosing error contract: the failure message
    includes the recent transcript so a test reader can see what was
    happening before the over-pop."""
    io = ScriptedIO()
    io.info("first")
    io.ok("second")
    io.warn("third")
    with pytest.raises(ScriptExhaustedError) as exc_info:
        io.confirm("over the line?")
    msg = str(exc_info.value)
    # At least one of the prior messages must surface in the tail.
    assert any(prior in msg for prior in ("first", "second", "third"))


# ───────────────────────── ScriptedIO — transcript ─────────────────────────


def test_scripted_transcript_records_output_in_order() -> None:
    io = ScriptedIO()
    io.info("a")
    io.ok("b")
    io.warn("c")
    io.err("d")
    io.header("e")
    assert [e.channel for e in io.transcript] == ["info", "ok", "warn", "err", "header"]
    assert [e.message for e in io.transcript] == ["a", "b", "c", "d", "e"]


def test_scripted_transcript_preserves_verbose_flag() -> None:
    """Pins: ScriptedIO records every output call (no short-circuit on
    verbose=True), with the verbose tag intact for filtered assertions."""
    io = ScriptedIO()
    io.info("loud", verbose=False)
    io.info("quiet", verbose=True)
    assert io.transcript[0].verbose is False
    assert io.transcript[1].verbose is True


def test_scripted_transcript_records_prompts_with_answers() -> None:
    io = ScriptedIO(confirms=[True])
    result = io.confirm("ok?")
    assert result is True
    entry = io.transcript[-1]
    assert entry.channel == "confirm"
    assert entry.message == "ok?"
    assert entry.payload is True


def test_scripted_transcript_records_diff_payload() -> None:
    io = ScriptedIO()
    io.show_diff("a.md", b"old", b"new")
    entry = io.transcript[-1]
    assert entry.channel == "diff"
    assert entry.message == "a.md"
    assert entry.payload == (b"old", b"new")


# ───────────────────────── ScriptedIO — interactivity ─────────────────────────


def test_scripted_is_interactive_defaults_true() -> None:
    assert ScriptedIO().is_interactive() is True


def test_scripted_is_interactive_can_be_disabled() -> None:
    assert ScriptedIO(interactive=False).is_interactive() is False


# ───────────────────────── TerminalIO - smoke against StringIO Console ─────────────────────────


def _capture_console() -> tuple[Console, StringIO]:
    """Return (Console, buffer) suitable for asserting on TerminalIO output
    without touching real stdout/stderr or rich's color rendering."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=120)
    return console, buf


def test_terminal_io_info_writes_to_console() -> None:
    out_console, out_buf = _capture_console()
    io = TerminalIO(stdout=out_console)
    io.info("hello")
    assert "hello" in out_buf.getvalue()


def test_terminal_io_does_not_interpret_bracket_tokens_as_markup() -> None:
    """A literal '[dir]' / '[file]' token (the prune list's type tag) must survive
    verbatim. rich would otherwise parse '[dir]' as inline markup and silently strip
    it. markup=False is set per print(), so the guarantee holds even here, where the
    caller injects a markup-enabled Console (rich's default) — not only on the default
    Console TerminalIO builds for itself."""
    out_console, out_buf = _capture_console()  # injected Console; markup defaults to True
    io = TerminalIO(stdout=out_console)
    io.info("    [dir] /home/.claude/skills/condition-based-waiting")
    assert "[dir]" in out_buf.getvalue()


def test_terminal_io_verbose_suppressed_when_verbose_flag_false() -> None:
    """Pins the default-quiet contract: verbose=True messages do not
    render unless TerminalIO was constructed with verbose=True."""
    out_console, out_buf = _capture_console()
    io = TerminalIO(stdout=out_console)  # verbose defaults to False
    io.info("loud", verbose=True)
    assert out_buf.getvalue() == ""


def test_terminal_io_verbose_emitted_when_verbose_flag_true() -> None:
    out_console, out_buf = _capture_console()
    io = TerminalIO(stdout=out_console, verbose=True)
    io.info("loud", verbose=True)
    assert "loud" in out_buf.getvalue()


def test_terminal_io_err_goes_to_stderr() -> None:
    """Pins the stdout/stderr split - err() must not pollute stdout."""
    out_console, out_buf = _capture_console()
    err_console, err_buf = _capture_console()
    io = TerminalIO(stdout=out_console, stderr=err_console)
    io.err("oops")
    assert "oops" in err_buf.getvalue()
    assert "oops" not in out_buf.getvalue()


def test_terminal_io_is_interactive_reflects_tty() -> None:
    """Pins the 'both ends must be TTY' contract."""
    io = TerminalIO()
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("sys.stdout.isatty", return_value=True),
    ):
        assert io.is_interactive() is True
    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("sys.stdout.isatty", return_value=False),
    ):
        assert io.is_interactive() is False
    with (
        patch("sys.stdin.isatty", return_value=False),
        patch("sys.stdout.isatty", return_value=True),
    ):
        assert io.is_interactive() is False


@pytest.mark.parametrize("channel_name", ["ok", "warn", "err", "header"])
def test_terminal_io_other_channels_respect_verbose_flag(channel_name: str) -> None:
    """Pins: the verbose-suppression branch fires on every output channel,
    not just info()."""
    out_console, out_buf = _capture_console()
    err_console, err_buf = _capture_console()
    io = TerminalIO(stdout=out_console, stderr=err_console)  # verbose=False
    method = getattr(io, channel_name)
    method("quiet", verbose=True)
    # err writes to err_buf; everything else writes to out_buf
    target = err_buf if channel_name == "err" else out_buf
    assert target.getvalue() == ""


def test_terminal_io_other_channels_emit_when_enabled() -> None:
    """Pins: non-verbose calls on all output channels actually write output."""
    out_console, out_buf = _capture_console()
    err_console, err_buf = _capture_console()
    io = TerminalIO(stdout=out_console, stderr=err_console)
    for name in ("ok", "warn", "header"):
        getattr(io, name)("visible")
    io.err("visible-err")
    assert "visible" in out_buf.getvalue()
    assert "visible-err" in err_buf.getvalue()


def test_terminal_io_show_diff_renders_diff_markers() -> None:
    """Pins: show_diff produces unified-diff output containing standard
    diff markers. Validates the difflib + Syntax pipeline fires end-to-end."""
    out_console, out_buf = _capture_console()
    io = TerminalIO(stdout=out_console)
    io.show_diff("config.yaml", b"old line\n", b"new line\n")
    output = out_buf.getvalue()
    # unified_diff always emits --- / +++ header lines
    assert "---" in output or "+++" in output or "@@" in output
