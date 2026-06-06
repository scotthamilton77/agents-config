"""Unit tests for installer.core.merge.registry.

Each test pins a coded dispatch decision in the merge registry (E.1):

- A registered ``(kind, namespace)`` key resolves to its strategy.
- ``NAMESPACED_MD`` dispatches BY namespace — ``"rules"`` and ``"commands"``
  can map to different strategies.
- Non-namespaced kinds (SETTINGS_JSON / JSONC / TOML / OTHER / DIR) IGNORE
  the namespace component: registering under ``None`` resolves for any
  namespace value passed at lookup time.
- An unknown ``(kind, namespace)`` key raises a clear lookup error that is
  NOT ``CollisionError`` (which is reserved for real file collisions).

These pin the dispatch contract, not the stdlib dict that backs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.merge.base import CollisionError, MergeStrategy
from installer.core.merge.registry import MergeRegistry, UnknownMergeKeyError
from installer.core.model import FileKind, Provenance, StagedItem


class _DummyStrategy:
    """Minimal MergeStrategy stub. The constructor ``label`` is a readable
    identifier for debugging; tests assert WHICH strategy resolve() returned
    via object identity (``is``)."""

    def __init__(self, label: str) -> None:
        self.label = label

    def merge(
        self,
        existing: StagedItem,  # noqa: ARG002  # inert stub
        incoming: StagedItem,
    ) -> StagedItem:
        return incoming


def test_register_then_resolve_returns_the_registered_strategy() -> None:
    reg = MergeRegistry()
    strat = _DummyStrategy("toml")
    reg.register(FileKind.TOML, None, strat)

    assert reg.resolve(FileKind.TOML, None) is strat


def test_namespaced_md_dispatches_by_namespace() -> None:
    """The whole point of keying on (kind, namespace): the SAME FileKind
    resolves to DIFFERENT strategies depending on the namespace."""
    reg = MergeRegistry()
    rules = _DummyStrategy("rules-append")
    commands = _DummyStrategy("commands-fatal")
    reg.register(FileKind.NAMESPACED_MD, "rules", rules)
    reg.register(FileKind.NAMESPACED_MD, "commands", commands)

    assert reg.resolve(FileKind.NAMESPACED_MD, "rules") is rules
    assert reg.resolve(FileKind.NAMESPACED_MD, "commands") is commands


def test_namespaced_md_distinct_namespaces_do_not_collide() -> None:
    """Registering a second namespace must not overwrite the first —
    guards against a FileKind-only key silently clobbering entries."""
    reg = MergeRegistry()
    rules = _DummyStrategy("rules")
    commands = _DummyStrategy("commands")
    reg.register(FileKind.NAMESPACED_MD, "rules", rules)
    reg.register(FileKind.NAMESPACED_MD, "commands", commands)

    assert reg.resolve(FileKind.NAMESPACED_MD, "rules") is rules


def test_non_namespaced_kind_ignores_namespace_on_register_and_resolve() -> None:
    """For SETTINGS_JSON the namespace component is normalized to None:
    a strategy registered under None resolves even when a (nonsense)
    namespace is supplied at lookup time."""
    reg = MergeRegistry()
    strat = _DummyStrategy("json-union")
    reg.register(FileKind.SETTINGS_JSON, None, strat)

    assert reg.resolve(FileKind.SETTINGS_JSON, "anything") is strat
    assert reg.resolve(FileKind.SETTINGS_JSON, None) is strat


def test_non_namespaced_kind_register_with_namespace_is_normalized() -> None:
    """Registering a non-namespaced kind WITH a namespace normalizes it to
    None, so a later resolve without (or with any) namespace still hits."""
    reg = MergeRegistry()
    strat = _DummyStrategy("other")
    reg.register(FileKind.OTHER, "spurious", strat)

    assert reg.resolve(FileKind.OTHER, None) is strat
    assert reg.resolve(FileKind.OTHER, "different") is strat


def test_resolve_unknown_key_raises_unknown_merge_key_error() -> None:
    reg = MergeRegistry()

    with pytest.raises(UnknownMergeKeyError):
        reg.resolve(FileKind.JSONC, None)


def test_unknown_key_error_is_not_collision_error() -> None:
    """A lookup miss is a programmer/wiring error, NOT a file collision.
    Conflating the two would mislead operators, so the classes are distinct."""
    reg = MergeRegistry()

    with pytest.raises(UnknownMergeKeyError) as excinfo:
        reg.resolve(FileKind.NAMESPACED_MD, "unregistered")

    assert not isinstance(excinfo.value, CollisionError)


def test_unknown_key_error_message_names_kind_and_namespace() -> None:
    """The error must identify the missing (kind, namespace) so a wiring
    gap is diagnosable from the message alone."""
    reg = MergeRegistry()

    with pytest.raises(UnknownMergeKeyError) as excinfo:
        reg.resolve(FileKind.NAMESPACED_MD, "ghost")

    text = str(excinfo.value)
    assert FileKind.NAMESPACED_MD.value in text
    assert "ghost" in text


def test_resolved_strategy_is_usable_as_merge_strategy() -> None:
    """End-to-end: what resolve() returns honours the MergeStrategy
    contract — it can merge two colliding items."""
    reg = MergeRegistry()
    reg.register(FileKind.TOML, None, _DummyStrategy("toml"))

    strategy: MergeStrategy = reg.resolve(FileKind.TOML, None)
    existing = StagedItem(
        source_path=Path("/a/x.toml"),
        dest_relpath=Path("x.toml"),
        kind=FileKind.TOML,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=b"a=1",
    )
    incoming = StagedItem(
        source_path=Path("/b/x.toml"),
        dest_relpath=Path("x.toml"),
        kind=FileKind.TOML,
        namespace=None,
        provenance=Provenance(kind="plugin", name="beads"),
        content=b"b=2",
    )

    assert strategy.merge(existing, incoming) is incoming
