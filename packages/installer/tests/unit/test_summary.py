"""Unit tests for installer.core.summary.render_summary (8.18 — install summary).

The renderer is the in-memory port of the bash install Summary
(``scripts/install.sh:1801-1869``). It is pure: it takes the per-target merged
``Counters``, the active tool/plugin lists, the ALL_* universes, and a verbose
flag, and emits through the injected ``IOPort``. These tests drive it with
``ScriptedIO`` and assert the recorded transcript STRINGS and the per-target
grouping decisions — never which method fired, and never a Counters default.

Covered decisions (bash spec line refs in each test):
- verbose per-tool block with the six fields in bash order,
- the DIM '(not detected, skipped)' footer for an ALL_* target absent from the
  active/report set,
- a plugin pruned outside the active set is reported (bash AC#19),
- quiet one-line-per-target, only for targets with non-zero changes,
- quiet all-zero prints exactly the em-dash 'up to date' line,
- a zero-change target is omitted from the quiet summary but still printed
  (all-zeros) in the verbose block.
"""

from __future__ import annotations

from installer.core.io_port import ScriptedIO, TranscriptEntry
from installer.core.model import Counters
from installer.core.summary import render_summary


def _messages(io: ScriptedIO) -> list[str]:
    return [e.message for e in io.transcript]


def test_verbose_block_lists_six_fields_in_bash_order() -> None:
    """
    Given a single active tool with a created+updated+merged+pruned+backed_up+
    skipped spread, under verbose
    When render_summary runs
    Then its block lists the six fields in EXACT bash order — Installed, Updated,
    Merged, Backed up, Pruned, Skipped (scripts/install.sh:1820-1825) — with
    'Installed' sourced from Counters.created.
    """
    io = ScriptedIO()
    counters = {
        "claude": Counters(created=3, updated=2, merged=1, skipped=5, pruned=4, backed_up=6)
    }

    render_summary(
        counters,
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=True,
        io=io,
    )

    msgs = _messages(io)
    # The six field lines, in order, immediately follow the per-tool header.
    field_lines = [
        m
        for m in msgs
        if m.strip().split(":")[0]
        in {"Installed", "Updated", "Merged", "Backed up", "Pruned", "Skipped"}
    ]
    labels = [m.strip().split(":")[0] for m in field_lines]
    assert labels == ["Installed", "Updated", "Merged", "Backed up", "Pruned", "Skipped"]
    # 'Installed' carries created's value, not a coincidental zero.
    assert any(m.strip() == "Installed:  3" for m in msgs), msgs
    assert any(m.strip() == "Pruned:     4" for m in msgs), msgs


def test_verbose_names_the_target_in_its_block_header() -> None:
    """
    Given an active tool, under verbose
    When render_summary runs
    Then a header naming the tool ('-- claude --') is emitted before its fields
    (scripts/install.sh:1819).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude", "codex"],
        all_plugins=[],
        verbose=True,
        io=io,
    )

    headers = [e.message for e in io.transcript if e.channel == "header"]
    assert any("claude" in h for h in headers), headers


def test_verbose_emits_not_detected_footer_for_inactive_all_tool() -> None:
    """
    Given ALL_TOOLS={claude,codex} but only claude active, under verbose
    When render_summary runs
    Then a DIM '-- codex (not detected, skipped) --' footer is emitted for the
    inactive tool (scripts/install.sh:1832-1834) and claude gets a real block.
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude", "codex"],
        all_plugins=[],
        verbose=True,
        io=io,
    )

    msgs = _messages(io)
    assert any("codex" in m and "not detected, skipped" in m for m in msgs), msgs
    # claude is active -> it gets a real block, NOT a skipped footer.
    assert not any("claude" in m and "not detected, skipped" in m for m in msgs), msgs


