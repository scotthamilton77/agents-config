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

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReceiptEntry:
    """One wholesale-authored dest entry. ``path``/``root`` are home-relative."""

    path: Path
    owner: str
    root: Path
    kind: Literal["file", "dir"]
    sha256: str | None


@dataclass(frozen=True, slots=True)
class Receipt:
    """The whole receipt. ``roots`` is the persisted install-root allowlist."""

    schema_version: int = SCHEMA_VERSION
    roots: tuple[Path, ...] = ()
    entries: tuple[ReceiptEntry, ...] = ()
    integrity: str | None = field(default=None)


def canonical_bytes(receipt: Receipt) -> bytes:
    """Deterministic content bytes for the integrity digest — EXCLUDES ``integrity``.

    Entries are sorted by path so receipt equality is order-independent; the digest
    covers schema_version, roots, and entries only."""
    entries = sorted(receipt.entries, key=lambda e: str(e.path))
    payload: dict[str, object] = {
        "schema_version": receipt.schema_version,
        "roots": [str(r) for r in receipt.roots],
        "entries": [[str(e.path), e.owner, str(e.root), e.kind, e.sha256] for e in entries],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_integrity(receipt: Receipt) -> str:
    """The ``sha256:<hex>`` digest over the receipt's integrity-free content."""
    return "sha256:" + hashlib.sha256(canonical_bytes(receipt)).hexdigest()
