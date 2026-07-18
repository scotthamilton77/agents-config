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

from installer.core.receipt import (
    SCHEMA_VERSION,
    CliReceiptEntry,
    Receipt,
    ReceiptEntry,
    compute_integrity,
)


class ReadStatus(Enum):
    MISSING = "missing"
    CORRUPT = "corrupt"
    OK = "ok"


@dataclass(frozen=True, slots=True)
class ReceiptRead:
    status: ReadStatus
    receipt: Receipt | None


def _entry_to_json(e: ReceiptEntry) -> dict[str, object]:
    out: dict[str, object] = {
        "path": str(e.path),
        "owner": e.owner,
        "root": str(e.root),
        "kind": e.kind,
        "sha256": e.sha256,
    }
    # Emitted only when present, so a legacy receipt (no digests) round-trips
    # byte-for-byte and existing integrity digests keep validating.
    if e.dir_digest is not None:
        out["dir_digest"] = e.dir_digest
    return out


def _entry_from_json(d: object) -> ReceiptEntry:
    if not isinstance(d, dict):
        raise ValueError("entry is not an object")  # noqa: TRY003, TRY004  # caught -> CORRUPT; subclass not justified
    kind = d["kind"]
    if kind not in ("file", "dir"):
        raise ValueError(f"bad kind {kind!r}")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    sha = d["sha256"]
    if sha is not None and not isinstance(sha, str):
        raise ValueError("sha256 must be string or null")  # noqa: TRY003  # caught -> CORRUPT; subclass not justified
    # kind<->sha256 coupling (mirrors write-time receipt_build): a file always
    # carries a digest, a dir never does. A file with null sha256 would defeat
    # hash-aware relinquishment (prune_hash deletes it instead of keeping a
    # user-modified file); fail closed -> CORRUPT.
    if kind == "file" and not isinstance(sha, str):
        raise ValueError("file entry requires string sha256")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    if kind == "dir" and sha is not None:
        raise ValueError("dir entry must have null sha256")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    # dir_digest is the directory analogue of sha256: optional (absent only on
    # legacy dir entries recorded before the field existed), str when present, and
    # never on a file entry. A file carrying one, or a non-string digest, is
    # schema-invalid on a file-deleting boundary -> CORRUPT (fail closed).
    dir_digest = d.get("dir_digest")
    if dir_digest is not None and not isinstance(dir_digest, str):
        raise ValueError("dir_digest must be string or null")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    if kind == "file" and dir_digest is not None:
        raise ValueError("file entry must not have dir_digest")  # noqa: TRY003  # caught -> CORRUPT; single call-site
    # Validate the string fields rather than ``str()``-coercing them: a JSON
    # number/list would otherwise coerce to a path/owner whose digest still
    # matches (the integrity is computed over the coerced form), silently
    # admitting a schema-invalid receipt on a file-deleting boundary. Reject
    # non-strings -> CORRUPT (fail closed). KeyError on a missing field is also
    # caught upstream as CORRUPT.
    path = d["path"]
    owner = d["owner"]
    root = d["root"]
    if not (isinstance(path, str) and isinstance(owner, str) and isinstance(root, str)):
        raise ValueError("path/owner/root must be strings")  # noqa: TRY003, TRY004  # caught -> CORRUPT; subclass not justified
    return ReceiptEntry(
        path=Path(path),
        owner=owner,
        root=Path(root),
        kind=kind,
        sha256=sha,
        dir_digest=dir_digest,
    )


def _cli_entry_from_json(d: object) -> CliReceiptEntry:
    if not isinstance(d, dict):
        raise ValueError("cli entry is not an object")  # noqa: TRY003, TRY004  # caught -> CORRUPT
    name, binary, digest = d.get("name"), d.get("binary"), d.get("digest")
    # Non-string fields fail closed -> CORRUPT: a malformed entry must not
    # drive deploy/prune decisions (spec §7).
    if not (isinstance(name, str) and isinstance(binary, str) and isinstance(digest, str)):
        raise ValueError(  # noqa: TRY003, TRY004  # caught -> CORRUPT; subclass not justified
            "cli entry name/binary/digest must be strings"
        )
    return CliReceiptEntry(name=name, binary=binary, digest=digest)


def to_json_obj(receipt: Receipt) -> dict[str, object]:
    out: dict[str, object] = {
        "schema_version": receipt.schema_version,
        "integrity": receipt.integrity,
        "roots": [str(r) for r in receipt.roots],
        "entries": [_entry_to_json(e) for e in receipt.entries],
    }
    if receipt.clis:
        out["clis"] = [
            {"name": c.name, "binary": c.binary, "digest": c.digest} for c in receipt.clis
        ]
    return out


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
    # ``roots`` is the persisted allowlist that gates retired-plugin root
    # legitimacy in the prune trust boundary; a non-string element would coerce
    # to a path whose digest still matches. Validate the element type -> CORRUPT.
    if not all(isinstance(r, str) for r in roots_raw):
        raise ValueError("roots must be a list of strings")  # noqa: TRY003  # caught -> CORRUPT; subclass not justified
    clis_raw = data.get("clis", [])
    if not isinstance(clis_raw, list):
        raise ValueError("clis must be a list")  # noqa: TRY003, TRY004  # caught -> CORRUPT
    return Receipt(
        schema_version=SCHEMA_VERSION,
        roots=tuple(Path(r) for r in roots_raw),
        entries=tuple(_entry_from_json(e) for e in entries_raw),
        clis=tuple(_cli_entry_from_json(c) for c in clis_raw),
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
