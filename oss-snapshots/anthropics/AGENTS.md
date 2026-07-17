# anthropics/ — Plugins from anthropics/claude-plugins-official

## What this is

Plugins and skills brought in from Anthropic's official public Claude Code plugin repo. Three plugins are adopted: `code-review`, `code-simplifier`, and `skill-creator` — the rest of the marketplace is out of scope for this project.

## Source

- **Repo**: https://github.com/anthropics/claude-plugins-official
- **Last refreshed**: 2026-07-17
- **Source paths**: `code-review/`, `code-simplifier/`, `skill-creator/`

Note: this repo supersedes the earlier standalone `anthropics/skills` repo this folder was previously sourced from — `skill-creator` moved from a flat `skills/skill-creator/` layout to a full plugin package (`.claude-plugin/plugin.json`, `LICENSE`, `README.md`, `skills/skill-creator/`). This is packaging only: a byte-for-byte diff against the prior committed snapshot confirms `SKILL.md` and every supporting file (`agents/*.md`, `scripts/*.py`, `eval-viewer/*`, `references/schemas.md`) are unchanged content — the eval/grading/benchmarking tooling was already present in the prior snapshot, not newly added here. `LICENSE.txt` was renamed to `LICENSE` in the move.

## Plugins

| Plugin | Contents | Modification notes |
|--------|----------|--------------------|
| `code-review` | `commands/code-review.md` | Copied as-is. Not installed/wired into `src/` — reference only. |
| `code-simplifier` | `agents/code-simplifier.md` | Copied as-is. Not installed/wired into `src/` — reference only. |
| `skill-creator` | `skills/skill-creator/` (SKILL.md, agents/, eval-viewer/, references/, scripts/) | Copied as-is. See amalgamation note below. |

## Out of scope (not brought in)

The rest of the `claude-plugins-official` marketplace — UI/artifact/integration-focused plugins and any not relevant to this project's discipline-layer mission.

## Notes

- Namespace folder is `anthropics/` (matches the GitHub org, spanning multiple source repos over time).
- `skill-creator` was amalgamated into two in-tree skills: `src/user/.agents/skills/writing-skills/` (creation/editing methodology) and `src/user/.agents/skills/optimize-my-skill/` (audit methodology). Provenance is recorded in each host SKILL.md's HTML-comment header and in the project-wide registry at `src/user/.agents/skills/AGENTS.md`. `optimize-my-skill` already carries the eval/grading/benchmarking machinery (`agents/`, `eval-viewer/`, `scripts/run_eval.py`, `scripts/run_loop.py`, `scripts/aggregate_benchmark.py`, etc.) byte-for-byte identical to this refresh's content — no resync action needed. Both host SKILL.md provenance comments still cite the superseded `anthropics/skills @ f458cee...` URL; update to point at `anthropics/claude-plugins-official` next time either file is touched for an unrelated reason.
- `code-review` and `code-simplifier` are newly snapshotted and not yet cross-referenced against any in-tree equivalent (this repo already has its own `quality-reviewer` agent and `simplify` skill) — adoption analysis is future work, not yet done.
