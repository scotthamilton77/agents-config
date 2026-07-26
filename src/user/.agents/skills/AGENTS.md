# src/user/.agents/skills/ — Shared Skill Sources

Source-of-truth for every skill that gets staged into each detected tool's user-space skills directory by `scripts/install.sh`. Edits here are what land in `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`, and `~/.config/opencode/skills/` on the next install run.

Staging is gated on admission: a `SKILL.md` without a complete `admission:` record (`prevents` **or** `provides`, plus `cost` and `remove_when`) in its front matter is dropped at deploy and pruned from every tool. Only admitted skills live in this folder; skills awaiting or past admission live under `archive/src/user/**`.

An admission record is necessary but not sufficient — a skill can hold a complete record and still fail a mechanical staging check, in which case it deploys nothing. Before telling anyone a skill is available, list the tool's own config directory and confirm it landed. `writing-skills` is in exactly that state today (it exceeds the file-size limit and carries an `exemption:` key the installer does not yet honour); `agents-config-9k9.68` tracks it.

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

Skills built from scratch in-repo do not appear here. This table tracks OSS-derived or OSS-influenced skills by name, whether they currently live in `src/user/.agents/skills/` or under `archive/src/user/**`. Archived rows are retained deliberately: a skill readmitted later must carry its provenance forward, and the drift-audit grep-targets have to keep resolving. The `Skill` column names an artifact, not a live `src/` path.

| Skill | Snapshot path | Upstream | Last sync | Drift policy |
|-------|---------------|----------|-----------|--------------|
| `writing-skills` | `oss-snapshots/superpowers/writing-skills/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-17 | accept-periodic-resync |
| `writing-skills` | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-17 | accept-periodic-resync |
| `optimize-my-skill` | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-20 | accept-periodic-resync |
| `finishing-a-development-branch` | `oss-snapshots/superpowers/finishing-a-development-branch/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `test-driven-development` | `oss-snapshots/superpowers/test-driven-development/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `using-git-worktrees` | `oss-snapshots/superpowers/using-git-worktrees/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-23 | accept-periodic-resync |
| `improve-codebase-architecture` | `oss-snapshots/pocock/skills/skills/engineering/improve-codebase-architecture/` (pristine upstream; local extensions in deployed copy) | `mattpocock/skills @ e74f0061` | 2026-05-23 | rewrite-and-divorce (project-extended fork) |
| `grill-with-docs` | `oss-snapshots/pocock/skills/skills/engineering/grill-with-docs/` | `mattpocock/skills @ e74f0061` | 2026-05-23 | local-fork |
| `grilling` | `oss-snapshots/pocock/skills/skills/productivity/grilling/` | `mattpocock/skills @ e74f0061` | 2026-07-24 | local-fork |
| `to-spec` | `oss-snapshots/pocock/skills/skills/engineering/to-spec/` | `mattpocock/skills @ e74f0061` | 2026-07-24 | local-fork |
| `caveman` | repo-owned (upstream removed the skill; detached 2026-07-24) | `mattpocock/skills @ e74f0061` (historical origin) | 2026-05-23 | rewrite-and-divorce |
| `prototype` | `oss-snapshots/pocock/skills/skills/engineering/prototype/` | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |
| `writing-unit-tests` | `oss-snapshots/pocock/skills/skills/engineering/tdd/` (amalgamated deltas only) | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |
| `verify-checklist` | `oss-snapshots/superpowers/verification-before-completion/` (amalgamated lift only — Iron Law framing, gate function) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | accept-periodic-resync |
| `bugfix` | `oss-snapshots/superpowers/systematic-debugging/` (selective amalgamation — 3-strike escalation, multi-component boundary instrumentation lifted only) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | selective-amalgamation |
| `wait-for-pr-comments` | `oss-snapshots/superpowers/receiving-code-review/` (selective amalgamation — pushback discipline lifted into the skill's own `references/` folder) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | selective-amalgamation |
| `reply-and-resolve-pr-threads` | `oss-snapshots/superpowers/receiving-code-review/` (selective amalgamation — host SKILL.md cites the sibling `wait-for-pr-comments` reference rather than carrying its own) | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-24 | selective-amalgamation |

Update this table whenever a skill is added, replaced, or amalgamated from an OSS source.

### Claude-dependent OSS-derived skills

A skill whose Claude-only features (`!`-command syntax, `disable-model-invocation`, `allowed-tools`) would be inert or broken on the other tools belongs under `src/user/.claude/skills/`. Provenance for those is tracked here for cross-tree discoverability:

| Skill | Location | Snapshot path | Upstream | Last sync | Drift policy |
|-------|----------|---------------|----------|-----------|--------------|
| `handoff` | `src/user/.agents/skills/handoff/` | `oss-snapshots/pocock/skills/skills/productivity/handoff/` (pristine upstream; local extensions in deployed copy) | `mattpocock/skills @ e74f0061` | 2026-05-23 | rewrite-and-divorce (project-extended, Claude-specific) |
| `zoom-out` | `archive/src/user/.claude/skills/zoom-out/` | formerly `oss-snapshots/pocock/zoom-out/`, snapshot removed 2026-07-24; upstream no longer ships it | `mattpocock/skills @ e74f0061` | 2026-05-23 | accept-periodic-resync |

`handoff` is the standing exception: it carries Claude-only front matter but sits in the shared tree, so it stages into Codex, Gemini and OpenCode where those keys do nothing. That placement is deliberate and temporary — `agents-config-9k9.68` resolves it, either with per-tool exemption support or by moving the skill back.

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
- `src/user/.claude/skills/` — skills that depend on Claude-only capabilities (depth-1 same rule). Placement is by capability-dependency: a skill that works on every supported tool belongs in **this** folder; one that needs a Claude-specific capability belongs in **that** one.
