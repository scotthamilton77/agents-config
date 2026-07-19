"""grind — event schema and FSM fold for the event-sourced grind runtime.

The event log (``events.jsonl``) is the source of truth for one grind run;
``fold()`` is the pure transition function that turns it into a materialized
``State``. See ``docs/specs/2026-07-19-event-sourced-grind-runtime.md`` for
the behavioral spec this package implements.
"""

from __future__ import annotations

SCHEMA_VERSION = "1.0"
