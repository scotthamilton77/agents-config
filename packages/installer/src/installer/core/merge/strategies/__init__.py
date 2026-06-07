"""Concrete merge strategies — one module + test file per strategy.

Each strategy (``append_rules``, ``fatal``, ``json_union``, ``last_wins_warn``,
``last_wins_silent``) is an independent module; the ``registry`` module's
``default_registry()`` binds them to their ``(FileKind, namespace)`` keys.
"""
