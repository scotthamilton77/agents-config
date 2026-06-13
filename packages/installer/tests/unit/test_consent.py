"""Unit tests for installer.core.consent (G.7 — non-interactive consent guard).

Pins the installer-level guard the Python rewrite adds: a run that cannot prompt
(stdin not a TTY) and has not been waived by ``--yes`` or ``--dry-run`` must hard
fail with a clear error rather than silently make destructive changes. ``--yes``
or ``--dry-run`` stand in for consent, so the guard does not trigger then.

The guard is driven through ``ScriptedIO`` (its ``is_interactive`` flag is the
TTY probe) and asserted on its raise/no-raise behaviour — the actual coded
decision, not the stdlib ``sys.stdin.isatty``.
"""

from __future__ import annotations

import pytest

from installer.core.consent import ConsentRequiredError, require_consent


def test_non_interactive_without_waiver_raises() -> None:
    """
    Given a non-interactive session, not dry_run, not auto_yes
    When require_consent runs
    Then it raises ConsentRequiredError (no way to confirm destructive writes).
    """
    from installer.core.io_port import ScriptedIO

    with pytest.raises(ConsentRequiredError):
        require_consent(ScriptedIO(interactive=False), dry_run=False, auto_yes=False)


def test_non_interactive_with_auto_yes_does_not_raise() -> None:
    """
    Given a non-interactive session waived by auto_yes
    When require_consent runs
    Then it returns without raising (the scripted-install path).
    """
    from installer.core.io_port import ScriptedIO

    require_consent(ScriptedIO(interactive=False), dry_run=False, auto_yes=True)


def test_non_interactive_with_dry_run_does_not_raise() -> None:
    """
    Given a non-interactive session waived by dry_run
    When require_consent runs
    Then it returns without raising (dry-run touches nothing).
    """
    from installer.core.io_port import ScriptedIO

    require_consent(ScriptedIO(interactive=False), dry_run=True, auto_yes=False)


def test_interactive_session_does_not_raise() -> None:
    """
    Given an interactive session (a TTY can answer prompts)
    When require_consent runs with no waiver
    Then it returns without raising.
    """
    from installer.core.io_port import ScriptedIO

    require_consent(ScriptedIO(interactive=True), dry_run=False, auto_yes=False)
