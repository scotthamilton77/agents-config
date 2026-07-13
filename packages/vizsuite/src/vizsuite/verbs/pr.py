"""`viz pr <n>` — build the PR-shape artifact.

Slice 1 walking skeleton: extract the estate at ``HEAD`` → assemble a heat-free
scene → render one self-contained HTML file into `.viz/out/pr-<n>.html`. Slice 2
replaces the ``HEAD`` estate with the reconciled PR head-OID estate (fetch →
resolve OIDs → scalar reconcile) and slice 3+ thickens the heat axes.
"""

from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from vizsuite import __version__
from vizsuite.envelope import JsonValue
from vizsuite.extract.estate import estate
from vizsuite.output import ensure_viz_dir
from vizsuite.runners import Runners
from vizsuite.scene.assemble import assemble
from vizsuite.templates.html import render_html


def pr(runners: Runners, args: Namespace) -> JsonValue:
    """Handle `viz pr <n>`: estate → scene → HTML artifact on disk.

    Returns the envelope `data`: the written artifact path, the PR number, and
    the estate node count.
    """
    pr_number: int = args.number
    estate_map = estate(runners.git, "HEAD")
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
    }
    return data
