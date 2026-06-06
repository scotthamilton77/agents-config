"""Collision-resolution subsystem for the staging phase.

When two staged items target the same ``dest_relpath`` (a collision), the
staging engine resolves them through a :class:`MergeStrategy` selected by
the :class:`MergeRegistry` on the item's ``(FileKind, namespace)`` key.

The merge contract lives in ``base`` and the dispatch mechanism in
``registry``; the concrete strategies live under ``strategies/``. The
``default_registry()`` factory in ``registry`` is the single place that
binds each strategy to its ``(FileKind, namespace)`` key.
"""
