# src/user/.agents/skills/ — Shared Skill Sources

Source-of-truth for every skill that gets staged into each detected tool's user-space skills directory by `scripts/install.sh`. Edits here are what land in `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`, and `~/.config/opencode/skills/` on the next install run.

## Layout — flat, depth-1 only

Every immediate subdirectory of this folder is exactly one skill. Skills MUST NOT be nested under organizational subfolders.

```
skills/
├── <skill-name>/
│   ├── SKILL.md          (required; YAML frontmatter `name:` must match folder name)
│   ├── scripts/          (optional — executable helpers)
│   ├── references/       (optional — context-loaded docs)
│   └── assets/           (optional — templates, fonts, output materials)
└── ...
```

**Why depth-1.** All four target runtimes (Claude Code, Codex CLI, Gemini CLI, OpenCode) only discover skills one level deep. Anything nested deeper is invisible to the runtime — verified against each tool's official discovery docs (May 2026). Codex CLI's `.system/` exception is OpenAI-owned and not extensible by us.

## OSS provenance requirement

Skills derived from, or borrowing substantively from, third-party open-source sources MUST carry an HTML-comment provenance header at the top of `SKILL.md`, immediately after the YAML frontmatter close:

```markdown
---
name: my-skill
description: ...
---

<!--
Source: oss-snapshots/<snapshot-folder>/<path-to-original-skill>
Upstream: https://github.com/<owner>/<repo> @ <commit-sha>
Last sync: YYYY-MM-DD
Drift policy: <accept-periodic-resync | rewrite-and-divorce | track-upstream | ...>
-->

# My Skill
...
```

**Why HTML comments and not a co-located AGENTS.md.** Hosts do not read per-skill AGENTS.md files at runtime, and an in-folder note that travels with the SKILL.md is the only durable place for provenance that survives install staging. (See the provenance registry below for the project-wide rollup.)

The full unmodified upstream artifacts live under `<repo-root>/oss-snapshots/<snapshot-folder>/`. To inspect drift between an upstream snapshot and a modified deployed copy, `diff` the two trees. When a snapshot is refreshed to a newer upstream commit, bump the commit SHA and `Last sync` date in the deployed skill's header in the same change.

## Skill provenance registry

Skills built from scratch in-repo do not appear here. This table tracks only OSS-derived or OSS-influenced skills shipped from `src/user/.agents/skills/`.

| Skill | Snapshot path | Upstream | Last sync | Drift policy |
|-------|---------------|----------|-----------|--------------|
| `writing-skills` | `oss-snapshots/superpowers/writing-skills/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-17 | accept-periodic-resync |
| `writing-skills` | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-17 | accept-periodic-resync |
| `optimize-my-skill` | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-20 | accept-periodic-resync |

Update this table whenever a skill is added, replaced, or amalgamated from an OSS source.

## Companion folders

- `<repo-root>/oss-snapshots/` — unmodified reference clones of upstream skill catalogs, pinned to specific commits. Each snapshot folder carries its own `AGENTS.md` documenting source repo, commit, and per-skill inventory.
- `src/user/.claude/skills/` — Claude-specific skills (depth-1 same rule). Skills shared across tools belong here; tool-specific skills belong there.
