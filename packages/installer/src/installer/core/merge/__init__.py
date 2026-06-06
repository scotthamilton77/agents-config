"""Collision-resolution subsystem for the staging phase.

When two staged items target the same ``dest_relpath`` (a collision), the
staging engine resolves them through a :class:`MergeStrategy` selected by
the :class:`MergeRegistry` on the item's ``(FileKind, namespace)`` key.

This package ships only the *mechanism* (E.1): the merge contract
(``base``) and the dispatch registry (``registry``). Concrete strategies
live under ``strategies/`` (E.2-E.5); the ``default_registry()`` factory
that wires them is added at the Integrate stage.
"""
