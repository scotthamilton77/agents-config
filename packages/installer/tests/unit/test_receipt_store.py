from pathlib import Path

from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    receipt = Receipt(
        roots=(Path(".claude"),),
        entries=(
            ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", "ab"),
        ),
    )
    write_receipt(path, receipt)
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    assert result.receipt.entries[0].path == Path(".claude/rules/x.md")
    assert result.receipt.roots == (Path(".claude"),)


def test_missing_file_is_missing(tmp_path: Path) -> None:
    result = read_receipt(tmp_path / "absent.json")
    assert result.status is ReadStatus.MISSING
    assert result.receipt is None


def test_unparseable_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    path.write_text("{ this is not json", encoding="utf-8")
    result = read_receipt(path)
    assert result.status is ReadStatus.CORRUPT
    assert result.receipt is None
