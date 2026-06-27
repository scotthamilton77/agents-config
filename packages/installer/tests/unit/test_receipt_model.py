from pathlib import Path

from installer.core.receipt import Receipt, ReceiptEntry, compute_integrity


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


def test_integrity_is_independent_of_roots_order() -> None:
    # roots is conceptually a set/allowlist; differing tuple order for the same
    # set of roots must not change the integrity digest (else false CORRUPT).
    a = Receipt(roots=(Path(".claude"), Path(".beads")), entries=())
    b = Receipt(roots=(Path(".beads"), Path(".claude")), entries=())
    assert compute_integrity(a) == compute_integrity(b)


def test_dir_content_digest_changes_when_file_added_or_removed(tmp_path: Path) -> None:
    from installer.core.receipt import dir_content_digest

    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("alpha")
    base = dir_content_digest(d)
    (d / "b.txt").write_text("beta")
    with_added = dir_content_digest(d)
    assert with_added != base
    (d / "b.txt").unlink()
    assert dir_content_digest(d) == base
