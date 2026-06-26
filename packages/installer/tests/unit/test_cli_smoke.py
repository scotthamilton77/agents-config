"""Smoke tests for installer.cli.main.

Each test pins a CLI-level behaviour contract from the B.1 spec
(docs/specs/2026-05-23-w1qls.2.1-config-claude-adapter-design.md).
Tests for argparse machinery and exit-code propagation by SystemExit
are absent — they test the stdlib, not coded decisions."""

from __future__ import annotations

import subprocess
import sys
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


def _write_installignore(repo: Path) -> None:
    """Mirror the real repo-root .installignore so cli.main's up-front fail-fast
    load finds it. main() refuses to run without one (exit 2), so every hermetic
    repo a CLI smoke test points main() at must carry the manifest."""
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".installignore").write_text(
        "AGENTS.md\nCLAUDE.md\nGEMINI.md\nREADME.md\nSESSION-PRIMER-README.md\nrules-readmes/\n",
        encoding="utf-8",
    )


def _repo_with_installer_toml(tmp_path: Path, *, retired: list[str]) -> Path:
    """Create a repo_root whose packages/installer/installer.toml carries the
    given prune list — mirroring where _run_prune now derives the config path
    (off the injected repo_root, not __file__)."""
    repo = tmp_path / "repo"
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True)
    retired_lines = "\n".join(f'  "{glob}",' for glob in retired)
    (toml_dir / "installer.toml").write_text(f"[prune]\nretired = [\n{retired_lines}\n]\n")
    _write_installignore(repo)
    return repo


def _repo_with_malformed_installer_toml(tmp_path: Path) -> Path:
    """Create a repo_root whose installer.toml is type-malformed: prune.retired
    is a bare string, which load_installer_toml rejects with ValueError (it would
    otherwise list()-shred into single-character globs)."""
    repo = tmp_path / "repo"
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True)
    (toml_dir / "installer.toml").write_text('[prune]\nretired = "*/skills/ralf-it"\n')
    _write_installignore(repo)
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
    _write_installignore(repo)
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


def test_main_dry_run_auto_detect_with_claude_signal_returns_zero(tmp_path: Path) -> None:
    """
    Given a home with a .claude/settings.json install signal and a hermetic repo,
    under --dry-run with no --tools
    When main runs (auto-detect)
    Then it returns 0 — auto-detection finds claude and proceeds past resolution
    (the success counterpart to the empty-home exit-2 path), and --dry-run lets
    the real install path preview without prompting or writing.

    Pins: auto-detect of an installed tool does NOT take the no-tools exit-2
    guard; the run reaches and completes the (dry-run) install path.
    """
    home = _home_with_claude_settings(tmp_path)
    repo = _hermetic_repo(tmp_path)
    assert main(["--dry-run"], home=home, io=ScriptedIO(interactive=False), repo_root=repo) == 0