def test_verbose_plugin_pruned_outside_active_set_gets_real_block_not_footer() -> None:
    """
    Given beads NOT in the active plugin set but carrying pruned activity, under
    verbose
    When render_summary runs
    Then beads gets a real '-- beads --' block (its pruned tally), NOT a
    '(not detected, skipped)' footer — bash AC#19 (scripts/install.sh:1808-1812,
    keyed off REPORT_TARGETS so it is not double-printed).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1), "beads": Counters(pruned=2, backed_up=2)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=["beads"],
        verbose=True,
        io=io,
    )

    msgs = _messages(io)
    headers = [e.message for e in io.transcript if e.channel == "header"]
    assert any("beads" in h for h in headers), headers
    assert not any("beads" in m and "not detected, skipped" in m for m in msgs), msgs


def test_quiet_one_line_per_nonzero_target() -> None:
    """
    Given two active tools, one with changes (claude) and one all-zero (codex),
    under quiet (verbose=False)
    When render_summary runs
    Then claude gets a one-line summary naming its non-zero parts and codex is
    omitted (scripts/install.sh:1847-1858).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=2, updated=1), "codex": Counters(skipped=4)},
        tools=["claude", "codex"],
        plugins=[],
        all_tools=["claude", "codex"],
        all_plugins=[],
        verbose=False,
        io=io,
    )

    msgs = _messages(io)
    assert any("claude:" in m and "2 installed" in m and "1 updated" in m for m in msgs), msgs
    # codex changed nothing (only skips) -> no quiet line for it.
    assert not any(m.startswith("codex:") for m in msgs), msgs


def test_quiet_all_zero_prints_up_to_date_em_dash_line() -> None:
    """
    Given every active target all-zero (only skips), under quiet
    When render_summary runs
    Then it prints exactly 'All files up to date — no changes made.' (note the
    em-dash) and no per-target lines (scripts/install.sh:1862-1863).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(skipped=9)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=False,
        io=io,
    )

    msgs = _messages(io)
    assert any(m == "All files up to date — no changes made." for m in msgs), msgs
    assert not any(m.startswith("claude:") for m in msgs), msgs


def test_quiet_skipped_is_not_a_change_but_verbose_still_prints_the_block() -> None:
    """
    Given an all-skips target, comparing quiet vs verbose
    When render_summary runs each way
    Then quiet omits it from the per-target lines (skips are not 'changes':
    installed+updated+merged+pruned == 0, scripts/install.sh:1848) BUT verbose
    still prints its full all-but-skipped block (scripts/install.sh:1818 iterates
    every REPORT_TARGET regardless of activity).
    """
    counters = {"claude": Counters(skipped=7)}

    quiet_io = ScriptedIO()
    render_summary(
        counters,
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=False,
        io=quiet_io,
    )
    assert not any(m.startswith("claude:") for m in _messages(quiet_io))

    verbose_io = ScriptedIO()
    render_summary(
        counters,
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=True,
        io=verbose_io,
    )
    vmsgs = _messages(verbose_io)
    assert any("claude" in e.message for e in verbose_io.transcript if e.channel == "header")
    assert any(m.strip() == "Skipped:    7" for m in vmsgs), vmsgs


def test_quiet_reports_pruned_and_backed_up_parts() -> None:
    """
    Given a target whose only activity is a prune (pruned + backed_up), under quiet
    When render_summary runs
    Then its one-line summary names 'pruned' and 'backed up' (pruned counts as a
    change; scripts/install.sh:1855-1856) so a --prune run surfaces in the quiet
    summary.
    """
    io = ScriptedIO()
    render_summary(
        {"beads": Counters(pruned=3, backed_up=3)},
        tools=[],
        plugins=["beads"],
        all_tools=[],
        all_plugins=["beads"],
        verbose=False,
        io=io,
    )

    msgs = _messages(io)
    assert any("beads:" in m and "3 pruned" in m and "3 backed up" in m for m in msgs), msgs


def test_verbose_summary_header_is_dash_wrapped_with_leading_blank() -> None:
    """
    Given any verbose run
    When render_summary runs
    Then the 'Summary' header byte-matches bash header() — wrapped '-- Summary --'
    (NOT bare 'Summary') and preceded by a blank line (scripts/install.sh:162,1816).
    A bare 'Summary' or a missing leading blank is a parity regression.
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=True,
        io=io,
    )

    msgs = _messages(io)
    assert "-- Summary --" in msgs, msgs
    assert "Summary" not in msgs, msgs  # never the unwrapped form
    summary_idx = msgs.index("-- Summary --")
    assert summary_idx > 0 and msgs[summary_idx - 1] == "", msgs


