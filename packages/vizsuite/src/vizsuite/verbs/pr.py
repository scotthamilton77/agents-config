"""`viz pr <n>` — build the PR-shape artifact.

Reconcile the PR to its immutable head OID (fetch → resolve OIDs → scalar
reconcile against GitHub), build the estate at that head OID — never the
operator's ``HEAD`` checkout — then materialize the head snapshot from
`git archive` so scc scores per-file complexity against the committed tree (a
dirty working copy can never leak in). The heat-free scene is assembled into one
self-contained HTML file at `.viz/out/pr-<n>.html`. Threading the per-file heat
values into scene node attributes + the cross-axis fusion is `.2.2` (§6.2); this
verb delivers the extraction layer and proves the snapshot→scc plumbing.
"""

from __future__ import annotations

import shutil
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from vizsuite import __version__
from vizsuite.adapters.scc.parse import parse_scc
from vizsuite.envelope import JsonValue
from vizsuite.extract.complexity import complexity
from vizsuite.extract.consequence import consequence
from vizsuite.extract.estate import estate
from vizsuite.output import ensure_viz_dir
from vizsuite.reconcile.pr_scope import reconcile
from vizsuite.reconcile.snapshot import materialize
from vizsuite.runners import Runners
from vizsuite.scene.assemble import assemble
from vizsuite.templates.html import render_html


def pr(runners: Runners, args: Namespace) -> JsonValue:
    """Handle `viz pr <n>`: reconcile → head-OID estate → snapshot → scc → scene → HTML.

    Returns the envelope `data`: the written artifact path, the PR number, the
    estate node count, the reconciled net-file count, and the number of files the
    complexity axis scored.
    """
    pr_number: int = args.number
    scope = reconcile(pr_number, gh=runners.gh, git=runners.git)
    estate_map = estate(runners.git, scope.head_oid)

    # scc scans a *materialized* snapshot of the head tree, never the live
    # checkout, so a dirty working copy can't leak into the artifact; the snapshot
    # also carries `.critical-paths` for the consequence axis. Both heat axes are
    # scored before the tempdir is torn down. The per-file heat values thread into
    # scene node attributes in `.2.2` (§6.2); scoring them here proves the
    # snapshot→scc→complexity and snapshot→consequence chains end-to-end on real data.
    snapshot = materialize(runners.git, scope.head_oid, set(estate_map))
    try:
        scc_records = parse_scc(runners.scc.scan(snapshot))
        complexity_scores = complexity(estate_map, scc_records, scope.files)
        consequence_scores = consequence(estate_map, snapshot)
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)

    scene = assemble(
        estate_map,
        pr_number=pr_number,
        generated_at=datetime.now(UTC).isoformat(),
        generator=f"vizsuite/{__version__}",
        base_oid=scope.base_oid,
        head_oid=scope.head_oid,
    )
    html = render_html(scene)

    out_dir = ensure_viz_dir(Path.cwd())
    artifact = out_dir / f"pr-{pr_number}.html"
    artifact.write_text(html, encoding="utf-8")

    data: dict[str, JsonValue] = {
        "pr": pr_number,
        "artifact": str(artifact),
        "nodes": len(estate_map),
        "net_files": len(scope.files),
        "scored_files": len(complexity_scores),
        "consequential_files": sum(1 for value in consequence_scores.values() if value > 0),
        "author": scope.meta.author,
        "review_state": scope.meta.review_state,
    }
    return data
