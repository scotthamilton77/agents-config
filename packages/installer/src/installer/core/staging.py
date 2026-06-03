"""Staging-phase transforms applied to source files on their way into a StagingPlan.

B.3: strip_template_suffix — removes the .template suffix from a path's final
component so that AGENTS.md.template arrives at the destination as AGENTS.md.

B.4 will extend this module with stage_file(), which calls strip_template_suffix
internally alongside DYNAMIC-INCLUDE detection.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.model import FileKind


def strip_template_suffix(path: Path) -> Path:
    """Strip .template if it is the final suffix; return path unchanged otherwise.

    Uses Path.with_suffix("") so that double-suffixed names such as
    AGENTS.md.template correctly collapse to AGENTS.md without touching
    any earlier suffix component.
    """
    if path.suffix == ".template":
        return path.with_suffix("")
    return path


def classify_file(path: Path, namespace: str | None) -> FileKind:
    """Merge-dispatch classification of a source path.

    Port of the bash ``classify_file`` (``scripts/install.sh:486-505``).
    ``namespace`` is the parent namespace dir name (``skills``/``rules``/…)
    or ``None`` for tool-root files; it promotes a ``*.md`` file to
    ``NAMESPACED_MD`` exactly as the bash ``-n "$parent_dir"`` guard does.
    The directory check is first, mirroring the bash ordering, so a
    directory named ``foo.toml`` still classifies as ``DIR``.
    """
    if path.is_dir():
        return FileKind.DIR
    name = path.name
    if name == "settings.json.template":
        return FileKind.SETTINGS_JSON
    if name.endswith(".jsonc.template"):
        return FileKind.JSONC
    if name.endswith(".toml.template") or name.endswith(".toml"):
        return FileKind.TOML
    if name.endswith(".md") and namespace:
        return FileKind.NAMESPACED_MD
    return FileKind.OTHER
