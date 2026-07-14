"""`viz pr <n>` — build the PR-shape artifact.

Reconcile the PR to its immutable head OID (fetch → resolve OIDs → scalar
reconcile against GitHub), build the estate at that head OID — never the
operator's ``HEAD`` checkout — then materialize the head snapshot from
`git archive` so scc scores per-file complexity against the committed tree (a
dirty working copy can never leak in). The load-bearing axis reads
`graphify-out/graph.json` from the **live working tree** (it is gitignored,
so it is never in the materialized snapshot), head-guarded by
`centrality_axis` itself; an absent/stale graph fails soft to an unavailable
axis, never a crash and never stale-as-fresh (§6.2). The three axes fuse into
one per-file heat (`scene.heat.combine`), thread into scene node attributes,
and the scene assembles into one self-contained HTML file at
`.viz/out/pr-<n>.html`.
"""

from __future__ import annotations

import shutil
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from vizsuite import __version__
from vizsuite.adapters.critical_paths import read_critical_paths
from vizsuite.adapters.scc.parse import parse_scc
from vizsuite.envelope import JsonValue
from vizsuite.extract.centrality import centrality_axis
from vizsuite.extract.complexity import complexity
from vizsuite.extract.consequence import consequence
from vizsuite.extract.estate import estate
from vizsuite.output import ensure_viz_dir
from vizsuite.reconcile.pr_scope import reconcile
from vizsuite.reconcile.snapshot import materialize
from vizsuite.runners import Runners
from vizsuite.scene import heat
from vizsuite.scene.assemble import assemble
from vizsuite.scene.model import RenderConfig
from vizsuite.templates.html import render_html


def pr(runners: Runners, args: Namespace) -> JsonValue:
    """Handle `viz pr <n>`: reconcile → head-OID estate → snapshot → scc → scene → HTML.

    Returns the envelope `data`: the written artifact path, the PR number, the
    estate node count, the reconciled net-file count, the number of files the
    complexity axis scored, and the heat axes that were available to combine.
    """
    pr_number: int = args.number
    scope = reconcile(pr_number, gh=runners.gh, git=runners.git)
    estate_map = estate(runners.git, scope.head_oid)

    # scc scans a *materialized* snapshot of the head tree, never the live
    # checkout, so a dirty working copy can't leak into the artifact; the snapshot
    # also carries `.critical-paths` for the consequence axis. Both snapshot-scored
    # axes (complexity, consequence) are scored before the tempdir is torn down; the
    # load-bearing axis is computed later from the live working tree (see below).
    snapshot = materialize(runners.git, scope.head_oid, set(estate_map))
    try:
        scc_records = parse_scc(runners.scc.scan(snapshot))
        complexity_scores = complexity(estate_map, scc_records, scope.files)
        critical_paths_lines = read_critical_paths(snapshot)
        consequence_scores = consequence(estate_map, critical_paths_lines)
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)

    # The load-bearing axis reads the LIVE working tree's `graphify-out/graph.json`
    # (gitignored — never in the materialized snapshot); `centrality_axis` itself
    # guards staleness against `scope.head_oid` and fails soft to unavailable.
    graph_path = Path.cwd() / "graphify-out" / "graph.json"
    centrality = centrality_axis(graph_path, scope.head_oid)
    heat_model = heat.combine(
        estate_map, complexity_scores, consequence_scores, centrality, set(scope.files)
    )

    scene = assemble(
        estate_map,
        pr_number=pr_number,
        generated_at=datetime.now(UTC).isoformat(),
        generator=f"vizsuite/{__version__}",
        base_oid=scope.base_oid,
        head_oid=scope.head_oid,
        attributes=heat_model.attributes,
        descriptors=heat_model.descriptors,
        render_config=RenderConfig(
            default_weights=heat_model.default_weights,
            unavailable_axes=heat_model.unavailable_axes,
        ),
        repo_nwo=scope.meta.repo_nwo,
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
        "heat_axes_available": cast(
            "list[JsonValue]",
            sorted(
                axis
                for axis in heat_model.default_weights
                if axis not in heat_model.unavailable_axes
            ),
        ),
    }
    return data
