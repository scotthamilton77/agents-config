"""Read/write the install receipt with missing-vs-corrupt distinction.

Read never raises on bad data: a missing file is ``MISSING`` (bootstrap empty),
anything present-but-unusable is ``CORRUPT`` (fail closed). Write is atomic
(temp file + ``os.replace``) and stamps the integrity digest; read verifies it,
so a missing or mismatched digest reads as ``CORRUPT``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from installer.core.receipt import SCHEMA_VERSION, Receipt, ReceiptEntry, compute_integrity


class ReadStatus(Enum):
    MISSING = "missing"
    CORRUPT = "corrupt"
    OK = "ok"


@dataclass(frozen=True, slots=True)
class ReceiptRead:
    status: ReadStatus
    receipt: Receipt | None


def _entry_to_json(e: ReceiptEntry) -> dict[str, object]:
    return {
        "path": str(e.path),
        "owner": e.owner,
        "root": str(e.root),
        "kind": e.kind,
        "sha256": e.sha256,
    }


def _entry_from_json(d: object) -> ReceiptEntry:
    if not isinstance(d, dict):
        raise ValueError("entry is not an object")  # noqa: TRY003, TRY004  # caught -> CORRUPT; subclass not justified
    kind = d["kind"]
    if kind not in ("file", "dir"):
        raise ValueError(f"bad kind {kind!r}")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    sha = d["sha256"]
    if sha is not None and not isinstance(sha, str):
        raise ValueError("sha256 must be string or null")  # noqa: TRY003  # caught -> CORRUPT; subclass not justified
    return ReceiptEntry(
        path=Path(str(d["path"])),
        owner=str(d["owner"]),
        root=Path(str(d["root"])),
        kind=kind,
        sha256=sha,
    )


def to_json_obj(receipt: Receipt) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "integrity": receipt.integrity,
        "roots": [str(r) for r in receipt.roots],
        "entries": [_entry_to_json(e) for e in receipt.entries],
    }


def _receipt_from_json(data: object) -> Receipt:
    if not isinstance(data, dict):
        raise ValueError("receipt is not an object")  # noqa: TRY003, TRY004  # caught -> CORRUPT; subclass not justified
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    roots_raw = data.get("roots", [])
    entries_raw = data.get("entries", [])
    if not isinstance(roots_raw, list) or not isinstance(entries_raw, list):
        raise ValueError("roots/entries must be lists")  # noqa: TRY003, TRY004  # caught -> CORRUPT; subclass not justified
    return Receipt(
        schema_version=SCHEMA_VERSION,
        roots=tuple(Path(str(r)) for r in roots_raw),
        entries=tuple(_entry_from_json(e) for e in entries_raw),
        integrity=(str(data["integrity"]) if data.get("integrity") is not None else None),
    )


def read_receipt(path: Path) -> ReceiptRead:
    if not path.is_file():
        # Truly absent (no path, no broken symlink) bootstraps empty -> MISSING.
        # A present-but-wrong-type path (dir, broken symlink, device) is
        # present-but-unusable -> CORRUPT, so the caller fails closed instead
        # of crashing later when write_receipt() tries to replace() it.
        if not path.exists() and not path.is_symlink():
            return ReceiptRead(ReadStatus.MISSING, None)
        return ReceiptRead(ReadStatus.CORRUPT, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        receipt = _receipt_from_json(data)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return ReceiptRead(ReadStatus.CORRUPT, None)
    if receipt.integrity is None or receipt.integrity != compute_integrity(receipt):
        return ReceiptRead(ReadStatus.CORRUPT, None)
    return ReceiptRead(ReadStatus.OK, receipt)


def write_receipt(path: Path, receipt: Receipt) -> None:
    stamped = replace(receipt, integrity=compute_integrity(receipt))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_json_obj(stamped), indent=2, sort_keys=False), encoding="utf-8")
    tmp.replace(path)
