"""Hook commands in the deployed settings point at the scripts the same run placed.

Claude Code exposes no config-root variable to a hook command (nothing analogous
to ``CLAUDE_PLUGIN_ROOT``), so the destination home has to be resolved at install
time. These tests pin that resolution against the REAL source tree, because the
coupling being protected is between two real files: the hook commands in
``src/user/.claude/settings.json.template`` and the scripts in
``src/user/.claude/hooks/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from installer.cli import main

_REPO_ROOT = Path(__file__).resolve().parents[4]
_HOOKS_SOURCE = _REPO_ROOT / "src" / "user" / ".claude" / "hooks"


def _hook_commands(settings: dict[str, Any]) -> list[str]:
    """Every hook ``command`` string in a settings payload, across all events."""
    return [
        hook["command"]
        for matchers in settings["hooks"].values()
        for matcher in matchers
        for hook in matcher["hooks"]
    ]


def _dump_claude_settings(home: Path, out: Path) -> dict[str, Any]:
    """Stage the real source tree for the given home and read the settings it
    would deploy. ``--dump-stage`` materialises the plan and writes nothing under
    ``home``, so this observes the install without performing one."""
    rc = main([f"--dump-stage={out}", "--tools=claude"], home=home, repo_root=_REPO_ROOT)
    assert rc == 0
    return json.loads((out / "claude" / "settings.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_hook_commands_resolve_under_the_home_the_run_installs_into(tmp_path: Path) -> None:
    """
    Given a run anchored on a home that is not the user's own
    When the Claude plan is staged
    Then every hook command names a script under THAT home, not under `~`.
    """
    home = tmp_path / "other-home"
    home.mkdir()

    settings = _dump_claude_settings(home, tmp_path / "dump")

    commands = _hook_commands(settings)
    assert commands, "the template ships hook commands"
    for command in commands:
        script = command.split(" ", 1)[1]
        assert script.startswith(f"{home}/.claude/hooks/"), command


def test_default_home_hook_commands_run_the_deployed_scripts(tmp_path: Path) -> None:
    """
    Given a run anchored on the user's own home
    When the Claude plan is staged
    Then every hook command invokes `~/.claude/hooks/<script>.py` — the shell's
    spelling of that home — and each named script is one this install deploys.
    """
    settings = _dump_claude_settings(Path.home(), tmp_path / "dump")

    commands = _hook_commands(settings)
    assert commands, "the template ships hook commands"
    for command in commands:
        script = command.removeprefix("python3 ~/.claude/hooks/")
        assert script != command, command
        assert (_HOOKS_SOURCE / script).is_file(), command
