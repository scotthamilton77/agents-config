"""vizsuite — the `viz` CLI transport layer.

Produces a self-contained HTML PR-shape artifact from deterministic Tier-1
extracts. Mirrors ``workcli``'s adapter / verb / envelope structure: stdout is
always exactly one JSON envelope, outside-world dependencies are injected as
arguments, and expected failures are modeled as ``VizError``/``ErrorCode``.

See ``docs/specs/2026-07-12-visualization-suite-design.md`` for the design and
``docs/plans/visualization-suite/2026-07-13-implementation-plan.md`` for the
PR-sliced build map this package implements.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1"
__version__ = "0.1.0"
