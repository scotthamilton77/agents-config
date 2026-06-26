"""The install receipt — a record of what the installer authored wholesale.

Distinct from the ``.installignore`` *exclusion manifest* (source-side); the
receipt records destination output so pruning can diff "what we installed" against
"what we still want installed". See docs/specs/2026-06-25-install-receipt-pruning-design.md.
"""

from __future__ import annotations

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
