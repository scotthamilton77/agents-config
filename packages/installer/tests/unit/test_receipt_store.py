import json
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


def test_written_receipt_carries_integrity_and_reads_ok(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    write_receipt(
        path,
        Receipt(
            entries=(
                ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", "ab"),
            )
        ),
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw["integrity"], str) and raw["integrity"].startswith("sha256:")
    assert read_receipt(path).status is ReadStatus.OK


def test_tampered_entry_without_redigest_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    write_receipt(
        path,
        Receipt(
            entries=(
                ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", "ab"),
            )
        ),
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["entries"].append(
        {
            "path": ".claude/rules/EVIL.md",
            "owner": "claude",
            "root": ".claude",
            "kind": "file",
            "sha256": "zz",
        }
    )
    path.write_text(json.dumps(raw), encoding="utf-8")  # integrity now stale
    result = read_receipt(path)
    assert result.status is ReadStatus.CORRUPT
    assert result.receipt is None


def test_missing_integrity_field_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    path.write_text(
        json.dumps({"schema_version": 1, "integrity": None, "roots": [".claude"], "entries": []}),
        encoding="utf-8",
    )
    assert read_receipt(path).status is ReadStatus.CORRUPT
