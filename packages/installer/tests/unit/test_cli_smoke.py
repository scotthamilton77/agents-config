"""Smoke tests for installer.cli.main.

Each test pins a CLI-level behaviour contract from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for argparse machinery and exit-code propagation by SystemExit
are absent — they test the stdlib, not coded decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.cli import main
from installer.core.io_port import ScriptedIO
from installer.core.model import Tool
from installer.tools import registry


def _home_with_claude_settings(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def _repo_with_installer_toml(tmp_path: Path, *, retired: list[str]) -> Path:
    """Create a repo_root whose packages/installer/installer.toml carries the
    given prune list — mirroring where _run_prune now derives the config path
    (off the injected repo_root, not __file__)."""
    repo = tmp_path / "repo"
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True)
    retired_lines = "\n".join(f'  "{glob}",' for glob in retired)
    (toml_dir / "installer.toml").write_text(f"[prune]\nretired = [\n{retired_lines}\n]\n")
    return repo


def _repo_with_malformed_installer_toml(tmp_path: Path) -> Path:
    """Create a repo_root whose installer.toml is type-malformed: prune.retired
    is a bare string, which load_installer_toml rejects with ValueError (it would
    otherwise list()-shred into single-character globs)."""
    repo = tmp_path / "repo"
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True)
    (toml_dir / "installer.toml").write_text('[prune]\nretired = "*/skills/ralf-it"\n')
    return repo


def _hermetic_repo(tmp_path: Path) -> Path:
    """A minimal source repo: one shared template so a Claude plan is
    non-empty, plus empty tool-root dirs the adapters expect."""
    repo = tmp_path / "repo"
    shared = repo / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "INSTRUCTIONS.md.template").write_bytes(b"shared laws\n")
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)
    return repo


def test_main_help_exits_with_status_zero() -> None:
    """
    When main(["--help"]) is invoked
    Then SystemExit(0) is raised.
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0


def test_main_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    """
    When main(["--help"]) is invoked
    Then usage text is printed to stdout.
    """
    with pytest.raises(SystemExit):
        main(["--help"])
    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "installer" in captured.out


def test_main_no_args_returns_zero_against_hermetic_home_with_settings(
    tmp_path: Path,
) -> None:
    """
    Given a home directory with a file at .claude/settings.json
    When main([], home=that_home) is invoked
    Then it returns 0.
    """
    home = _home_with_claude_settings(tmp_path)
    assert main([], home=home) == 0


def test_main_tools_claude_returns_zero(tmp_path: Path) -> None:
    """
    When main(["--tools=claude"], home=any) is invoked
    Then it returns 0.
    """
    assert main(["--tools=claude"], home=tmp_path) == 0


