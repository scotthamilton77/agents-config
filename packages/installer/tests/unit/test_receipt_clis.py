"""Tests for the additive Receipt.clis field (spec §7, item 11)."""

import json
from pathlib import Path

from installer.core.receipt import CliReceiptEntry, Receipt, canonical_bytes, compute_integrity
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt

_ENTRY = CliReceiptEntry(name="workcli", binary="work", digest="sha256:ab")


def test_clis_round_trip(tmp_path: Path) -> None:
    """
    Given a receipt with one clis entry
    When written and re-read
    Then status is OK and the entry survives intact.

    Pins spec §7 / item 11: receipt_store round-trips the field.
    """
    path = tmp_path / "install-receipt.json"
    write_receipt(path, Receipt(clis=(_ENTRY,)))
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None and result.receipt.clis == (_ENTRY,)


def test_legacy_receipt_without_clis_still_validates(tmp_path: Path) -> None:
    """
    Given a receipt written before the clis field existed
    When read by the new code
    Then it reads OK (integrity still validates) with clis == ().

    Pins spec §7: canonical_bytes includes "clis" only when non-empty, so a
    legacy receipt hashes byte-identically (item 11).
    """
    path = tmp_path / "install-receipt.json"
    legacy = Receipt()  # no clis
    write_receipt(path, legacy)
    raw = json.loads(path.read_text())
    assert "clis" not in raw  # emitted only when non-empty
    result = read_receipt(path)
    assert result.status is ReadStatus.OK
    assert result.receipt is not None and result.receipt.clis == ()


def test_empty_clis_hashes_identically_to_absent() -> None:
    """
    Given two receipts, one default and one with explicit empty clis
    When canonical_bytes runs
    Then the bytes are identical (no integrity break for legacy receipts).

    Pins spec §7 omit-when-empty.
    """
    assert canonical_bytes(Receipt()) == canonical_bytes(Receipt(clis=()))
    assert compute_integrity(Receipt()) == compute_integrity(Receipt(clis=()))


def test_malformed_clis_entry_reads_corrupt(tmp_path: Path) -> None:
    """
    Given a receipt whose clis entry has a non-string digest, with integrity
    restamped as a coercing (non-validating) reader would have computed it
    When read
    Then status is CORRUPT (fail closed — only the clis type validation can
    produce this, since the restamped integrity MATCHES the coerced value).

    Pins spec §7 validation / item 11: the fail-closed type check in
    _cli_entry_from_json — not a stale integrity — is what rejects the entry.
    """
    path = tmp_path / "install-receipt.json"
    write_receipt(path, Receipt(clis=(_ENTRY,)))
    raw = json.loads(path.read_text())
    raw["clis"][0]["digest"] = 42
    # Restamp integrity as a coercing (non-validating) reader would compute it:
    # digest 42 coerced to "42" makes integrity MATCH, so the ONLY thing that
    # can flag CORRUPT is the fail-closed type validation itself. (The coerced
    # receipt mirrors the persisted one — default roots/entries, digest coerced.)
    coerced = Receipt(clis=(CliReceiptEntry(name=_ENTRY.name, binary=_ENTRY.binary, digest="42"),))
    raw["integrity"] = compute_integrity(coerced)
    path.write_text(json.dumps(raw))
    assert read_receipt(path).status is ReadStatus.CORRUPT
