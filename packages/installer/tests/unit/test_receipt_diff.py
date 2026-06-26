from pathlib import Path

from installer.core.model import Orphan
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_diff import diff_orphans


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