def test_verbose_block_and_footer_headers_are_dash_wrapped_with_leading_blank() -> None:
    """
    Given an active tool and an inactive ALL_* tool, under verbose
    When render_summary runs
    Then each per-tool block header and each '(not detected, skipped)' footer is
    '-- ... --' wrapped and immediately preceded by a blank line, byte-matching
    bash's leading-'\\n' printf (scripts/install.sh:1819,1833).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude", "codex"],
        all_plugins=[],
        verbose=True,
        io=io,
    )

    msgs = _messages(io)
    block_idx = msgs.index("-- claude --")
    assert msgs[block_idx - 1] == "", msgs
    footer = "-- codex (not detected, skipped) --"
    footer_idx = msgs.index(footer)
    assert msgs[footer_idx - 1] == "", msgs


def test_verbose_emits_blank_line_before_done() -> None:
    """
    Given any verbose run
    When render_summary runs
    Then the final 'Done.' is immediately preceded by a blank line, matching
    bash's ``echo ""`` before ``ok "Done."`` (scripts/install.sh:1844-1845).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=True,
        io=io,
    )

    done_idx = next(i for i, e in enumerate(io.transcript) if e.channel == "ok")
    assert io.transcript[done_idx].message == "Done."
    assert io.transcript[done_idx - 1].message == "", _messages(io)


def test_quiet_emits_blank_line_before_outcome() -> None:
    """
    Given a quiet run that changed nothing
    When render_summary runs
    Then a blank line precedes the 'up to date' line, matching bash's ``echo ""``
    ahead of the quiet outcome branch (scripts/install.sh:1859).
    """
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(skipped=2)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=False,
        io=io,
    )

    outcome_idx = next(i for i, e in enumerate(io.transcript) if e.channel == "ok")
    assert io.transcript[outcome_idx - 1].message == "", _messages(io)


def test_entries_carry_a_transcript_record() -> None:
    """A sanity guard that the renderer routes through IOPort (records a
    transcript) rather than printing — so the pure-core/injected-IO contract
    holds. Pins the seam, not a Counters default."""
    io = ScriptedIO()
    render_summary(
        {"claude": Counters(created=1)},
        tools=["claude"],
        plugins=[],
        all_tools=["claude"],
        all_plugins=[],
        verbose=True,
        io=io,
    )
    assert io.transcript
    assert all(isinstance(e, TranscriptEntry) for e in io.transcript)


def test_cli_targets_render_as_blocks() -> None:
    """
    Given counters keyed cli:workcli with activity
    When render_summary runs with clis=("cli:workcli",)
    Then verbose renders a '-- cli:workcli --' block and quiet renders its
    change line (previously cli:* keys were silently dropped).

    Pins spec §6 summary-rendering change.
    """
    counters = {"cli:workcli": Counters(created=1)}
    io = ScriptedIO()
    render_summary(
        counters,
        tools=[],
        plugins=[],
        all_tools=[],
        all_plugins=[],
        clis=["cli:workcli"],
        verbose=True,
        io=io,
    )
    assert any(e.message == "-- cli:workcli --" for e in io.transcript)
    io2 = ScriptedIO()
    render_summary(
        counters,
        tools=[],
        plugins=[],
        all_tools=[],
        all_plugins=[],
        clis=["cli:workcli"],
        verbose=False,
        io=io2,
    )
    assert any("cli:workcli: 1 installed" in e.message for e in io2.transcript)
