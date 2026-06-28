"""Bounded-memory file hashing.

A single streaming sha-256 helper shared by every site that fingerprints a file
on disk (``sync`` dest comparison, ``prune_hash`` file-orphan guard,
``receipt.dir_content_digest``). Streaming via :func:`hashlib.file_digest`
(stdlib 3.11+) keeps memory bounded regardless of file size; the digest is
byte-identical to hashing ``path.read_bytes()`` in one shot.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def sha256_file(path: Path) -> bytes:
    """Return the raw sha-256 digest of ``path``'s contents, read in bounded memory.

    Hex callers use ``.hex()`` on the result — identical to ``hexdigest()``.
    Symlinks are dereferenced (the file is opened for reading), matching the
    prior ``read_bytes()`` behaviour at every call site.
    """
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").digest()
