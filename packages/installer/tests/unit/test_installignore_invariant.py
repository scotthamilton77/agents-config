"""Invariant guard: the known confirmed dev-doc leakers never appear in the
Python installer's staged output, using the REAL repo-root .installignore.

The leaker paths are HARDCODED here, deliberately NOT sourced from .installignore:
a manifest-sourced check would go blind to the exact regression it must catch —
someone deleting an entry from .installignore. This test goes red on a manifest
mis-edit OR a staging-logic regression, and survives the parity gate (it tests
Python, the permanent installer, not the bash↔python comparison)."""

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
