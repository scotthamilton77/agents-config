"""Staging-phase transforms applied to source files on their way into a StagingPlan.

B.3: strip_template_suffix — removes the .template suffix from a path's final
component so that AGENTS.md.template arrives at the destination as AGENTS.md.

B.4 will extend this module with stage_file(), which calls strip_template_suffix
internally alongside DYNAMIC-INCLUDE detection.
"""

from __future__ import annotations

from pathlib import Path


def strip_template_suffix(path: Path) -> Path:
    """Strip .template if it is the final suffix; return path unchanged otherwise.

    Uses Path.with_suffix("") so that double-suffixed names such as
    AGENTS.md.template correctly collapse to AGENTS.md without touching
    any earlier suffix component.
    """
    if path.suffix == ".template":
        return path.with_suffix("")
    return path
