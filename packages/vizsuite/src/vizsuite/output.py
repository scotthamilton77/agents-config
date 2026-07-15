"""`.viz/` sidecar bootstrap — the portable, versioned output location.

`ensure_viz_dir` creates `<root>/.viz/out/` and, via the shared
`ensure_viz_gitignore` helper, writes a versioned `<root>/.viz/.gitignore`
ignoring the machine-managed sidecar entries (`lock`, `out/`). Committing that
sidecar (not editing the target repo's root `.gitignore`) makes `viz pr`
portable: generated HTML and the advisory lock are ignored in *any* target
repo. Only the managed entries are ignored — Tier-3 verdict sidecars under
`.viz/` are versioned and must stay tracked (none exist in .2.1).

`ensure_viz_gitignore` is the single owner of `.viz/.gitignore` maintenance,
shared by both sidecar writers (this module and `vizsuite.sidecar.store`), so
the file is byte-identical regardless of which command runs first.
"""

from __future__ import annotations

from pathlib import Path

# The machine-managed `.viz/.gitignore` entries, in canonical (alphabetical)
# order. Both sidecar writers install the *complete* set through
# `ensure_viz_gitignore`, so whichever runs first produces an identical file.
_MANAGED_GITIGNORE_LINES = ("lock", "out/")


def ensure_viz_gitignore(viz_dir: Path) -> None:
    """Idempotently ensure `<viz_dir>/.gitignore` ignores every managed entry.

    The single owner of `.viz/.gitignore` maintenance, shared by both sidecar
    writers. Creates `viz_dir` if needed, reads the existing `.gitignore`
    (empty if absent), and appends every managed entry (`lock`, `out/`) that is
    absent — in one write, in canonical order — while preserving any existing
    lines and never reordering them.

    Convergence: whichever writer runs first installs the complete managed set,
    so the resulting file is byte-identical regardless of call order.
    Idempotent: a second call with all entries already present is a no-op
    (byte-stable).
    """
    viz_dir.mkdir(parents=True, exist_ok=True)
    gitignore = viz_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = existing.splitlines()
    missing = [entry for entry in _MANAGED_GITIGNORE_LINES if entry not in lines]
    if not missing:
        return
    prefix = existing if existing == "" or existing.endswith("\n") else existing + "\n"
    gitignore.write_text(prefix + "".join(f"{entry}\n" for entry in missing), encoding="utf-8")


def ensure_viz_dir(root: Path) -> Path:
    """Idempotently ensure `<root>/.viz/out/` exists and `.viz/.gitignore` is managed.

    Returns the `out/` directory. Safe to call repeatedly: the directory is
    created with `exist_ok`, and the managed ignore entries are appended only
    when absent (existing `.viz/.gitignore` content is preserved).
    """
    viz_dir = root / ".viz"
    out_dir = viz_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_viz_gitignore(viz_dir)
    return out_dir