def test_main_tools_unregistered_returns_2_and_writes_unknown_tool_to_stderr(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a Tool enum value whose adapter is absent from the registry
    When main(["--tools=<that>"], home=any) is invoked
    Then it returns 2
    And stderr contains "Unknown tool: '<that>'".

    Pins: the CLI rejects an enum value that has no registered adapter
    (registry-is-truth). Every Tool now has an adapter, so the unregistered
    case is simulated by removing one entry.
    """
    reduced = {t: a for t, a in registry._REGISTRY.items() if t is not Tool.OPENCODE}
    monkeypatch.setattr(registry, "_REGISTRY", reduced)
    rc = main(["--tools=opencode"], home=tmp_path)
    assert rc == 2
    captured = capsys.readouterr()
    assert "Unknown tool: 'opencode'" in captured.err


def test_main_tools_empty_returns_2_and_writes_usage_error_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main(["--tools="], home=any) is invoked
    Then it returns 2
    And stderr contains "--tools= requires at least one tool".
    """
    rc = main(["--tools="], home=tmp_path)
    assert rc == 2
    captured = capsys.readouterr()
    assert "--tools= requires at least one tool" in captured.err


def test_main_tools_foo_returns_2(tmp_path: Path) -> None:
    """
    When main(["--tools=foo"], home=any) is invoked
    Then it returns 2.
    """
    assert main(["--tools=foo"], home=tmp_path) == 2


def test_main_no_args_against_empty_home_returns_2_with_detection_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given an empty home directory (no agent tools detectable)
    When main([], home=that_home) is invoked
    Then it returns 2
    And stderr names the failure ("no agent tools detected")
    And stderr lists each known tool by name
    And stderr lists each tool's detection signal
    And stderr names the home directory that was probed
    And stderr suggests the --tools= escape hatch.

    Pins: empty auto-detect must NOT silently succeed — see Codex
    adversarial review of PR #86 (2026-05-23). Forces operators to
    either install a recognized tool or pass --tools= explicitly.
    """
    rc = main([], home=tmp_path)
    assert rc == 2
    captured = capsys.readouterr()
    assert "no agent tools detected" in captured.err
    assert "claude" in captured.err
    assert "settings.json" in captured.err
    assert str(tmp_path) in captured.err
    assert "--tools=" in captured.err


# ── G.5 / G.7: prune flags + --yes wiring ──


def test_prune_and_prune_only_together_is_mutually_exclusive_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main(["--prune", "--prune-only"]) is invoked
    Then argparse exits 2 (mutually exclusive group rejects both).

    Pins: --prune and --prune-only cannot be combined (installer-design.md G.5).
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--prune", "--prune-only"], home=tmp_path)
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "not allowed with" in captured.err


def test_prune_only_against_empty_source_prunes_unstaged_dest_entry(tmp_path: Path) -> None:
    """
    Given a home with a claude skills/ entry matching the bundled prune list and
    an empty source repo (nothing staged), under --prune-only --yes
    When main runs (non-interactive io)
    Then the unstaged, retired entry is removed.

    Pins: --prune-only scans + prunes against the in-memory plan without an
    install half, and --yes waives the non-interactive guard.
    """
    home = _home_with_claude_settings(tmp_path)
    retired = home / ".claude" / "skills" / "ralf-it"
    retired.mkdir(parents=True)
    # Source repo is empty (nothing staged) but carries an installer.toml whose
    # prune list matches the orphan, so _run_prune loads a non-empty list.
    repo = _repo_with_installer_toml(tmp_path, retired=["*/skills/ralf-it"])
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=io,
        repo_root=repo,
    )

    assert rc == 0
    assert not retired.exists()
    # Companion to the missing-config case: when installer.toml IS present, the
    # missing-config warning is not emitted.
    assert not any(
        e.channel == "warn" and "installer.toml not found" in e.message for e in io.transcript
    )


def test_prune_only_warns_and_exits_clean_when_installer_toml_absent(tmp_path: Path) -> None:
    """
    Given a repo_root whose packages/installer/installer.toml does NOT exist,
    under --prune-only --yes
    When main runs (non-interactive io)
    Then a warning naming the missing path is emitted through io and the run
    still exits cleanly (0) — an absent prune list deletes nothing (fail-safe),
    so the no-op is explained rather than silent.

    Pins: _run_prune derives the config path from repo_root and warns on the
    missing-file case (PR #151 comment 3408241642).
    """
    home = _home_with_claude_settings(tmp_path)
    # An orphan that WOULD match the bundled prune list, to prove it is the
    # empty list (not a non-match) that spares it from pruning.
    retired = home / ".claude" / "skills" / "ralf-it"
    retired.mkdir(parents=True)
    empty_repo = tmp_path / "no-toml-repo"
    empty_repo.mkdir()  # no packages/installer/installer.toml underneath
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=io,
        repo_root=empty_repo,
    )

    assert rc == 0
    assert retired.exists()  # empty prune list => nothing pruned
    warnings = [
        e for e in io.transcript if e.channel == "warn" and "installer.toml not found" in e.message
    ]
    assert len(warnings) == 1
    assert str(empty_repo / "packages" / "installer" / "installer.toml") in warnings[0].message


def test_prune_only_non_interactive_without_yes_fails(tmp_path: Path) -> None:
    """
    Given --prune-only with a matching orphan, a non-interactive io, and no --yes
    When main runs
    Then it returns a non-zero status (the prune flow's hard-fail guard).
    """
    home = _home_with_claude_settings(tmp_path)
    (home / ".claude" / "skills" / "ralf-it").mkdir(parents=True)
    repo = _repo_with_installer_toml(tmp_path, retired=["*/skills/ralf-it"])

    rc = main(
        ["--prune-only", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc != 0


def test_prune_only_with_malformed_installer_toml_returns_2_and_errs_through_io(
    tmp_path: Path,
) -> None:
    """
    Given a repo_root whose packages/installer/installer.toml is type-malformed
    (prune.retired is a string, not a list), under --prune-only --yes
    When main runs (non-interactive io)
    Then it returns 2 (the config-error exit convention)
    And the malformed-config message is surfaced through io's err channel
    And no uncaught traceback escapes.

    Pins: _run_prune catches the ValueError that load_installer_toml raises on a
    type-malformed installer.toml and fails cleanly via io.err + return 2 rather
    than crashing the CLI (PR #151 comment 3408271848).
    """
    home = _home_with_claude_settings(tmp_path)
    repo = _repo_with_malformed_installer_toml(tmp_path)
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=io,
        repo_root=repo,
    )

    assert rc == 2
    errs = [
        e
        for e in io.transcript
        if e.channel == "err" and "retired must be a list of strings" in e.message
    ]
    assert len(errs) == 1


def test_prune_plugin_discovery_honors_injected_repo_root(tmp_path: Path) -> None:
    """
    Given two repo_roots — one whose src/plugins/ contains a plugin directory and
    one lacking src/plugins entirely — each with a valid installer.toml,
    under --prune-only --yes
    When main runs against each (non-interactive io)
    Then plugin discovery resolves against the *injected* repo_root: the run
    completes cleanly (0) in both cases, and the run whose repo_root lacks
    src/plugins discovers nothing (no plugin staging is attempted off the real
    repo's src/plugins).

    Pins: main resolves plugins against the injected repo_root
    (repo_root / "src" / "plugins"), not the module-level _REPO_ROOT, and passes
    them to _run_prune, so repo_root is fully authoritative (PR #151 comment
    3408271853). With a repo_root lacking src/plugins, discover() returns {} —
    proving the real repo's plugins are not consulted.
    """
    home = _home_with_claude_settings(tmp_path)

    # repo_root WITH a plugin under src/plugins/: discovery has something to find
    # there, and the run must not error reaching for the real repo's plugins.
    repo_with_plugins = _repo_with_installer_toml(tmp_path / "with", retired=[])
    (repo_with_plugins / "src" / "plugins" / "beads").mkdir(parents=True)
    rc_with = main(
        ["--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo_with_plugins,
    )
    assert rc_with == 0

    # repo_root WITHOUT src/plugins: discover() returns {} for the injected root.
    # If discovery had ignored repo_root and used the real _REPO_ROOT/src/plugins,
    # this assertion could not distinguish the two — the injected empty root is
    # what makes "no plugins" observable.
    repo_no_plugins = _repo_with_installer_toml(tmp_path / "without", retired=[])
    assert not (repo_no_plugins / "src" / "plugins").exists()
    rc_without = main(
        ["--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo_no_plugins,
    )
    assert rc_without == 0


def test_plain_prune_non_interactive_without_yes_fails_on_consent_guard(tmp_path: Path) -> None:
    """
    Given plain --prune (not --prune-only), a non-interactive io, and no --yes
    When main runs
    Then it returns non-zero — the consent guard refuses a destructive run that
    cannot prompt (G.7), before any orphan scan.
    """
    home = _home_with_claude_settings(tmp_path)
    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir()

    rc = main(
        ["--prune", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=empty_repo,
    )

    assert rc != 0


def test_dump_stage_materialises_plan_and_returns_zero(tmp_path: Path) -> None:
    """
    Given a hermetic source repo and a Claude install signal in home
    When main(["--dump-stage=<out>", "--tools=claude"], repo_root=repo) runs
    Then it returns 0
    And the staged shared template lands at <out>/claude/INSTRUCTIONS.md.
    """
    repo = _hermetic_repo(tmp_path)
    out = tmp_path / "dump"

    rc = main(
        [f"--dump-stage={out}", "--tools=claude"],
        home=tmp_path,
        repo_root=repo,
    )

    assert rc == 0
    assert (out / "claude" / "INSTRUCTIONS.md").read_bytes() == b"shared laws\n"


def test_dump_stage_writes_nothing_under_home(tmp_path: Path) -> None:
    """
    Given a home with a Claude detection signal but no installed config tree
    When main runs in --dump-stage mode
    Then the only thing under .claude is the detection signal that was already
    there — the dump touches no install destination.
    """
    repo = _hermetic_repo(tmp_path)
    home = _home_with_claude_settings(tmp_path)
    out = tmp_path / "dump"

    main([f"--dump-stage={out}", "--tools=claude"], home=home, repo_root=repo)

    under_claude = sorted(p.name for p in (home / ".claude").iterdir())
    assert under_claude == ["settings.json"]


def test_dump_stage_prints_dump_path_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main runs in --dump-stage mode
    Then the dump path is printed to stdout (operator-facing breadcrumb).

    Whitespace is collapsed before the substring check: rich's Console
    soft-wraps long lines at the detected terminal width (80 under capsys), so
    a long temp path is split across physical lines. That wrapping is a
    rendering artifact of console width — an injectable concern, per the
    io_port suite's width=120 Console — not part of the "path is printed"
    contract.
    """
    repo = _hermetic_repo(tmp_path)
    out = tmp_path / "dump"

    main([f"--dump-stage={out}", "--tools=claude"], home=tmp_path, repo_root=repo)

    printed = "".join(capsys.readouterr().out.split())
    assert "".join(str(out).split()) in printed


def test_dump_stage_non_empty_target_returns_2_with_stderr_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a --dump-stage target that already holds files
    When main runs in --dump-stage mode
    Then it returns 2 (not an uncaught traceback)
    And stderr names the not-empty target.

    Pins: the debug flag fails cleanly on a dirty target rather than crashing,
    consistent with the CLI's other return-2 error paths.
    """
    repo = _hermetic_repo(tmp_path)
    out = tmp_path / "dump"
    out.mkdir()
    (out / "stale.txt").write_bytes(b"old\n")

    rc = main([f"--dump-stage={out}", "--tools=claude"], home=tmp_path, repo_root=repo)

    assert rc == 2
    assert "not empty" in capsys.readouterr().err


# ── Integration: --dump-stage ⊥ --prune/--prune-only (cross-PR seam) ──


def test_dump_stage_and_prune_together_is_mutually_exclusive_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    When main(["--dump-stage=<p>", "--prune"]) is invoked
    Then argparse exits 2 — --dump-stage and --prune share one mutually
    exclusive group, so the three terminal modes cannot combine.

    Pins the cross-PR integration seam: --dump-stage ⊥ --prune/--prune-only,
    realised when the prune pipeline and the --dump-stage debug flag merged.
    """
    with pytest.raises(SystemExit) as exc_info:
        main(["--dump-stage", str(tmp_path / "out"), "--prune"], home=tmp_path)
    assert exc_info.value.code == 2
    assert "not allowed with" in capsys.readouterr().err


# ── W4: --plugins flag wiring ──


def _repo_with_widget_plugin(tmp_path: Path) -> Path:
    """A hermetic repo plus a discoverable 'widget' plugin whose overlay
    contributes a Claude rules file. The rule lands in the Claude plan only
    when the widget plugin is active for the run."""
    repo = _hermetic_repo(tmp_path)
    rule = repo / "src" / "plugins" / "widget" / ".claude" / "rules" / "widget-rule.md"
    rule.parent.mkdir(parents=True)
    rule.write_bytes(b"widget rule\n")
    return repo


def test_dump_stage_honors_plugins_override_over_footprint_autodetect(tmp_path: Path) -> None:
    """
    Given a discoverable 'widget' plugin (overlaying claude rules/widget-rule.md)
    and a home carrying the ~/.widget footprint plugin auto-detection keys on
    When --dump-stage runs WITHOUT --plugins
    Then the plugin's rule is staged (auto-detect includes the footprint plugin);
    And when --dump-stage runs WITH an empty --plugins=
    Then the plugin's rule is absent.

    Pins: args.plugins flows to the dump-stage resolve_plugins call. An empty
    --plugins= installs no plugins (resolve_plugins '' -> ()), overriding the
    footprint auto-detect. Fails while the call site hardcodes override_csv=None
    — the empty value would be ignored and widget staged regardless.
    """
    repo = _repo_with_widget_plugin(tmp_path)
    home = _home_with_claude_settings(tmp_path)
    (home / ".widget").mkdir()
    staged = Path("claude") / "rules" / "widget-rule.md"

    auto_out = tmp_path / "auto"
    assert main([f"--dump-stage={auto_out}", "--tools=claude"], home=home, repo_root=repo) == 0
    assert (auto_out / staged).exists()

    empty_out = tmp_path / "empty"
    rc = main(
        [f"--dump-stage={empty_out}", "--tools=claude", "--plugins="],
        home=home,
        repo_root=repo,
    )
    assert rc == 0
    assert not (empty_out / staged).exists()


def test_unknown_plugin_value_returns_2_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a repo whose discoverable plugin set does not include 'bogus'
    When main(["--plugins=bogus", "--tools=claude"]) runs a plain install
    Then it returns 2
    And stderr names the unknown plugin ("Unknown plugin: 'bogus'").

    Pins: --plugins is validated up front on every path — not only --dump-stage
    and --prune — so a bad value fails fast and cleanly (exit 2) rather than
    being silently ignored or crashing with a traceback. Mirrors the --tools=
    guard. Fails on the plain path while plugins are resolved only inside the
    --dump-stage / --prune branches.
    """
    repo = _repo_with_widget_plugin(tmp_path)
    rc = main(["--plugins=bogus", "--tools=claude"], home=tmp_path, repo_root=repo)
    assert rc == 2
    assert "Unknown plugin: 'bogus'" in capsys.readouterr().err


def test_prune_only_honors_plugins_override(tmp_path: Path) -> None:
    """
    Given a 'widget' plugin overlaying claude rules/widget-rule.md, a dest entry
    ~/.claude/rules/widget-rule.md, an installer.toml retiring that key, and NO
    ~/.widget footprint (so auto-detect alone would exclude widget)
    When --prune-only --yes runs with --plugins=widget
    Then the dest entry is spared — an active plugin stages that basename, so the
    orphan scan treats it as known rather than retired;
    And when the same dest is run again with an empty --plugins=
    Then the dest entry is pruned — excluded, nothing stages it, so it is an
    orphan matching the retired glob.

    Pins: the up-front resolved plugins tuple is threaded into _run_prune. Fails
    while _run_prune re-resolves plugins internally with override_csv=None —
    which, absent the footprint, excludes widget even under --plugins=widget and
    prunes the dest.
    """
    repo = _repo_with_installer_toml(tmp_path, retired=["claude/rules/widget-rule.md"])
    rule = repo / "src" / "plugins" / "widget" / ".claude" / "rules" / "widget-rule.md"
    rule.parent.mkdir(parents=True)
    rule.write_bytes(b"widget rule\n")

    home = _home_with_claude_settings(tmp_path)
    dest_rule = home / ".claude" / "rules" / "widget-rule.md"
    dest_rule.parent.mkdir(parents=True)
    dest_rule.write_bytes(b"installed widget rule\n")

    # Active via explicit override (no footprint) -> staged -> spared.
    rc_active = main(
        ["--prune-only", "--yes", "--tools=claude", "--plugins=widget"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc_active == 0
    assert dest_rule.exists()

    # Excluded via empty override -> unstaged -> pruned.
    rc_excluded = main(
        ["--prune-only", "--yes", "--tools=claude", "--plugins="],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc_excluded == 0
    assert not dest_rule.exists()
