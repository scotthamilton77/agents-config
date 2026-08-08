"""Invariant guard: the known confirmed dev-doc leakers never appear in the
Python installer's staged output, using the REAL repo-root .installignore.

The leaker paths are HARDCODED here, deliberately NOT sourced from .installignore:
a manifest-sourced check would go blind to the exact regression it must catch —
someone deleting an entry from .installignore. This test goes red on a manifest
mis-edit OR a staging-logic regression."""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import load_installignore
from installer.core.model import Tool
from installer.core.staging import build_plan
from installer.tools.registry import get_adapter

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Confirmed live leakers (design spec audit table). Their relpaths must never
# survive base staging into any tool's plan.
_FORBIDDEN_RELPATHS = (
    Path("rules/AGENTS.md"),
    Path("skills/AGENTS.md"),
)
_NAMESPACE_DIRS = {"skills", "agents", "rules", "commands", "hooks"}
_MARKER_BASENAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}


def test_known_dead_docs_are_never_staged() -> None:
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    for tool in Tool:
        adapter = get_adapter(tool)
        plan = build_plan(adapter, repo_root=_REPO_ROOT, ignore=ignore)

        for forbidden in _FORBIDDEN_RELPATHS:
            assert forbidden not in plan.items, f"{forbidden} leaked into {tool} plan"
        # No namespace-level AGENTS.md/CLAUDE.md/GEMINI.md under a staged subdir.
        for dest in plan.items:
            parts = dest.parts
            if len(parts) >= 2 and parts[-1] in _MARKER_BASENAMES:
                assert parts[-2] not in _NAMESPACE_DIRS, (
                    f"namespace dead-doc {dest} leaked into {tool} plan"
                )


def test_marker_docs_are_excluded_at_every_depth_not_just_the_namespace_level() -> None:
    """The three marker names must stay UNANCHORED in the real manifest.

    Staging sees only a namespace dir's direct children; a skill stages as one
    DIR item whose interior the copy walks separately. An anchored marker entry
    would therefore leave ``skills/<skill>/AGENTS.md`` deploying — and in this
    repo a skill's own AGENTS.md is guidance for whoever maintains its scripts,
    so it would ship to every install carrying repo-internal vocabulary.

    This pins the manifest's policy, not the matcher's mechanism (that is
    test_installignore.py's job): re-anchoring any of the three turns it red."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    for marker in sorted(_MARKER_BASENAMES):
        for rel in (Path(f"some-skill/{marker}"), Path(f"some-skill/references/{marker}")):
            assert ignore.excludes_path(rel), (
                f"{rel} would deploy — {marker} is anchored in .installignore and must not be"
            )


def test_readme_stays_anchored_so_a_skill_can_ship_one() -> None:
    """README.md is the deliberate exception to the rule above.

    Unlike the marker names it is genuinely ambiguous — a skill's own
    references/README.md may be content it means to ship — so it stays anchored
    to the namespace level. Unanchoring it would silently stop deploying that
    file, which is the failure mode the anchoring rule exists to prevent."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    assert not ignore.excludes_path(Path("some-skill/references/README.md"))
    assert ignore.excludes("README.md", is_dir=False, at_root=True)
