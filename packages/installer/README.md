# installer

uv-managed Python package that installs agent configurations into AI coding assistant homes (`~/.claude/`, `~/.codex/`, `~/.gemini/`, OpenCode XDG).

Replaces `scripts/install.sh`, which is now a thin `uv run` exec stub. Parity confirmed (H.3), golden-master suite retired (H.4). See [`docs/architecture/installer/installer-design.md`](../../docs/architecture/installer/installer-design.md) for the full Epic A→H history.

## Local development

From the repo root:

```bash
make ci-installer    # full quality gate (tests, lint, format-check, typecheck, coverage, audit, entry-verify)
make test-installer  # just pytest
```

First-time setup: `uv` auto-installs Python ≥3.11 if missing (one-time slow run; subsequent runs are fast).
