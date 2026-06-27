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


# ── Parse-time schema validation -> CORRUPT (runs before the integrity check).
# Each writes a JSON-parseable but schema-invalid receipt directly (NOT via
# write_receipt, which would stamp a valid digest) so the malformed shape reaches
# _receipt_from_json / _entry_from_json. The receipt-as-empty fallback that these
# protect is the fail-closed guarantee for a feature that deletes files.


def _good_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "path": ".claude/rules/x.md",
        "owner": "claude",
        "root": ".claude",
        "kind": "file",
        "sha256": "ab",
    }
    entry.update(overrides)
    return entry


def _write_raw(path: Path, *, entries: object, **top: object) -> None:
    doc: dict[str, object] = {
        "schema_version": 1,
        "integrity": "sha256:deadbeef",
        "roots": [".claude"],
        "entries": entries,
    }
    doc.update(top)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_entry_with_bad_kind_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    _write_raw(path, entries=[_good_entry(kind="symlink")])
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_entry_with_non_string_sha256_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    _write_raw(path, entries=[_good_entry(sha256=123)])  # number, not string|null
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_roots_not_a_list_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    _write_raw(path, entries=[], roots=".claude")  # string, not list
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_unsupported_schema_version_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    _write_raw(path, entries=[], schema_version=999)
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_non_object_entry_element_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    _write_raw(path, entries=["not-an-object"])
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_top_level_not_an_object_is_corrupt(tmp_path: Path) -> None:
    """A receipt whose top-level JSON parses to a non-object (here a list) is
    CORRUPT — the document shape itself is wrong, before any field is read.
    """
    path = tmp_path / "install-receipt.json"
    path.write_text(json.dumps(["not", "a", "receipt"]), encoding="utf-8")
    assert read_receipt(path).status is ReadStatus.CORRUPT
