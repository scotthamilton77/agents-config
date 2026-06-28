"""The install receipt — a record of what the installer authored wholesale.

Distinct from the ``.installignore`` *exclusion manifest* (source-side); the
receipt records destination output so pruning can diff "what we installed" against
"what we still want installed". See docs/specs/2026-06-25-install-receipt-pruning-design.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from installer.core.hashing import sha256_file

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReceiptEntry:
    """One wholesale-authored dest entry. ``path``/``root`` are home-relative."""

    path: Path
    owner: str
    root: Path
    kind: Literal["file", "dir"]
    sha256: str | None
    dir_digest: str | None = None
    """Recursive content fingerprint for a ``dir`` entry (``None`` for files and for
    legacy dir entries recorded before this field existed). Lets the prune boundary
    relinquish a directory whose contents drifted from the owned state — the
    directory analogue of ``sha256`` for files."""


@dataclass(frozen=True, slots=True)
class Receipt:
    """The whole receipt. ``roots`` is the persisted install-root allowlist."""

    schema_version: int = SCHEMA_VERSION
    roots: tuple[Path, ...] = ()
    entries: tuple[ReceiptEntry, ...] = ()
    integrity: str | None = field(default=None)


def canonical_bytes(receipt: Receipt) -> bytes:
    """Deterministic content bytes for the integrity digest — EXCLUDES ``integrity``.

    Roots and entries are both sorted so the digest is order-independent for
    semantically-equal receipts; the digest covers schema_version, roots, and
    entries only."""
    entries = sorted(receipt.entries, key=lambda e: str(e.path))
    payload: dict[str, object] = {
        "schema_version": receipt.schema_version,
        "roots": sorted(str(r) for r in receipt.roots),
        "entries": [_entry_canonical(e) for e in entries],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entry_canonical(e: ReceiptEntry) -> list[object]:
    """Canonical list form of an entry. ``dir_digest`` is appended ONLY when present,
    so a receipt written before this field existed (no digest on any entry) hashes
    byte-identically — its persisted integrity still validates, with no
    ``SCHEMA_VERSION`` bump."""
    base: list[object] = [str(e.path), e.owner, str(e.root), e.kind, e.sha256]
    if e.dir_digest is not None:
        base.append(e.dir_digest)
    return base


def dir_content_digest(path: Path) -> str:
    """A recursive content fingerprint of a directory tree: ``sha256:<hex>`` over the
    sorted ``(relpath, sha256(bytes))`` of every file under ``path``.

    Mirrors ``sync._dir_is_unchanged``'s notion of owned content — files only
    (empty dirs ignored), symlinks dereferenced (both ``rglob`` and the per-file
    read follow them) — so a digest match means the same thing as "directory is unchanged" at
    install time. Order-independent via the sort; stable across runs on the same
    POSIX platform (relpaths are encoded with the OS separator, so the value is not
    portable across separator families — fine for this POSIX-targeted installer)."""
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file()):
        # surrogateescape so a filename with undecodable bytes (POSIX allows them;
        # the os layer fsdecodes them to lone surrogates) re-encodes losslessly
        # instead of raising UnicodeEncodeError at the prune boundary.
        h.update(str(f.relative_to(path)).encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(sha256_file(f))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def compute_integrity(receipt: Receipt) -> str:
    """The ``sha256:<hex>`` digest over the receipt's integrity-free content."""
    return "sha256:" + hashlib.sha256(canonical_bytes(receipt)).hexdigest()
