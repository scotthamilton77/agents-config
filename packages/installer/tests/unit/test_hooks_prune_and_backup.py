"""End-to-end pins for hooks joining the prune-tracked, sibling-backed-up
namespaces (``namespaces.PRUNE`` / ``namespaces.BACKUP``).

Before this fix, a hooks item was staged and deployed (``TOOL_SCOPED``) but
never receipt-recorded and never sibling-backed-up: ``entries_from_outcomes``
dropped every hooks write (namespace not in ``PRUNE_NAMESPACES``), so a
removed-source hook had no receipt entry to trigger its deletion, and an
overwritten hook's prior bytes landed as an in-place ``<name>.backup-<ts>``
sibling instead of a recoverable ``hooks-backup/`` dir. Mirrors
test_workflows_namespace.py, the reference fix for the identical gap.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.backup import back_up
from installer.core.hashing import sha256_file
from installer.core.io_port import ScriptedIO
from installer.core.model import InstallOutcome, Outcome, StagingPlan, Tool
from installer.core.receipt import Receipt
from installer.core.receipt_build import entries_from_outcomes
from installer.core.run import prune_pipeline
from installer.core.sync import sync
from installer.tools.claude import ClaudeAdapter
from installer.tools.registry import get_adapter

_TS = "20250101-120000"


def _claude_home(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def test_hook_with_removed_source_is_pruned_on_next_install(tmp_path: Path) -> None:
    """A hook recorded in a prior receipt, whose source has since been removed,
    is pruned from the home on the next install.

    Builds the prior receipt via ``entries_from_outcomes`` — the real recording
    path a full install run uses — rather than hand-authoring a ``ReceiptEntry``,
    so the test actually exercises the namespace-membership gate this fix closes.
    Before the fix, ``entries_from_outcomes`` drops the hooks write (namespace
    not in ``PRUNE_NAMESPACES``), so ``prior.entries`` never gets an entry for it,
    no orphan is ever detected, and the hook survives; after the fix the entry is
    recorded and the now-sourceless hook is diffed out and deleted.
    """
    home = _claude_home(tmp_path)
    hook_path = home / ".claude" / "hooks" / "old-hook.py"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_bytes(b"#!/usr/bin/env python3\n")

    # The recorded sha256 must match the on-disk bytes: prune_hash's bytes-match
    # guard relinquishes (keeps) a file orphan whose recorded hash disagrees with
    # what is actually on disk, so a mismatched hash here would make this test
    # pass for the wrong reason (relinquished, not pruned).
    outcomes = [InstallOutcome(hook_path, Outcome.WRITTEN, sha256_file(hook_path).hex())]
    entries = entries_from_outcomes(outcomes, tool="claude", dest_root=home / ".claude", home=home)
    prior = Receipt(roots=(Path(".claude"),), entries=tuple(entries))

    # Next install: the hook's source has been removed, so this run's plan no
    # longer stages it.
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not hook_path.exists()
    assert outcome.pruned_paths == {Path(".claude/hooks/old-hook.py")}


def test_overwritten_hook_backs_up_to_sibling_hooks_backup_dir(tmp_path: Path) -> None:
    """Overwriting a deployed hook places the previous content in a sibling
    ``hooks-backup/`` directory rather than an in-place ``.backup-<ts>`` suffix
    next to the live hook.
    """
    repo_root = tmp_path / "repo"
    home = tmp_path / "home"
    source = repo_root / "src" / "user" / ".claude" / "hooks" / "ruff-postedit.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"new content\n")

    dest = home / ".claude" / "hooks" / "ruff-postedit.py"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old content\n")

    counters = sync(
        ClaudeAdapter(),
        Path("hooks/ruff-postedit.py"),
        repo_root=repo_root,
        home=home,
        io=ScriptedIO(),
        timestamp=_TS,
    )

    backup = home / ".claude" / "hooks-backup" / f"ruff-postedit.py.backup-{_TS}"
    assert backup.read_bytes() == b"old content\n"
    assert dest.read_bytes() == b"new content\n"
    assert counters.backed_up == 1


def test_back_up_routes_a_hooks_target_to_the_sibling_dir(tmp_path: Path) -> None:
    """Unit-level companion to the sync test above: ``back_up`` itself routes a
    hooks-namespace target to the sibling ``hooks-backup/`` dir, exercised
    directly (no sync/staging machinery) the way test_backup.py pins the other
    backup-routed namespaces.
    """
    target = tmp_path / ".claude" / "hooks" / "retired.py"
    target.parent.mkdir(parents=True)
    target.write_text("precious")

    dest = back_up(target, _TS)

    assert dest == tmp_path / ".claude" / "hooks-backup" / f"retired.py.backup-{_TS}"
    assert dest.read_text() == "precious"


def test_hook_present_but_recorded_in_no_receipt_is_left_alone(tmp_path: Path) -> None:
    """A hook file that is physically present in the home, but recorded in no
    receipt at all (hand-placed, or from before receipts existed), is never
    swept up by hooks joining the prune-eligible namespaces — pruning only ever
    acts on a recorded orphan, never on undocumented content it finds on disk.
    """
    home = _claude_home(tmp_path)
    stray = home / ".claude" / "hooks" / "hand-placed.py"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"#!/usr/bin/env python3\n")

    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=Receipt(),  # no receipt entries at all
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert stray.exists()
    assert outcome.pruned_paths == set()
