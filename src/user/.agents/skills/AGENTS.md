# src/user/.agents/skills/ — Shared Skill Sources

Source-of-truth for every skill that gets staged into each detected tool's user-space skills directory by `scripts/install.sh`. Edits here are what land in `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`, and `~/.config/opencode/skills/` on the next install run.

Staging is gated on admission: a `SKILL.md` without a complete `admission:` record (`prevents` **or** `provides`, plus `cost` and `remove_when`) in its front matter is dropped at deploy and pruned from every tool. Only admitted skills live in this folder; a skill awaiting admission, or retired after it, is not here at all.

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

**Never rename the provenance keys.** `Source: oss-snapshots` and `Drift policy:` are the literal strings a resync sweep greps for. A skill that *amalgamates* — lifts specific patterns rather than resyncing byte-for-byte — keeps the same keys and encodes the amalgam semantics in the `Drift policy:` **value** (`selective-amalgamation`), never in a renamed key like `Amalgamation source:`. If a new policy value is needed (e.g. `vendor-pinned`), add it to the enum above rather than inventing an ad-hoc key.

## Skill provenance registry

One row per OSS-derived or OSS-influenced skill that is **here now**. Skills built from
scratch in-repo do not appear. When a skill is retired, delete its row — the SKILL.md
carries its own provenance header with it wherever it goes, and git holds the rest.

| Skill | Location | Snapshot path | Upstream | Last sync | Drift policy |
|-------|----------|---------------|----------|-----------|--------------|
| `writing-skills` | shared | `oss-snapshots/superpowers/writing-skills/` | `obra/superpowers @ f2cbfbe` (v5.1.0) | 2026-05-17 | accept-periodic-resync |
| `writing-skills` | shared | `oss-snapshots/anthropics/skill-creator/` | `anthropics/skills @ f458cee` | 2026-05-17 | accept-periodic-resync |
| `grill-with-docs` | shared | `oss-snapshots/pocock/skills/skills/engineering/grill-with-docs/` | `mattpocock/skills @ e74f0061` | 2026-05-23 | local-fork |
| `grilling` | shared | `oss-snapshots/pocock/skills/skills/productivity/grilling/` | `mattpocock/skills @ e74f0061` | 2026-07-24 | local-fork |
| `to-spec` | shared | `oss-snapshots/pocock/skills/skills/engineering/to-spec/` | `mattpocock/skills @ e74f0061` | 2026-07-24 | local-fork |
| `handoff` | shared *(see below)* | `oss-snapshots/pocock/skills/skills/productivity/handoff/` (pristine upstream; local extensions in deployed copy) | `mattpocock/skills @ e74f0061` | 2026-05-23 | rewrite-and-divorce (project-extended, Claude-specific) |

Update this table whenever a skill is added, replaced, retired, or amalgamated from an OSS source.

`handoff` is the standing exception to the placement rule: it carries Claude-only front matter but sits in the shared tree, so it stages into Codex, Gemini and OpenCode where those keys do nothing. Deliberate and temporary — `agents-config-9k9.68` resolves it, either with per-tool exemption support or by moving the skill back.

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
