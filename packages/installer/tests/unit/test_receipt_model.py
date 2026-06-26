from pathlib import Path

from installer.core.receipt import Receipt, ReceiptEntry


def test_entry_is_frozen_and_carries_fields() -> None:
    e = ReceiptEntry(
        path=Path(".claude/skills/foo"),
        owner="claude",
        root=Path(".claude"),
        kind="dir",
        sha256=None,
    )
    assert e.path == Path(".claude/skills/foo")
    assert e.owner == "claude"
    assert e.root == Path(".claude")
    assert e.kind == "dir"
    assert e.sha256 is None


def test_receipt_holds_schema_roots_and_entries() -> None:
    r = Receipt(schema_version=1, roots=(Path(".beads"),), entries=())
    assert r.schema_version == 1
    assert r.roots == (Path(".beads"),)
    assert r.entries == ()
