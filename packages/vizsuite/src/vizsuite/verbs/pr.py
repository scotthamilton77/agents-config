"""`viz pr <n>` — build the PR-shape artifact.

Slice 2: reconcile the PR to its immutable head OID (fetch → resolve OIDs →
scalar reconcile against GitHub), then build the estate at that head OID — never
the operator's ``HEAD`` checkout — and assemble a heat-free scene into one
self-contained HTML file at `.viz/out/pr-<n>.html`. Slice 3+ thickens the heat
axes (consuming the reconciled net set + churn); slice 5 hardens the envelope.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from vizsuite import __version__
from vizsuite.envelope import JsonValue
from vizsuite.extract.estate import estate
from vizsuite.output import ensure_viz_dir
from vizsuite.reconcile.pr_scope import reconcile
from vizsuite.runners import Runners
from vizsuite.scene.assemble import assemble
from vizsuite.templates.html import render_html


def pr(runners: Runners, args: Namespace) -> JsonValue:
    """Handle `viz pr <n>`: reconcile → head-OID estate → scene → HTML on disk.

    Returns the envelope `data`: the written artifact path, the PR number, the
    estate node count, and the reconciled net-file count.
    """
    pr_number: int = args.number
    scope = reconcile(pr_number, gh=runners.gh, git=runners.git)
    estate_map = estate(runners.git, scope.head_oid)
    scene = assemble(
        estate_map,
        pr_number=pr_number,
        generated_at=datetime.now(UTC).isoformat(),
        generator=f"vizsuite/{__version__}",
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
    }
    return data
