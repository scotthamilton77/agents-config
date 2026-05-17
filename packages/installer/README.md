# installer

uv-managed Python package that installs agent configurations into AI coding assistant homes (`~/.claude/`, `~/.codex/`, `~/.gemini/`, OpenCode XDG).

Replaces `scripts/install.sh` (which stays as the parity reference until the golden-master suite goes green; see [`docs/specs/2026-05-17-python-installer-rewrite.md`](../../docs/specs/2026-05-17-python-installer-rewrite.md)).

## Local development

From the repo root:

```bash
make ci-installer    # full quality gate (tests, lint, format-check, typecheck, coverage, audit, entry-verify)
make test-installer  # just pytest
```

First-time setup: `uv` auto-installs Python 3.11 if missing (one-time slow run; subsequent runs are fast).

## Status

A.1 (this milestone) ships only the package scaffold and the `--help`-printing CLI entry point. No installer behaviour yet. See the [parent spec](../../docs/specs/2026-05-17-python-installer-rewrite.md) for the full Epic A → H sequence.
