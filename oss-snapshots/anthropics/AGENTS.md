# anthropics/ — Skills from anthropics/skills

## What this is

Skills brought in from Anthropic's official public skills repo. Only `skill-creator` was adopted — the remaining skills in the source repo are UI/artifact-focused (canvas, frontend-design, pptx, xlsx, etc.) and out of scope for this project.

## Source

- **Repo**: https://github.com/anthropics/skills
- **Commit**: `f458cee31a7577a47ba0c9a101976fa599385174`
- **Last refreshed**: 2026-05-17
- **Source path**: `skills/skill-creator/`

## Skills

| Skill | Modification notes |
|-------|-------------------|
| `skill-creator/SKILL.md` | Copied as-is from source |

## Out of scope (not brought in)

The following skills exist in the source repo but were not adopted — all are UI/artifact/integration-focused and not relevant to this project's discipline-layer mission:

`algorithmic-art`, `brand-guidelines`, `canvas-design`, `claude-api`, `doc-coauthoring`, `docx`, `frontend-design`, `internal-comms`, `mcp-builder`, `pdf`, `pptx`, `slack-gif-creator`, `theme-factory`, `web-artifacts-builder`, `webapp-testing`, `xlsx`

## Notes

- Namespace folder is `anthropics/` (renamed mid-cycle to match the actual GitHub org, replacing an earlier `claude-plugins-official/` label).
- `skill-creator` was amalgamated into two in-tree skills: `src/user/.agents/skills/writing-skills/` (creation/editing methodology) and `src/user/.agents/skills/optimize-my-skill/` (audit methodology). Provenance is recorded in each host SKILL.md's HTML-comment header and in the project-wide registry at `src/user/.agents/skills/AGENTS.md`.
