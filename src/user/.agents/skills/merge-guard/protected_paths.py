#!/usr/bin/env python3
"""protected_paths.py — the built-in human-required change classes.

A conservative superset of paths that alter the merge/review machinery, the
delivery/provenance workflow, CI/hooks, installer, secrets, or agent
instructions. A diff (base..head) touching any of these forces a STRUCTURAL
abstain in judge_merge.py — it never reaches the model, so no rubric judgment
or prompt injection can override it.

This set lives in the skill (user space), not in the target repo, so a
target-repo PR cannot shrink it. The globs still match the skill's own source
files (merge-guard/, finishing-a-development-branch/, the prompt/rubric) so a
self-hosting PR that edits them in-repo still trips the scan.

Matching is fnmatch over POSIX paths; a "/**/" style dir class is expressed as
a substring test so it matches at any depth regardless of repo layout.
Stdlib only.
"""
from __future__ import annotations

import fnmatch

# Glob patterns matched against each changed path (fnmatch, full-path).
_GLOBS = (
    "*project-config.toml",
    "*.env", "*.env.*", "*.env",
    "*credentials*", "*secret*", "*token*",
    "*.md.template",
    "*AGENTS.md", "*CLAUDE.md", "*GEMINI.md",
)

# Directory classes: a changed path is protected if any of these appears as a
# path segment substring (depth-independent, layout-independent).
_DIR_CLASSES = (
    "/merge-guard/", "merge-guard/",
    "/finishing-a-development-branch/", "finishing-a-development-branch/",
    "/.github/workflows/", ".github/workflows/",
    "/hooks/", "hooks/",
    "/packages/installer/", "packages/installer/",
    "/rules/", "rules/",
)

# Exact-ish filename classes (settings + routing + the judge prompt/rubric).
_NAME_GLOBS = (
    "*settings.json", "*settings.json.template",
    "*codex-routing.md",
    "*merge_judge_prompt.md", "*merge_judge_rubric*",
)


def scan_protected(changed_paths: list[str]) -> str | None:
    """Return the first changed path that hits a protected class, else None."""
    for path in changed_paths:
        p = path.strip()
        if not p:
            continue
        if any(fnmatch.fnmatch(p, g) for g in _GLOBS):
            return path
        if any(cls in ("/" + p) for cls in _DIR_CLASSES):
            return path
        if any(fnmatch.fnmatch(p, g) for g in _NAME_GLOBS):
            return path
    return None
