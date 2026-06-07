"""Integration tests for ``default_registry()`` — the concrete dispatch table.

The mechanism (``MergeRegistry.register`` / ``resolve``) is unit-tested in
``test_merge_registry``. THIS file pins the WIRING: which concrete strategy
``default_registry()`` binds to each ``(FileKind, namespace)`` key. Each test
asserts the resolved strategy TYPE, pinning a coded routing decision:

- ``NAMESPACED_MD`` dispatches by namespace — ``"rules"`` append-merges while
  ``"commands"`` / ``"skills"`` / ``"agents"`` are fatal (a coded asymmetry,
  not an implementation accident).
- Non-namespaced kinds ignore the namespace component.
- A key the factory does NOT wire still raises ``UnknownMergeKeyError`` — the
  factory adds bindings, it does not turn the registry permissive.

These are routing assertions (resolve(key) -> expected type), not re-tests of
the strategies' merge behaviour (covered per-strategy) nor of the registry's
normalization mechanism (covered in test_merge_registry).
"""

from __future__ import annotations

import pytest

from installer.core.merge.registry import (
    MergeRegistry,
    UnknownMergeKeyError,
    default_registry,
)
from installer.core.merge.strategies.append_rules import AppendRulesStrategy
from installer.core.merge.strategies.fatal import FatalStrategy
from installer.core.merge.strategies.json_union import JsonUnionStrategy
from installer.core.merge.strategies.last_wins_silent import LastWinsSilentStrategy
from installer.core.merge.strategies.last_wins_warn import LastWinsWarnStrategy
from installer.core.model import FileKind


def test_default_registry_returns_a_merge_registry() -> None:
    """The factory hands back a populated MergeRegistry instance — callers
    wire collision resolution off this, so the concrete type matters."""
    assert isinstance(default_registry(), MergeRegistry)


def test_rules_namespace_routes_to_append() -> None:
    """rules/ collisions are additive — they must route to the append
    strategy, never the fatal one (the load-bearing namespace asymmetry)."""
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.NAMESPACED_MD, "rules"), AppendRulesStrategy)


@pytest.mark.parametrize("namespace", ["commands", "skills", "agents"])
def test_non_rules_namespaces_route_to_fatal(namespace: str) -> None:
    """commands/skills/agents collisions are irreconcilable — each must route
    to FatalStrategy, distinct from the rules append route."""
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.NAMESPACED_MD, namespace), FatalStrategy)


def test_rules_and_commands_resolve_to_different_strategies() -> None:
    """Pins the dispatch-by-namespace contract end to end: the SAME kind
    with two namespaces yields two DIFFERENT strategy types."""
    reg = default_registry()
    assert type(reg.resolve(FileKind.NAMESPACED_MD, "rules")) is not type(
        reg.resolve(FileKind.NAMESPACED_MD, "commands")
    )


def test_settings_json_routes_to_json_union() -> None:
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.SETTINGS_JSON, None), JsonUnionStrategy)


def test_jsonc_routes_to_last_wins_warn() -> None:
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.JSONC, None), LastWinsWarnStrategy)


def test_toml_routes_to_last_wins_warn() -> None:
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.TOML, None), LastWinsWarnStrategy)


def test_other_routes_to_last_wins_silent() -> None:
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.OTHER, None), LastWinsSilentStrategy)


def test_dir_routes_to_fatal() -> None:
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.DIR, None), FatalStrategy)


@pytest.mark.parametrize("namespace", [None, "ignored", "whatever"])
def test_non_namespaced_kinds_ignore_namespace(namespace: str | None) -> None:
    """SETTINGS_JSON is wired under None; the factory must rely on the
    registry's normalization so any namespace at lookup still resolves."""
    reg = default_registry()
    assert isinstance(reg.resolve(FileKind.SETTINGS_JSON, namespace), JsonUnionStrategy)


def test_unwired_namespaced_key_still_raises() -> None:
    """The factory wires specific namespaces; an un-wired NAMESPACED_MD
    namespace is a routing gap and must still raise — default_registry()
    does not make the registry permissive."""
    reg = default_registry()
    with pytest.raises(UnknownMergeKeyError):
        reg.resolve(FileKind.NAMESPACED_MD, "unwired_namespace")
