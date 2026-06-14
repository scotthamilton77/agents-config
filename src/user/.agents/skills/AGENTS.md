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

**The provenance keys are audit grep-targets — never rename them.** Drift-audit tooling enumerates resync/lift candidates by grepping the literal keys (`Source: oss-snapshots`, `Drift policy:`). A skill that *amalgamates* — lifts specific patterns rather than resyncing byte-for-byte — keeps the same keys and encodes the amalgam semantics in the `Drift policy:` **value** (`selective-amalgamation`), never in a renamed key like `Amalgamation source:`. A renamed key silently drops the file from every future audit. If a new policy value is needed (e.g. `vendor-pinned`), add it to the enum above rather than inventing an ad-hoc key.

## Skill provenance registry

Skills built from scratch in-repo do not appear here. This table tracks only OSS-derived or OSS-influenced skills shipped from `src/user/.agents/skills/`.

| Skill | Snapshot path | Upstream | Last sync | Drift policy |
|-------|---------------|----------|-----------|--------------|
| `writing-skills` | `oss-snapshots/superpowers/writing-skills/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-17 | accept-periodic-resync |
| `writing-skills` | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-17 | accept-periodic-resync |
| `optimize-my-skill` | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-20 | accept-periodic-resync |
| `brainstorming` | `oss-snapshots/superpowers/brainstorming/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `finishing-a-development-branch` | `oss-snapshots/superpowers/finishing-a-development-branch/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `test-driven-development` | `oss-snapshots/superpowers/test-driven-development/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `using-git-worktrees` | `oss-snapshots/superpowers/using-git-worktrees/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `writing-plans` | `oss-snapshots/superpowers/writing-plans/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `improve-codebase-architecture` | `oss-snapshots/pocock/improve-codebase-architecture/` (pristine upstream; local extensions in deployed copy) | `mattpocock/skills @ e74f0061` | 2026-05-23 | rewrite-and-divorce (project-extended fork) |
| `grill-with-docs` | `oss-snapshots/pocock/grill-with-docs/` | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |
| `caveman` | `oss-snapshots/pocock/caveman/` (pristine upstream; local extensions in deployed copy) | `mattpocock/skills @ e74f0061` | 2026-05-23 | rewrite-and-divorce (project-extended fork) |
| `prototype` | `oss-snapshots/pocock/prototype/` | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |
| `writing-unit-tests` | `oss-snapshots/pocock/tdd/` (amalgamated deltas only) | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |
| `verify-checklist` | `oss-snapshots/superpowers/verification-before-completion/` (amalgamated lift only — Iron Law framing, gate function) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | accept-periodic-resync |
| `bugfix` | `oss-snapshots/superpowers/systematic-debugging/` (selective amalgamation — 3-strike escalation, multi-component boundary instrumentation lifted only) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | selective-amalgamation |
| `wait-for-pr-comments` | `oss-snapshots/superpowers/receiving-code-review/` (selective amalgamation — pushback discipline lifted into `references/handling-feedback.md`) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | selective-amalgamation |
| `reply-and-resolve-pr-threads` | `oss-snapshots/superpowers/receiving-code-review/` (selective amalgamation — host SKILL.md cites sibling `wait-for-pr-comments/references/handling-feedback.md` as the canonical pushback-discipline reference; no independent reference file) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | selective-amalgamation |

Update this table whenever a skill is added, replaced, or amalgamated from an OSS source.

### Claude-only OSS-derived skills

Skills whose Claude-specific features (`!`-command syntax, `disable-model-invocation`, `allowed-tools`) preclude shared deployment live under `src/user/.claude/skills/` instead. Their provenance is tracked here for cross-tree discoverability:

| Skill | Location | Snapshot path | Upstream | Last sync | Drift policy |
|-------|----------|---------------|----------|-----------|--------------|
| `handoff` | `src/user/.claude/skills/handoff/` | `oss-snapshots/pocock/handoff/` (pristine upstream; local extensions in deployed copy) | `mattpocock/skills @ e74f0061` | 2026-05-23 | rewrite-and-divorce (project-extended, Claude-specific) |
| `zoom-out` | `src/user/.claude/skills/zoom-out/` | `oss-snapshots/pocock/zoom-out/` | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |

## Common pitfall — extracted helpers must be wired in

When you extract a helper script out of in-model skill code, the live path keeps
using the in-model code until `SKILL.md` is rewired to invoke the helper. So
smoke tests, Copilot, and first-pass review can all pass while the helper chain
carries a latent, unexercised contract bug. Treat "helper added but not yet
invoked by `SKILL.md`" as a review smell, and drive the documented helper chain
end-to-end on a fixture before merging — an architecture-challenge review pass
catches these cross-file contract gaps that per-line review misses.

## Companion folders

- `<repo-root>/oss-snapshots/` — unmodified reference clones of upstream skill catalogs, pinned to specific commits. Each snapshot folder carries its own `AGENTS.md` documenting source repo, commit, and per-skill inventory.
- `src/user/.claude/skills/` — Claude-specific skills (depth-1 same rule). Skills shared across tools belong here; tool-specific skills belong there.
