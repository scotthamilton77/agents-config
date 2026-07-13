"""`.viz/` sidecar bootstrap — the portable, versioned output location.

`ensure_viz_dir` creates `<root>/.viz/out/` and writes a versioned
`<root>/.viz/.gitignore` containing `out/`. Committing that sidecar (not editing
the target repo's root `.gitignore`) makes `viz pr` portable: generated HTML is
ignored in *any* target repo. It ignores **only** `out/` — Tier-3 verdict
sidecars under `.viz/` are versioned and must stay tracked (none exist in .2.1).
"""

from __future__ import annotations

from pathlib import Path

_GITIGNORE_LINE = "out/"


def ensure_viz_dir(root: Path) -> Path:
    """Idempotently ensure `<root>/.viz/out/` exists and `.viz/.gitignore` ignores `out/`.

    Returns the `out/` directory. Safe to call repeatedly: the directory is
    created with `exist_ok`, and the `out/` ignore line is appended only when
    absent (existing `.viz/.gitignore` content is preserved).
    """
    viz_dir = root / ".viz"
    out_dir = viz_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    gitignore = viz_dir / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if _GITIGNORE_LINE not in existing.splitlines():
        prefix = existing if existing == "" or existing.endswith("\n") else existing + "\n"
        gitignore.write_text(f"{prefix}{_GITIGNORE_LINE}\n")
    return out_dir
