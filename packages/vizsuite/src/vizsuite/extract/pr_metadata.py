"""PR metadata extractor — author/review-state/timestamps (spec §4.4, slice 5).

Tier-1 (deterministic): a widened `gh pr view --json` call, distinct from the
OID-reconciliation graphql query (slice 2) — this one is metadata-only garnish,
never part of the reconciler's drift-critical scalar join. Mirrors the
adapter/parse split of `reconcile.pr_scope`/`adapters.gh.parse.parse_pr_view`.
"""

from __future__ import annotations

from vizsuite.adapters.gh.parse import PrMeta, parse_pr_meta
from vizsuite.adapters.gh.runner import GhRunner


def pr_metadata(gh: GhRunner, pr_number: int) -> PrMeta:
    """Fetch and parse the PR's author/review-state/timestamps."""
    return parse_pr_meta(gh.pr_meta(pr_number), pr_number=pr_number)
