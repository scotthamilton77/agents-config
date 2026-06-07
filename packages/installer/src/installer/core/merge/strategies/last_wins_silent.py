"""Last-wins-silent strategy for ``(OTHER, *)``.

``OTHER`` is the catch-all kind for opaque files the installer neither
parses nor structurally merges. A collision resolves to *last wins*: the
``incoming`` item replaces the ``existing`` one, and — unlike the JSONC/TOML
variant — the overwrite is **not** announced. ``OTHER`` collisions are
expected and benign in normal operation (e.g. re-staging the same asset
from two sources), so a warning would be noise; the warn variant is reserved
for the structured-config kinds where a lost merge is worth surfacing.
"""

from __future__ import annotations

from installer.core.model import StagedItem


class LastWinsSilentStrategy:
    """Resolve an ``OTHER`` collision by replacing ``existing`` with
    ``incoming`` silently (no warning)."""

    def merge(
        self,
        existing: StagedItem,  # noqa: ARG002  # last-wins discards existing
        incoming: StagedItem,
    ) -> StagedItem:
        """Return ``incoming`` unchanged — it already carries its own
        ``provenance`` and ``source_path``; last-wins stages it verbatim."""
        return incoming
