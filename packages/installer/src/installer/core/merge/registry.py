"""Dispatch registry mapping ``(FileKind, namespace)`` to a strategy.

The registry decides *which* :class:`MergeStrategy` resolves a collision.
For ``NAMESPACED_MD`` the namespace (the item's parent-dir name) selects
the strategy — e.g. ``(NAMESPACED_MD, "rules")`` append-merges while
``(NAMESPACED_MD, "commands")`` is fatal. For every other kind
(``SETTINGS_JSON`` / ``JSONC`` / ``TOML`` / ``OTHER`` / ``DIR``) the
namespace component is irrelevant and is normalized to ``None`` on both
``register`` and ``resolve`` so the key degenerates to a ``FileKind``.

The :class:`MergeRegistry` mechanism imports no concrete strategy; the
:func:`default_registry` factory at the foot of this module is the one place
that wires the concrete strategies onto their ``(FileKind, namespace)`` keys.
"""

from __future__ import annotations

from installer.core.merge.base import MergeStrategy
from installer.core.merge.strategies.append_rules import AppendRulesStrategy
from installer.core.merge.strategies.fatal import FatalStrategy
from installer.core.merge.strategies.json_union import JsonUnionStrategy
from installer.core.merge.strategies.last_wins_silent import LastWinsSilentStrategy
from installer.core.merge.strategies.last_wins_warn import LastWinsWarnStrategy
from installer.core.model import FileKind

# Kinds whose collision resolution does not depend on a namespace. Their
# namespace component is normalized to None so a single registration serves
# every namespace value seen at lookup time.
_NON_NAMESPACED_KINDS: frozenset[FileKind] = frozenset(
    {
        FileKind.DIR,
        FileKind.SETTINGS_JSON,
        FileKind.JSONC,
        FileKind.TOML,
        FileKind.OTHER,
    }
)


def _normalize(kind: FileKind, namespace: str | None) -> tuple[FileKind, str | None]:
    """Collapse the namespace to None for non-namespaced kinds so register
    and resolve agree on the key regardless of the caller's namespace."""
    if kind in _NON_NAMESPACED_KINDS:
        return (kind, None)
    return (kind, namespace)


class UnknownMergeKeyError(ValueError):
    """Raised when ``resolve`` is asked for a ``(kind, namespace)`` with no
    registered strategy — a wiring/programmer error, deliberately NOT a
    ``CollisionError`` (which is reserved for real file collisions).
    Structured attrs (``.kind`` / ``.namespace``) let callers and tests
    assert on data, not on the message string."""

    def __init__(self, kind: FileKind, namespace: str | None) -> None:
        super().__init__(
            f"No merge strategy registered for kind {kind.value!r} with namespace {namespace!r}."
        )
        self.kind = kind
        self.namespace = namespace


class MergeRegistry:
    """Mutable ``(FileKind, namespace) -> MergeStrategy`` lookup, easily
    populated in tests with dummy strategies and at runtime by
    ``default_registry()``."""

    def __init__(self) -> None:
        self._strategies: dict[tuple[FileKind, str | None], MergeStrategy] = {}

    def register(self, kind: FileKind, namespace: str | None, strategy: MergeStrategy) -> None:
        """Bind ``strategy`` to ``(kind, namespace)``. For non-namespaced
        kinds the namespace is normalized to None before storing."""
        self._strategies[_normalize(kind, namespace)] = strategy

    def resolve(self, kind: FileKind, namespace: str | None) -> MergeStrategy:
        """Return the strategy for ``(kind, namespace)``. For non-namespaced
        kinds the namespace is ignored. Raises :class:`UnknownMergeKeyError`
        if nothing is registered."""
        key = _normalize(kind, namespace)
        try:
            return self._strategies[key]
        except KeyError:
            raise UnknownMergeKeyError(key[0], key[1]) from None


def default_registry() -> MergeRegistry:
    """Build the production registry: every concrete strategy bound to the
    ``(FileKind, namespace)`` key it resolves.

    ``NAMESPACED_MD`` dispatches by namespace — ``"rules"`` collisions are
    additive (append) while ``"commands"`` / ``"skills"`` / ``"agents"`` are
    irreconcilable (fatal). Every non-namespaced kind is registered under the
    ``None`` namespace; the registry normalizes the namespace away on lookup,
    so any namespace value passed at resolve time still hits these bindings.

    Kinds NOT wired here (and un-wired ``NAMESPACED_MD`` namespaces) remain a
    lookup miss: ``resolve`` raises :class:`UnknownMergeKeyError`. The factory
    adds bindings; it does not make the registry permissive.
    """
    registry = MergeRegistry()
    registry.register(FileKind.NAMESPACED_MD, "rules", AppendRulesStrategy())
    registry.register(FileKind.NAMESPACED_MD, "commands", FatalStrategy())
    registry.register(FileKind.NAMESPACED_MD, "skills", FatalStrategy())
    registry.register(FileKind.NAMESPACED_MD, "agents", FatalStrategy())
    registry.register(FileKind.SETTINGS_JSON, None, JsonUnionStrategy())
    registry.register(FileKind.JSONC, None, LastWinsWarnStrategy())
    registry.register(FileKind.TOML, None, LastWinsWarnStrategy())
    registry.register(FileKind.OTHER, None, LastWinsSilentStrategy())
    registry.register(FileKind.DIR, None, FatalStrategy())
    return registry
