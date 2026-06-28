"""Unit tests for the streaming file-digest helper."""

from __future__ import annotations

import hashlib
from pathlib import Path

from installer.core.hashing import sha256_file


def test_matches_in_memory_digest_for_multichunk_file(tmp_path: Path) -> None:
    """sha256_file streams the same canonical digest the in-memory path produced.

    Sized well past file_digest's internal read buffer so a single-read bug
    (truncated digest) would diverge from hashing the whole byte string.
    """
    data = bytes(i % 256 for i in range(300_000))
    target = tmp_path / "blob.bin"
    target.write_bytes(data)

    assert sha256_file(target).hex() == hashlib.sha256(data).hexdigest()


def test_empty_file(tmp_path: Path) -> None:
    """An empty file hashes to the canonical sha-256 of no bytes."""
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")

    assert sha256_file(target) == hashlib.sha256(b"").digest()
