"""Unit tests for ``record_receipt`` — the hoisted receipt write.

The receipt is written on every non-dry-run install (not only ``--prune``), so
the write moved out of ``prune_pipeline`` into ``record_receipt``, which the CLI
calls after install+prune inside the lock. ``record_receipt`` builds ``installed``
from the real per-item install outcomes (DECLINED excluded, real sha256) and
mirrors disk: a declined overwrite of a previously-recorded path relinquishes it,
pruned paths drop, untouched prior entries survive.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from installer.core.model import InstallOutcome, Outcome
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_store import ReadStatus, read_receipt
from installer.core.run import record_receipt


def _receipt_path(home: Path) -> Path:
    return home / ".config" / "agents-config" / "install-receipt.json"


def test_record_receipt_writes_real_outcomes_excludes_declined_drops_pruned(
    tmp_path: Path,
) -> None:
    """record_receipt mirrors disk from the real install outcomes.

    Given a prior recording an untouched entry, a pruned entry, and a path that
    this run declined; and tool outcomes with one WRITTEN file (real sha256) and
    one DECLINED file that IS in prior:
    - the WRITTEN entry is recorded with its sha256,
    - the DECLINED-of-recorded path is relinquished (excluded),
    - the pruned path is dropped,
    - the untouched prior entry survives.
    """
    home = tmp_path
    dest_root = home / ".claude"
    receipt_path = _receipt_path(home)

    written_bytes = b"new rule\n"
    written_sha = hashlib.sha256(written_bytes).hexdigest()

    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(
            # untouched — survives
            ReceiptEntry(Path(".claude/skills/untouched"), "claude", Path(".claude"), "dir", None),
            # pruned this run — dropped
            ReceiptEntry(Path(".claude/skills/gone"), "claude", Path(".claude"), "dir", None),
            # declined overwrite of a recorded path — relinquished
            ReceiptEntry(
                Path(".claude/rules/declined.md"), "claude", Path(".claude"), "file", "ab"
            ),
        ),
    )

    tool_outcomes = {
        "claude": [
            InstallOutcome(dest_root / "rules" / "new.md", Outcome.WRITTEN, written_sha),
            InstallOutcome(dest_root / "rules" / "declined.md", Outcome.DECLINED, None),
        ]
    }

    record_receipt(
        receipt_path,
        prior=prior,
        dest_roots={"claude": dest_root},
        home=home,
        tool_outcomes=tool_outcomes,
        plugin_outcomes={},
        pruned_paths={Path(".claude/skills/gone")},
        relinquished_paths=set(),
    )

    read = read_receipt(receipt_path)
    assert read.status is ReadStatus.OK
    assert read.receipt is not None
    by_path = {e.path: e for e in read.receipt.entries}

    # WRITTEN entry recorded with real sha256
    assert Path(".claude/rules/new.md") in by_path
    assert by_path[Path(".claude/rules/new.md")].sha256 == written_sha
    # DECLINED-of-recorded path relinquished
    assert Path(".claude/rules/declined.md") not in by_path
    # pruned path dropped
    assert Path(".claude/skills/gone") not in by_path
    # untouched prior entry survives
    assert Path(".claude/skills/untouched") in by_path


def test_record_receipt_includes_plugin_route_outcomes(tmp_path: Path) -> None:
    """A plugin route's WRITTEN outcome is recorded owned by the plugin name."""
    home = tmp_path
    receipt_path = _receipt_path(home)
    formula_bytes = b"formula\n"
    sha = hashlib.sha256(formula_bytes).hexdigest()

    plugin_outcomes = {
        "beads": [
            InstallOutcome(home / ".beads" / "formulas" / "a.toml", Outcome.WRITTEN, sha),
        ]
    }

    record_receipt(
        receipt_path,
        prior=Receipt(),
        dest_roots={"claude": home / ".claude"},
        home=home,
        tool_outcomes={},
        plugin_outcomes=plugin_outcomes,
        pruned_paths=set(),
        relinquished_paths=set(),
    )

    read = read_receipt(receipt_path)
    assert read.receipt is not None
    by_path = {e.path: e for e in read.receipt.entries}
    entry = by_path[Path(".beads/formulas/a.toml")]
    assert entry.owner == "beads"
    assert entry.root == Path(".beads")
    assert entry.sha256 == sha
