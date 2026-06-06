"""Unit tests for the last-wins collision strategies.

Two strategies share the "incoming wins" resolution but differ on whether
they announce the overwrite:

- ``LastWinsWarnStrategy`` ((JSONC, *) / (TOML, *)) emits a stdlib
  ``warnings.warn`` whose message names BOTH colliding source paths, then
  returns the ``incoming`` item unchanged.
- ``LastWinsSilentStrategy`` ((OTHER, *)) returns ``incoming`` with no warning.

Each test pins a coded decision in that contract. Tests that would only
exercise Python/stdlib semantics (frozen-dataclass immutability, that
``warnings.warn`` raises under ``error`` filter, …) are deliberately absent.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from installer.core.merge.base import MergeStrategy
from installer.core.merge.strategies.last_wins_silent import LastWinsSilentStrategy
from installer.core.merge.strategies.last_wins_warn import LastWinsWarnStrategy
from installer.core.model import FileKind, Provenance, StagedItem


def _item(source: str, kind: FileKind, dest: str = "config.jsonc") -> StagedItem:
    return StagedItem(
        source_path=Path(source),
        dest_relpath=Path(dest),
        kind=kind,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=source.encode(),
    )


# --- LastWinsWarnStrategy ----------------------------------------------------


def test_warn_strategy_returns_incoming_item() -> None:
    """Last-wins means the colliding ``incoming`` item is the staged result;
    the warn variant resolves to ``incoming`` identically (by object identity)."""
    existing = _item("/src/a/config.jsonc", FileKind.JSONC)
    incoming = _item("/src/b/config.jsonc", FileKind.JSONC)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = LastWinsWarnStrategy().merge(existing, incoming)

    assert result is incoming


def test_warn_strategy_warning_names_both_source_paths() -> None:
    """The emitted warning must name BOTH source paths so an operator can
    see exactly which file was overwritten by which."""
    existing = _item("/src/a/config.jsonc", FileKind.JSONC)
    incoming = _item("/src/b/config.jsonc", FileKind.JSONC)

    with pytest.warns(UserWarning) as record:
        LastWinsWarnStrategy().merge(existing, incoming)

    assert len(record) == 1
    message = str(record[0].message)
    assert str(existing.source_path) in message
    assert str(incoming.source_path) in message


def test_warn_strategy_warning_emitted_for_toml_kind() -> None:
    """The warn strategy serves both (JSONC, *) and (TOML, *); a TOML
    collision warns the same way (kind is not branched on inside merge)."""
    existing = _item("/src/a/cfg.toml", FileKind.TOML, dest="cfg.toml")
    incoming = _item("/src/b/cfg.toml", FileKind.TOML, dest="cfg.toml")

    with pytest.warns(UserWarning) as record:
        result = LastWinsWarnStrategy().merge(existing, incoming)

    assert result is incoming
    message = str(record[0].message)
    assert str(existing.source_path) in message
    assert str(incoming.source_path) in message


def test_warn_strategy_satisfies_merge_strategy_protocol() -> None:
    """The warn strategy structurally satisfies the ``MergeStrategy`` protocol."""
    strategy: MergeStrategy = LastWinsWarnStrategy()
    assert isinstance(strategy, MergeStrategy)


# --- LastWinsSilentStrategy --------------------------------------------------


def test_silent_strategy_returns_incoming_item() -> None:
    """Last-wins: the silent variant resolves to ``incoming`` by identity."""
    existing = _item("/src/a/file.txt", FileKind.OTHER, dest="file.txt")
    incoming = _item("/src/b/file.txt", FileKind.OTHER, dest="file.txt")

    result = LastWinsSilentStrategy().merge(existing, incoming)

    assert result is incoming


def test_silent_strategy_emits_no_warning() -> None:
    """The silent variant overwrites without announcing it — the defining
    behavioural difference from the warn variant. Any warning is a failure."""
    existing = _item("/src/a/file.txt", FileKind.OTHER, dest="file.txt")
    incoming = _item("/src/b/file.txt", FileKind.OTHER, dest="file.txt")

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning would raise here
        result = LastWinsSilentStrategy().merge(existing, incoming)

    assert result is incoming


def test_silent_strategy_satisfies_merge_strategy_protocol() -> None:
    """The silent strategy structurally satisfies the ``MergeStrategy`` protocol."""
    strategy: MergeStrategy = LastWinsSilentStrategy()
    assert isinstance(strategy, MergeStrategy)
