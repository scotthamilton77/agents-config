#!/usr/bin/env python3
"""model_family.py — map an AI model name to its provider family.

Shared by resolve_policy.py (validates a judge-model family is derivable) and
judge_merge.py (derives the judge's family to enforce the cross-model rule).
Stdlib only — co-deploys with the merge-guard skill into user space.

Families are the same vocabulary the provenance record uses for
author_families: "anthropic" | "openai" | "google". Returns None for a model
whose family cannot be derived — the caller treats that as fail-closed.
"""
from __future__ import annotations

_PREFIXES = (
    ("openai", ("gpt-", "o1", "o3", "o4", "chatgpt")),
    ("anthropic", ("claude",)),
    ("google", ("gemini",)),
)


def family_of(model: str) -> str | None:
    """Best-effort provider family from a model name. None if underivable."""
    m = (model or "").strip().lower()
    for family, prefixes in _PREFIXES:
        if m.startswith(prefixes):
            return family
    return None
