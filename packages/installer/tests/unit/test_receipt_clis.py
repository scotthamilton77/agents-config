"""Tests for the additive Receipt.clis field."""

import json
from pathlib import Path

from installer.core.receipt import CliReceiptEntry, Receipt, canonical_bytes, compute_integrity
from installer.core.receipt_build import merge_clis
from installer.core.receipt_store import ReadStatus, read_receipt, write_receipt

_ENTRY = CliReceiptEntry(name="workcli", binary="work", digest="sha256:ab")


def test_clis_round_trip(tmp_path: Path) -> None:
    """
    Given a receipt with one clis entry
    When written and re-read
    Then status is OK and the entry survives intact.

    Pins that receipt_store round-trips the field.
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

    Pins that canonical_bytes includes "clis" only when non-empty, so a
    legacy receipt hashes byte-identically.
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

    Pins the omit-when-empty rule.
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

    Pins that the fail-closed type check in
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


def _e(name: str, digest: str = "sha256:aa") -> CliReceiptEntry:
    return CliReceiptEntry(name=name, binary=name[0:4], digest=digest)


def test_merge_clis_union_rule() -> None:
    """
    Given prior entries {workcli, oldtool} and registry {workcli, prgroom}
    When this run deployed prgroom and uninstalled oldtool
    Then the merge keeps workcli's prior entry (skip retains), adds
    prgroom's new entry, and drops oldtool.

    Pins the union merge rule (registry -> new-if-deployed else
    retained; non-registry -> dropped iff uninstalled).
    """
    merged = merge_clis(
        prior_clis=(_e("workcli"), _e("oldtool")),
        registry_names=frozenset({"workcli", "prgroom"}),
        deployed={"prgroom": _e("prgroom", "sha256:new")},
        uninstalled_names={"oldtool"},
        relinquished_names=set(),
    )
    assert {c.name for c in merged} == {"workcli", "prgroom"}
    assert next(c for c in merged if c.name == "prgroom").digest == "sha256:new"


def test_merge_clis_declined_uninstall_retained_foreign_relinquished() -> None:
    """
    Given a retired entry whose uninstall was declined and a foreign entry
    When merged
    Then the declined one is retained (retried next prune) and the
    relinquished foreign one is dropped without uninstall.

    Pins the decline-retains / foreign-names-relinquished rule.
    """
    merged = merge_clis(
        prior_clis=(_e("oldtool"), _e("ruff")),
        registry_names=frozenset({"workcli"}),
        deployed={},
        uninstalled_names=set(),
        relinquished_names={"ruff"},
    )
    assert {c.name for c in merged} == {"oldtool"}
