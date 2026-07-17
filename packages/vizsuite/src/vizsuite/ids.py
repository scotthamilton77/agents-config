"""Shared deterministic-id helper: `{prefix}-{sha256(content)[:16]}`.

Four call sites mint an id this exact way — `reconcile.content_fact_id`
(`fact-...`), `funnel.rungs._restamped_basis_hash` (`basis-...`),
`verbs.sweep._mint_flag_id` (`flag-...`), and `verbs.verdict._mint_orphan_flag_id`
(`flag-orphaned-edge-...`). These ids are persisted in `.viz/` sidecar records,
so this helper's exact digest-truncation behavior is load-bearing: any change
here changes every id already on disk.
"""

from __future__ import annotations

import hashlib


def deterministic_id(prefix: str, content: str) -> str:
    """`{prefix}-{sha256(content.encode("utf-8")).hexdigest()[:16]}`."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:16]}"
