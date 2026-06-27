import json
from pathlib import Path

from installer.core.receipt import Receipt, ReceiptEntry, compute_integrity
from installer.core.receipt_store import ReadStatus, read_receipt, to_json_obj, write_receipt


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


def test_directory_at_receipt_path_is_corrupt(tmp_path: Path) -> None:
    # Present-but-unusable: a directory sits where the receipt should be.
    # Treating it as MISSING would later crash write_receipt()'s replace().
    path = tmp_path / "install-receipt.json"
    path.mkdir()
    result = read_receipt(path)
    assert result.status is ReadStatus.CORRUPT
    assert result.receipt is None


def test_broken_symlink_at_receipt_path_is_corrupt(tmp_path: Path) -> None:
    # A dangling symlink exists (is_symlink True) but resolves to nothing
    # (is_file/exists False) -> present-but-unusable -> CORRUPT, not MISSING.
    path = tmp_path / "install-receipt.json"
    path.symlink_to(tmp_path / "nonexistent-target.json")
    result = read_receipt(path)
    assert result.status is ReadStatus.CORRUPT
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


# ── kind<->sha256 coupling guard. These write the malformed entry with a
# *matching* integrity digest (stamped over the malformed content via
# compute_integrity), so the integrity check passes and the only thing that can
# trip CORRUPT is the new kind/sha guard in _entry_from_json — not an integrity
# mismatch. Without the guard these would read OK, so each test pins the guard.


def _write_with_valid_integrity(path: Path, entry: ReceiptEntry) -> None:
    receipt = Receipt(roots=(Path(".claude"),), entries=(entry,))
    doc = to_json_obj(receipt)
    doc["integrity"] = compute_integrity(receipt)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_file_entry_with_null_sha256_is_corrupt(tmp_path: Path) -> None:
    # A file entry whose sha256 is null defeats hash-aware relinquishment in
    # prune_hash (the file is deleted instead of kept) -> fail closed.
    path = tmp_path / "install-receipt.json"
    entry = ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", None)
    _write_with_valid_integrity(path, entry)
    # Integrity matches the malformed content, so CORRUPT can only come from the
    # kind/sha guard.
    assert (
        compute_integrity(Receipt(roots=(Path(".claude"),), entries=(entry,)))
        == json.loads(path.read_text(encoding="utf-8"))["integrity"]
    )
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_dir_entry_with_non_null_sha256_is_corrupt(tmp_path: Path) -> None:
    # A dir entry carrying a digest contradicts the v1 schema (dirs are null).
    path = tmp_path / "install-receipt.json"
    entry = ReceiptEntry(Path(".claude/rules"), "claude", Path(".claude"), "dir", "ab")
    _write_with_valid_integrity(path, entry)
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_well_formed_file_and_dir_entries_read_ok(tmp_path: Path) -> None:
    # Regression guard: the tightening is narrow — a file-with-sha and a
    # dir-with-null entry together still read OK.
    path = tmp_path / "install-receipt.json"
    write_receipt(
        path,
        Receipt(
            roots=(Path(".claude"),),
            entries=(
                ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path(".claude"), "file", "ab"),
                ReceiptEntry(Path(".claude/rules"), "claude", Path(".claude"), "dir", None),
            ),
        ),
    )
    assert read_receipt(path).status is ReadStatus.OK


# ── string-type guards on path/owner/root and roots elements. Without the guard
# a JSON number in one of these fields ``str()``-coerces to a value whose
# canonical form equals the string the integrity was stamped over, so the digest
# MATCHES and the receipt reads OK. Each test writes the integrity stamped over
# that coerced form (``compute_integrity`` of the coerced ``Receipt``), so the
# ONLY thing that can trip CORRUPT is the new isinstance guard — not a digest
# mismatch. Without the guard these would read OK.