def test_main_tools_claude_dry_run_returns_zero_and_writes_nothing(tmp_path: Path) -> None:
    """
    When main(["--tools=claude", "--dry-run"]) runs against a hermetic repo
    Then it returns 0 and writes nothing under ~/.claude — --dry-run previews the
    install without prompting (waiving consent) and touches no destination.

    Pins: --tools=claude resolves and the install path runs in preview mode; the
    dry-run write-suppression holds end-to-end through main.
    """
    repo = _hermetic_repo(tmp_path)
    rc = main(
        ["--tools=claude", "--dry-run"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )
    assert rc == 0
    assert not (tmp_path / ".claude").exists()


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


def test_main_autodetect_empty_home_dry_run_selects_claude_returns_zero(
    tmp_path: Path,
) -> None:
    """
    Given an empty home directory (no install signals) and a hermetic repo,
    under --dry-run with no --tools
    When main(["--dry-run"], home=that_home) is invoked
    Then it returns 0 — auto-detect falls back to claude and proceeds.

    Pins: a bare home no longer takes a no-tools exit-2 guard; claude is the
    auto-detect floor, matching install.sh's unconditional `TOOLS=(claude)`.
    """
    repo = _hermetic_repo(tmp_path)
    rc = main(["--dry-run"], home=tmp_path, io=ScriptedIO(interactive=False), repo_root=repo)
    assert rc == 0


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


def test_prune_only_keeps_active_plugin_shipped_formula(tmp_path: Path) -> None:
    """
    Given --plugins=beads --prune-only --yes, a repo whose beads plugin still
    ships current.toml, and a home ~/.beads/formulas holding current.toml AND a
    genuinely retired.toml, both matching a beads/formulas/* prune glob
    When main runs (non-interactive io)
    Then retired.toml is removed but current.toml survives — the CLI threads the
    active plugin set into the prune scan, so a formula the active plugin still
    ships is not an orphan.

    Pins the end-to-end wiring (_run -> _run_prune -> prune_pipeline ->
    scan_orphans). Without it, strict mode deletes the live formula next to the
    retired one.
    """
    repo = _repo_with_installer_toml(tmp_path, retired=["beads/formulas/*"])
    beads_src = repo / "src" / "plugins" / "beads" / ".beads" / "formulas"
    beads_src.mkdir(parents=True)
    (beads_src / "current.toml").write_text("shipped")
    home = _home_with_claude_settings(tmp_path)
    formulas = home / ".beads" / "formulas"
    formulas.mkdir(parents=True)
    (formulas / "current.toml").write_text("shipped")
    (formulas / "retired.toml").write_text("stale")

    rc = main(
        ["--plugins=beads", "--prune-only", "--yes", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (formulas / "current.toml").exists()
    assert not (formulas / "retired.toml").exists()


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
    _write_installignore(empty_repo)  # but the exclusion manifest is required to run
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
    (repo_root / "src" / "plugins"), not the module-level _REPO_ROOT, builds the
    staging plans with them, and passes those plans to _run_prune — so repo_root
    is fully authoritative for plugin discovery (PR #151 comment 3408271853).
    With a repo_root lacking src/plugins, discover() returns {} — proving the
    real repo's plugins are not consulted.
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
    Then it returns non-zero — the install half's consent guard
    (install_pipeline -> sync_plan -> require_consent) refuses a destructive run
    that cannot prompt (G.7) before any file is written or orphan scanned, and
    main surfaces it as exit 1.
    """
    home = _home_with_claude_settings(tmp_path)
    empty_repo = tmp_path / "empty-repo"
    empty_repo.mkdir()
    _write_installignore(empty_repo)  # required to reach the consent guard this test pins

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

    Pins: args.plugins reaches plugin resolution and feeds the --dump-stage
    plan. main() resolves plugins once up front (resolve_plugins '' -> ()) and
    passes the resolved tuple into stage_and_transform, so an empty --plugins=
    installs no plugins, overriding the footprint auto-detect. Fails if
    --plugins is unregistered or its value is dropped (e.g. resolve_plugins
    pinned to override_csv=None) — widget would then be staged regardless.
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


# ── 8.15: prune-exclusion warning when --plugins= excludes a discovered plugin ──


def test_explicit_plugins_override_warns_about_excluded_plugin(tmp_path: Path) -> None:
    """
    Given a discoverable 'widget' plugin and an explicit --plugins= that excludes it
    When main runs a plain install (no --prune)
    Then a warning naming 'widget' and the non-prune guidance is emitted.

    Pins: an explicit --plugins= override that drops a discovered plugin warns the
    operator the already-installed files are NOT removed — bash
    scripts/install.sh:325. Fails while the Python installer drops excluded plugins
    silently (resolve_plugins returns the resolved set with no exclusion warning).
    """
    repo = _repo_with_widget_plugin(tmp_path)
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--tools=claude", "--plugins=", "--yes"],
        home=tmp_path,
        io=io,
        repo_root=repo,
    )

    assert rc == 0
    warns = [e.message for e in io.transcript if e.channel == "warn"]
    assert any("widget" in m and "excluded via --plugins=" in m for m in warns), warns
    # non-prune wording: files already installed are not removed
    assert any("not removed" in m for m in warns), warns


def test_explicit_plugins_override_with_prune_warns_orphan_wording(tmp_path: Path) -> None:
    """
    Given a discoverable 'widget' plugin excluded via --plugins= AND --prune-only
    When main runs
    Then the exclusion warning uses the prune wording (excluded files become
    orphans and may be removed) — bash scripts/install.sh:323.

    Pins: the wording branches on whether a prune phase is active. Fails if the
    warning is unconditional (always the non-prune text) or absent under --prune.
    --prune-only is used so the run needs no installer.toml-present install half.
    """
    repo = _repo_with_widget_plugin(tmp_path)
    # _run_prune reads installer.toml off repo_root; give it an (empty) prune list
    # so the prune phase is a clean no-op rather than a missing-file warning.
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True, exist_ok=True)
    (toml_dir / "installer.toml").write_text("[prune]\nretired = []\n")
    io = ScriptedIO(interactive=False)

    rc = main(
        ["--tools=claude", "--plugins=", "--prune-only", "--yes"],
        home=tmp_path,
        io=io,
        repo_root=repo,
    )

    assert rc == 0
    warns = [e.message for e in io.transcript if e.channel == "warn"]
    assert any("widget" in m and "become orphans" in m for m in warns), warns


def test_autodetect_does_not_warn_about_excluded_plugins(tmp_path: Path) -> None:
    """
    Given a discoverable 'widget' plugin with NO ~/.widget footprint (so
    auto-detect excludes it) and NO explicit --plugins=
    When main runs a plain install
    Then NO exclusion warning is emitted.

    Pins: the exclusion warning fires only under an EXPLICIT --plugins= override
    (bash gates it on PLUGINS_FLAG_SET, scripts/install.sh:308). Auto-detect
    dropping an undetected plugin is normal, not warn-worthy. Fails if the warning
    keys on the discovered-vs-resolved delta regardless of how plugins were
    resolved.
    """
    repo = _repo_with_widget_plugin(tmp_path)
    io = ScriptedIO(interactive=False)

    rc = main(["--tools=claude", "--yes"], home=tmp_path, io=io, repo_root=repo)

    assert rc == 0
    warns = [e.message for e in io.transcript if e.channel == "warn"]
    assert not any("excluded via --plugins=" in m for m in warns), warns


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

    Pins: the resolved plugin set builds the staging plans in main, and those
    plans are threaded into _run_prune — so the --plugins selection reaches the
    orphan scan via the plans. Fails if the plans dropped the override (e.g.
    plugins resolved with override_csv=None): absent the footprint, widget would
    be unstaged even under --plugins=widget and the dest pruned.
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


# ── 8.13: --verbose/-v flag parsing + plumbing into the IOPort ──


@pytest.mark.parametrize("flag", ["--verbose", "-v"])
def test_verbose_flag_constructs_terminal_io_verbose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """
    Given --verbose (or its -v alias) and no injected io
    When main builds the default TerminalIO
    Then TerminalIO is constructed with verbose=True.

    Pins: args.verbose is parsed (both spellings) and threaded into the
    TerminalIO construction in main — the plumbing the bash installer's
    VERBOSE=true wiring (scripts/install.sh:110) ports to. A spy on the lazily
    imported TerminalIO captures the kwarg without touching a real terminal.
    Fails while the flag is unparsed (argparse SystemExit) or constructed with a
    hard-coded verbose=False.
    """
    import installer.core.io_port as io_port_mod

    captured: dict[str, bool] = {}

    def _spy(*, verbose: bool = False, **_kwargs: object) -> ScriptedIO:
        captured["verbose"] = verbose
        return ScriptedIO(interactive=False)

    monkeypatch.setattr(io_port_mod, "TerminalIO", _spy)
    repo = _hermetic_repo(tmp_path)

    main([flag, "--tools=claude", "--dry-run"], home=tmp_path, repo_root=repo)

    assert captured == {"verbose": True}


def test_no_verbose_flag_constructs_terminal_io_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given NO --verbose flag and no injected io
    When main builds the default TerminalIO
    Then TerminalIO is constructed with verbose=False — the default-quiet
    contract, so per-file detail stays suppressed.

    Pins: the absence of --verbose yields verbose=False, the other direction of
    the plumbing.
    """
    import installer.core.io_port as io_port_mod

    captured: dict[str, bool] = {}

    def _spy(*, verbose: bool = False, **_kwargs: object) -> ScriptedIO:
        captured["verbose"] = verbose
        return ScriptedIO(interactive=False)

    monkeypatch.setattr(io_port_mod, "TerminalIO", _spy)
    repo = _hermetic_repo(tmp_path)

    main(["--tools=claude", "--dry-run"], home=tmp_path, repo_root=repo)

    assert captured == {"verbose": False}


def test_verbose_install_renders_per_file_detail_quiet_install_does_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a hermetic repo (one shared template -> a non-empty claude plan),
    under --tools=claude --yes
    When main runs a REAL install with --verbose vs without it (default io)
    Then --verbose renders a per-file line naming the installed dest on stdout,
    while the quiet run renders no such per-file line.

    End-to-end parity assertion: the flag reaches the file-operation sites and
    its presence/absence flips per-file chatter on/off, matching bash vok. The
    install_pipeline emits the staged template's dest under ~/.claude on the
    verbose run only. Uses the real default TerminalIO (no injected io) so the
    whole flag->IOPort->emission chain is exercised; stdout is captured by
    capsys.
    """
    dest = tmp_path / ".claude" / "INSTRUCTIONS.md"

    repo_v = _hermetic_repo(tmp_path / "v")
    home_v = tmp_path
    rc_v = main(["--tools=claude", "--yes", "--verbose"], home=home_v, repo_root=repo_v)
    assert rc_v == 0
    verbose_out = capsys.readouterr().out
    # Collapse whitespace before asserting: terminals in CI wrap long paths at
    # ~80 chars, splitting "INSTRUCTIONS.md" across lines and breaking naive
    # substring checks.
    assert "INSTRUCTIONS.md" in "".join(verbose_out.split())

    # Quiet re-install into a fresh home: the same install produces no per-file
    # line on stdout (the default-quiet contract).
    repo_q = _hermetic_repo(tmp_path / "q")
    home_q = tmp_path / "qhome"
    home_q.mkdir()
    rc_q = main(["--tools=claude", "--yes"], home=home_q, repo_root=repo_q)
    assert rc_q == 0
    quiet_out = capsys.readouterr().out
    assert "INSTRUCTIONS.md" not in "".join(quiet_out.split())
    # sanity: the verbose dest path is the one we expect main to have installed.
    assert dest.exists()


# ── W3: default-path real install (install_pipeline wired into main) ──


def test_main_default_install_writes_staged_plan_to_dest(tmp_path: Path) -> None:
    """
    Given a hermetic source repo (a shared template -> a non-empty claude plan),
    under --tools=claude --yes
    When main runs (non-interactive io; --yes waives the consent prompt)
    Then the staged shared template is written to ~/.claude/INSTRUCTIONS.md
    And main returns 0.

    Pins: the default (no terminal-mode flag) path performs a REAL install — it
    walks each tool's StagingPlan to disk via install_pipeline, honoring
    Config.auto_yes. Fails while main builds Config, discards it, and returns 0
    without installing.
    """
    repo = _hermetic_repo(tmp_path)

    rc = main(
        ["--tools=claude", "--yes"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (tmp_path / ".claude" / "INSTRUCTIONS.md").read_bytes() == b"shared laws\n"


def test_main_default_install_non_interactive_without_consent_returns_one(tmp_path: Path) -> None:
    """
    Given a hermetic source repo and a non-interactive io, under --tools=claude
    with neither --yes nor --dry-run
    When main runs the default install path
    Then it returns 1 — install_pipeline -> sync_plan's require_consent refuses a
    destructive run that cannot prompt (G.7);
    And nothing is written under ~/.claude (the guard fires before any write).

    Pins: the W2 consent contract is enforced at the CLI boundary — main catches
    ConsentRequiredError from the install and returns 1, rather than letting it
    escape as an uncaught traceback. Fails (errors out) while the install_pipeline
    call is unguarded.
    """
    repo = _hermetic_repo(tmp_path)

    rc = main(
        ["--tools=claude"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 1
    assert not (tmp_path / ".claude" / "INSTRUCTIONS.md").exists()


def test_main_prune_installs_then_prunes(tmp_path: Path) -> None:
    """
    Given a hermetic repo whose installer.toml retires '*/skills/ralf-it', a home
    holding that retired orphan, under --prune --yes
    When main runs (non-interactive io; --yes waives consent)
    Then the staged shared template is installed at ~/.claude/INSTRUCTIONS.md
    (install half) AND the retired orphan ~/.claude/skills/ralf-it is removed
    (prune half), and main returns 0.

    Pins: --prune is install-then-prune over ONE shared staging plan — main
    installs the plan, then _run_prune scans the same plan for orphans. Fails
    while --prune skips the install half (the pre-W3 prune-only behaviour of the
    default branch).
    """
    repo = _hermetic_repo(tmp_path)
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True)
    (toml_dir / "installer.toml").write_text('[prune]\nretired = [\n  "*/skills/ralf-it",\n]\n')

    home = tmp_path / "home"
    orphan = home / ".claude" / "skills" / "ralf-it"
    orphan.mkdir(parents=True)

    rc = main(
        ["--prune", "--yes", "--tools=claude"],
        home=home,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 0
    assert (home / ".claude" / "INSTRUCTIONS.md").read_bytes() == b"shared laws\n"
    assert not orphan.exists()


# ── 8.18: install summary renderer wired into main ──


def test_main_quiet_install_renders_summary_line_for_changed_tool(tmp_path: Path) -> None:
    """
    Given a hermetic repo (one shared template -> a claude create), under
    --tools=claude --yes (quiet)
    When main runs a real install
    Then a quiet summary line names claude and its install count is emitted
    through io — the per-tool counters from install_pipeline reach the renderer.

    Pins: main binds install_pipeline's per-tool return and feeds it to
    render_summary. Fails while main discards the counters and prints no summary.
    """
    repo = _hermetic_repo(tmp_path)
    io = ScriptedIO(interactive=False)

    rc = main(["--tools=claude", "--yes"], home=tmp_path, io=io, repo_root=repo)

    assert rc == 0
    oks = [e.message for e in io.transcript if e.channel == "ok"]
    infos = [e.message for e in io.transcript if e.channel == "info"]
    assert any(m == "Done." for m in oks), oks
    assert any("claude:" in m and "installed" in m for m in infos), infos


def test_main_quiet_reinstall_renders_all_up_to_date(tmp_path: Path) -> None:
    """
    Given a home where the claude plan is already installed (a second run), under
    --tools=claude --yes (quiet)
    When main runs again
    Then it emits exactly the em-dash 'All files up to date — no changes made.'
    line — every item is a skip, so nothing changed (scripts/install.sh:1863).

    Pins: the all-zero quiet branch reaches the renderer from a real re-install.
    """
    repo = _hermetic_repo(tmp_path)
    first = ScriptedIO(interactive=False)
    assert main(["--tools=claude", "--yes"], home=tmp_path, io=first, repo_root=repo) == 0

    second = ScriptedIO(interactive=False)
    rc = main(["--tools=claude", "--yes"], home=tmp_path, io=second, repo_root=repo)

    assert rc == 0
    oks = [e.message for e in second.transcript if e.channel == "ok"]
    assert any(m == "All files up to date — no changes made." for m in oks), oks


def test_main_verbose_install_renders_per_tool_block_and_skipped_footer(tmp_path: Path) -> None:
    """
    Given --tools=claude --yes --verbose against a hermetic repo
    When main runs
    Then the verbose summary emits a '-- claude --' block AND a
    '(not detected, skipped)' footer for an inactive ALL_TOOLS tool (e.g. codex),
    proving the active set and the ALL_* universe both reach the renderer.

    Pins: main passes known_tools() as ALL_TOOLS and the active tool list to
    render_summary under verbose.
    """
    repo = _hermetic_repo(tmp_path)
    io = ScriptedIO(interactive=False)

    rc = main(["--tools=claude", "--yes", "--verbose"], home=tmp_path, io=io, repo_root=repo)

    assert rc == 0
    headers = [e.message for e in io.transcript if e.channel == "header"]
    msgs = [e.message for e in io.transcript]
    assert any("-- claude --" in h for h in headers), headers
    assert any("not detected, skipped" in m for m in msgs), msgs


def test_main_prune_summary_reports_pruned_counts(tmp_path: Path) -> None:
    """
    Given a hermetic repo retiring '*/skills/ralf-it' and a home holding that
    orphan, under --prune --yes (quiet)
    When main runs (install-then-prune)
    Then the quiet summary's claude line reports the prune (and the orphan is
    gone) — the prune_pipeline's per-tool counters reach the renderer merged with
    the install counters.

    Pins: main merges install + prune per-target counters before rendering, so a
    --prune run's pruned tally surfaces in the summary.
    """
    repo = _hermetic_repo(tmp_path)
    toml_dir = repo / "packages" / "installer"
    toml_dir.mkdir(parents=True)
    (toml_dir / "installer.toml").write_text('[prune]\nretired = [\n  "*/skills/ralf-it",\n]\n')
    home = tmp_path / "home"
    orphan = home / ".claude" / "skills" / "ralf-it"
    orphan.mkdir(parents=True)
    io = ScriptedIO(interactive=False)

    rc = main(["--prune", "--yes", "--tools=claude"], home=home, io=io, repo_root=repo)

    assert rc == 0
    assert not orphan.exists()
    infos = [e.message for e in io.transcript if e.channel == "info"]
    assert any("claude:" in m and "pruned" in m for m in infos), infos


def test_main_dry_run_summary_reports_would_be_installs(tmp_path: Path) -> None:
    """
    Given --tools=claude --dry-run against a hermetic repo (a claude create)
    When main runs in preview mode
    Then the summary still reports the would-be install — bash tallies counters
    on a dry-run too (e.g. scripts/install.sh:1154-1160 increments
    tool_installed inside the DRY_RUN branch) and renders the Summary
    unconditionally at the end. The quiet 'claude: N installed' line appears.

    Pins: the summary renders on a dry-run with the previewed counts, matching
    bash — it is NOT gated to real writes only.
    """
    repo = _hermetic_repo(tmp_path)
    io = ScriptedIO(interactive=False)

    rc = main(["--tools=claude", "--dry-run"], home=tmp_path, io=io, repo_root=repo)

    assert rc == 0
    infos = [e.message for e in io.transcript if e.channel == "info"]
    assert any("claude:" in m and "installed" in m for m in infos), infos


def test_module_entry_point_propagates_nonzero_exit() -> None:
    """``python -m installer`` must propagate the CLI's non-zero exit code.

    Guards ``__main__.py`` against calling ``main()`` without ``sys.exit()`` —
    omitting it makes every installer error path silently report success (exit 0),
    which breaks ``set -e`` callers and CI gates. A subprocess call through the
    real entry point is the only way to verify the OS-level exit code.

    Pins: ``python -m installer --tools=bogus`` must exit 2 (the CLI's
    config-error convention, same as ``--tools=`` with an empty value or an
    unknown plugin name).
    """
    result = subprocess.run(
        [sys.executable, "-m", "installer", "--tools=bogus"],
        capture_output=True,
    )
    assert result.returncode == 2


def test_keyboard_interrupt_exits_130_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Ctrl-C during a run aborts cleanly: exit 130, a short message, no traceback.

    Pins the CLI boundary contract: a ``KeyboardInterrupt`` raised anywhere inside
    ``main`` (in practice, at an interactive overwrite prompt) is caught at the entry
    point and converted to a graceful ``Aborted.`` on stderr with exit code 130 —
    not a raw ``KeyboardInterrupt`` traceback. ``resolve_tools`` stands in as the deep
    collaborator that raises, exercising the outermost handler.
    """

    def _interrupt(**_kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr("installer.cli.resolve_tools", _interrupt)

    rc = main(["--dry-run"], home=tmp_path, repo_root=tmp_path)

    assert rc == 130
    captured = capsys.readouterr()
    assert "Aborted." in captured.err
    assert "Traceback" not in captured.err


def _repo_with_agent_collision(tmp_path: Path) -> Path:
    """A hermetic repo where a shared agent and a tool-root agent collide on the
    same dest (agents/dup.md, NAMESPACED_MD/'agents'); the registry routes that
    to the fatal strategy, so build_plan raises CollisionError during staging."""
    repo = _hermetic_repo(tmp_path)
    shared_agents = repo / "src" / "user" / ".agents" / "agents"
    shared_agents.mkdir(parents=True)
    (shared_agents / "dup.md").write_bytes(b"---\nname: dup\n---\nshared\n")
    claude_agents = repo / "src" / "user" / ".claude" / "agents"
    claude_agents.mkdir(parents=True)
    (claude_agents / "dup.md").write_bytes(b"---\nname: dup\n---\ntool\n")
    return repo


def test_main_collision_error_exits_1_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An irreconcilable merge collision during staging is surfaced as an
    actionable fatal install error (exit 1, 'installer:' on stderr), not an
    uncaught traceback out of stage_and_transform at the CLI boundary."""
    repo = _repo_with_agent_collision(tmp_path)

    rc = main(
        ["--tools=claude", "--dry-run"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=repo,
    )

    assert rc == 1
    assert "installer:" in capsys.readouterr().err


def test_main_unknown_merge_key_exits_1_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An UnknownMergeKeyError — a registry wiring miss (no strategy for a
    (kind, namespace)) — is surfaced as an actionable fatal (exit 1, 'installer:'
    on stderr) rather than an uncaught traceback. Fault-injected at the staging
    seam because the complete default_registry cannot produce this from real
    inputs; mirrors the resolve_tools fault-injection test above."""
    from installer.core.merge.registry import UnknownMergeKeyError
    from installer.core.model import FileKind

    def _raise(*_args: object, **_kwargs: object) -> object:
        raise UnknownMergeKeyError(FileKind.NAMESPACED_MD, "weird-ns")

    monkeypatch.setattr("installer.cli.stage_and_transform", _raise)

    rc = main(
        ["--tools=claude", "--dry-run"],
        home=tmp_path,
        io=ScriptedIO(interactive=False),
        repo_root=_hermetic_repo(tmp_path),
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "installer:" in err
    assert "weird-ns" in err
