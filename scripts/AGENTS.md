# `scripts/` — installer entry points

The installer logic lives in the Python package `packages/installer/`. This
directory holds only thin entry points into it.

- **`install.sh`** — a 6-line `exec uv run --project packages/installer python -m
  installer "$@"` stub. It is **not** the behavioural spec anymore; the earlier
  74 KB bash implementation (and its golden-master parity suite) was retired once
  the Python port reached parity. Do not add logic here — it belongs in
  `packages/installer/`.
- **`install.py`** — the Python entry point (`from installer.cli import main`);
  also invocable as `uv run python -m installer`.
- **`bootstrap-installer-beads.sh`** — one-time bootstrap helper for standing up
  the installer + beads on a fresh machine.

All installer behaviour, design principles, and the mandatory quality gate are
documented in `packages/installer/AGENTS.md`. Never run any of these scripts
automatically — only the user runs the installer, and only when they explicitly
ask.