def test_entry_with_non_string_path_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    coerced = Receipt(
        roots=(Path(".claude"),),
        entries=(ReceiptEntry(Path("123"), "claude", Path(".claude"), "file", "ab"),),
    )
    doc = {
        "schema_version": 1,
        "integrity": compute_integrity(coerced),
        "roots": [".claude"],
        "entries": [
            {"path": 123, "owner": "claude", "root": ".claude", "kind": "file", "sha256": "ab"}
        ],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    # The stamped integrity matches the coerced receipt, so CORRUPT can only come
    # from the string-type guard, not a digest mismatch.
    assert doc["integrity"] == compute_integrity(coerced)
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_entry_with_non_string_owner_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    coerced = Receipt(
        roots=(Path(".claude"),),
        entries=(ReceiptEntry(Path(".claude/rules/x.md"), "123", Path(".claude"), "file", "ab"),),
    )
    doc = {
        "schema_version": 1,
        "integrity": compute_integrity(coerced),
        "roots": [".claude"],
        "entries": [
            {
                "path": ".claude/rules/x.md",
                "owner": 123,
                "root": ".claude",
                "kind": "file",
                "sha256": "ab",
            }
        ],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_entry_with_non_string_root_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    coerced = Receipt(
        roots=(Path(".claude"),),
        entries=(ReceiptEntry(Path(".claude/rules/x.md"), "claude", Path("123"), "file", "ab"),),
    )
    doc = {
        "schema_version": 1,
        "integrity": compute_integrity(coerced),
        "roots": [".claude"],
        "entries": [
            {
                "path": ".claude/rules/x.md",
                "owner": "claude",
                "root": 123,
                "kind": "file",
                "sha256": "ab",
            }
        ],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_non_string_roots_element_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    coerced = Receipt(roots=(Path("123"),), entries=())
    doc = {
        "schema_version": 1,
        "integrity": compute_integrity(coerced),
        "roots": [123],
        "entries": [],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_dir_entry_with_digest_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    receipt = Receipt(
        entries=(
            ReceiptEntry(
                Path(".claude/skills/foo"),
                "claude",
                Path(".claude"),
                "dir",
                None,
                dir_digest="sha256:deadbeef",
            ),
        )
    )
    write_receipt(path, receipt)
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    assert result.receipt.entries[0].dir_digest == "sha256:deadbeef"


def test_legacy_dir_entry_without_digest_still_validates(tmp_path: Path) -> None:
    # A dir entry carrying no digest (what pre-feature installs wrote) must read OK:
    # dir_digest is omitted from both the JSON and the canonical integrity bytes, so
    # the persisted digest still matches — no SCHEMA_VERSION bump, no forced reinstall.
    path = tmp_path / "install-receipt.json"
    write_receipt(
        path,
        Receipt(
            entries=(
                ReceiptEntry(Path(".claude/skills/foo"), "claude", Path(".claude"), "dir", None),
            )
        ),
    )
    assert "dir_digest" not in path.read_text(encoding="utf-8")
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None
    assert result.receipt.entries[0].dir_digest is None


def test_file_entry_carrying_dir_digest_is_corrupt(tmp_path: Path) -> None:
    # dir_digest on a file entry is schema-invalid -> CORRUPT (fail closed). The
    # entry validator rejects it before integrity is even checked.
    path = tmp_path / "install-receipt.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrity": "sha256:whatever",
                "roots": [],
                "entries": [
                    {
                        "path": ".claude/rules/x.md",
                        "owner": "claude",
                        "root": ".claude",
                        "kind": "file",
                        "sha256": "ab",
                        "dir_digest": "sha256:nope",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert read_receipt(path).status is ReadStatus.CORRUPT


def test_non_string_dir_digest_is_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "install-receipt.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrity": "sha256:whatever",
                "roots": [],
                "entries": [
                    {
                        "path": ".claude/skills/foo",
                        "owner": "claude",
                        "root": ".claude",
                        "kind": "dir",
                        "sha256": None,
                        "dir_digest": 123,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert read_receipt(path).status is ReadStatus.CORRUPT
