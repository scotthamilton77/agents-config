from pathlib import Path

from installer.core.model import Orphan
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_diff import diff_orphans, scope_owners


def _entry(path: str, owner: str, root: str, kind: str = "file") -> ReceiptEntry:
    return ReceiptEntry(Path(path), owner, Path(root), kind, None)  # type: ignore[arg-type]


def test_dropped_entry_becomes_orphan() -> None:
    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(
            _entry(".claude/skills/keep", "claude", ".claude", "dir"),
            _entry(".claude/skills/drop", "claude", ".claude", "dir"),
        ),
    )
    desired = {("claude", Path(".claude/skills/keep"))}
    orphans = diff_orphans(
        prior,
        desired_keys=desired,
        scope_owners={"claude"},
        home=Path("/home/u"),
    )
    assert [o.path for o in orphans] == [Path("/home/u/.claude/skills/drop")]
    assert orphans[0].tool == "claude"
    assert isinstance(orphans[0], Orphan)


def test_untargeted_owner_is_untouched() -> None:
    prior = Receipt(
        roots=(Path(".codex"),),
        entries=(_entry(".codex/skills/x", "codex", ".codex", "dir"),),
    )
    orphans = diff_orphans(prior, desired_keys=set(), scope_owners={"claude"}, home=Path("/home/u"))
    assert orphans == []


def test_scope_includes_retired_plugin_excludes_untargeted_tool() -> None:
    prior = Receipt(
        entries=(
            _entry(".beads/formulas/old.toml", "beads", ".beads"),
            _entry(".codex/skills/x", "codex", ".codex", "dir"),
        )
    )
    owners = scope_owners({"claude"}, set(), prior)
    assert "claude" in owners  # resolved tool
    assert "beads" in owners  # retired plugin owner (not a tool name)
    assert "codex" not in owners  # untargeted tool -> preserved


def test_scope_includes_discovered_plugin() -> None:
    assert scope_owners({"claude"}, {"beads"}, Receipt()) == {"claude", "beads"}


def test_retired_plugin_entry_is_orphaned_when_in_scope() -> None:
    prior = Receipt(entries=(_entry(".beads/formulas/old.toml", "beads", ".beads"),))
    owners = scope_owners(set(), {"beads"}, prior)
    orphans = diff_orphans(prior, desired_keys=set(), scope_owners=owners, home=Path("/home/u"))
    assert [o.path for o in orphans] == [Path("/home/u/.beads/formulas/old.toml")]
    assert orphans[0].tool == "beads"
