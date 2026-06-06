"""Last-wins-with-warning strategy for ``(JSONC, *)`` and ``(TOML, *)``.

JSONC and TOML have no safe structural union the installer can perform
blindly (comment placement, table ordering, and key-merge semantics are all
format- and intent-specific), so a collision resolves to *last wins*: the
``incoming`` item replaces the ``existing`` one. Because that silently
discards the existing file's content, the overwrite is announced via a
stdlib :func:`warnings.warn` whose message names BOTH colliding source paths.

This module establishes the package's collision-warning convention: route
through stdlib ``warnings`` (category :class:`UserWarning`), not ``print`` /
``logging`` / ``rich``. ``warnings`` is the right channel for a
"this-degraded-gracefully, here is what happened" signal — it is capturable
in tests via ``pytest.warns`` and suppressible by callers via the warnings
filter, neither of which a bare ``print`` affords. The ``merge`` signature
carries no ``IOPort``, so terminal injection is not an option here.
"""

from __future__ import annotations

import warnings

from installer.core.model import StagedItem


class LastWinsWarnStrategy:
    """Resolve a JSONC/TOML collision by replacing ``existing`` with
    ``incoming`` and warning that the overwrite happened."""

    def merge(self, existing: StagedItem, incoming: StagedItem) -> StagedItem:
        """Warn (naming both source paths), then return ``incoming``.

        ``incoming`` already carries its own ``provenance`` and
        ``source_path``; last-wins stages it verbatim rather than
        synthesising a new item, so it is returned as-is.
        """
        warnings.warn(
            f"Last-wins overwrite: {incoming.source_path} replaces "
            f"{existing.source_path} at destination {incoming.dest_relpath} "
            f"(no structural merge for this file kind).",
            UserWarning,
            stacklevel=2,
        )
        return incoming
