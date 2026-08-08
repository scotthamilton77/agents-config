# src/user/.agents/skills/ — Shared Skill Sources

Source-of-truth for every skill that gets staged into each detected tool's user-space skills directory by `scripts/install.sh`. Edits here are what land in `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`, and `~/.config/opencode/skills/` on the next install run.

Staging is gated on admission: a `SKILL.md` without a complete `admission:` record (`prevents` **or** `provides`, plus `cost` and `remove_when`) in its front matter is dropped at deploy and pruned from every tool. Only admitted skills live in this folder; a skill awaiting admission, or retired after it, is not here at all.

An admission record is necessary but not sufficient — a skill can hold a complete record and still fail a mechanical staging check, in which case it deploys nothing. Before telling anyone a skill is available, list the tool's own config directory and confirm it landed.

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
Source: <path to the skill inside the upstream repository>
Upstream: https://github.com/<owner>/<repo> @ <commit-sha>
Last sync: YYYY-MM-DD
Drift policy: <accept-periodic-resync | rewrite-and-divorce | local-fork | track-upstream | selective-amalgamation | ...>
-->

# My Skill
...
```

**Why HTML comments and not a co-located AGENTS.md.** Hosts do not read per-skill AGENTS.md files at runtime, and an in-folder note that travels with the SKILL.md is the only durable place for provenance that survives install staging. (See the provenance registry below for the project-wide rollup.)

**The pinned commit is the reference copy.** This repository vendored full upstream trees until 2026-08-05; it no longer does, because `Upstream` plus `Source` already identifies the exact bytes and a clone reproduces them on demand. To inspect drift, clone the upstream repository, check out the pinned SHA, and diff that against the deployed copy. When a skill is resynced to a newer upstream commit, bump the SHA and the `Last sync` date in its header in the same change.

That makes each row's accuracy load-bearing in a way it was not while a local copy existed. A pin that names a commit predating the skill it claims to source is not a stale convenience — it is the only record, and it is wrong. Verify a SHA by hashing the file you are pinning and finding the commit whose blob matches, not by picking a commit near the right date.

**Never rename the provenance keys.** The installer's sanitizer matches `Source:` and `Upstream:` by key name alone, case-insensitively, and never reads their values — so a key rename silently stops provenance being recognised, while a value's shape is free. A skill that *amalgamates* — lifts specific patterns rather than resyncing byte-for-byte — keeps the same keys and encodes the amalgam semantics in the `Drift policy:` **value** (`selective-amalgamation`), never in a renamed key like `Amalgamation source:`. If a new policy value is needed, add it to the enum above rather than inventing an ad-hoc key.

## Skill provenance registry

One row per OSS-derived or OSS-influenced artifact on the deployed surface — skills, and any
command or rule that came from the same sources, since the admission gate sends all of them
to this one table. Artifacts built from scratch in-repo do not appear. When one is retired,
delete its row — the file carries its own provenance header with it wherever it goes, and
git holds the rest.

**The table tracks `src/`, not the branch it is sitting on.** A wave of admissions arriving
as several PRs consolidates its rows here first, so that one file is not the conflict every
later merge has to resolve by hand. A row may therefore name an artifact that has not landed
on this branch yet. The obligation runs the other way and is unaffected: a retired artifact's
row goes, and a row for something that will never land is a defect, not a forward reference.

| Artifact | Location | Upstream | Path in upstream | Last sync | Drift policy |
|-------|----------|----------|------------------|-----------|--------------|
| `writing-skills` | shared | `obra/superpowers @ f2cbfbe` (v5.1.0) | `skills/writing-skills/` | 2026-05-17 | selective-amalgamation |
| `writing-skills` | shared | `anthropics/skills @ f458cee` | `skills/skill-creator/` | 2026-05-17 | selective-amalgamation |
| `writing-skills` | shared | `mattpocock/skills @ 4aaccb58` | `skills/productivity/writing-for-agents/` | 2026-08-07 | selective-amalgamation |
| `diagnosing-bugs` | shared | `mattpocock/skills @ bda79a3c` | `skills/engineering/diagnosing-bugs/` | 2026-08-07 | selective-amalgamation |
| `diagnosing-bugs` | shared | `obra/superpowers @ f2cbfbe` (v5.1.0) | `skills/systematic-debugging/` (two patterns only) | 2026-08-07 | selective-amalgamation |
| `grill-with-docs` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/grill-with-docs/` | 2026-08-07 | selective-amalgamation |
| `codebase-design` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/codebase-design/` | 2026-08-07 | accept-periodic-resync |
| `domain-modeling` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/domain-modeling/` | 2026-08-07 | local-fork |
| `wait-what` | shared | `mattpocock/skills @ 84fdeffd` | `skills/productivity/wait-what/` | 2026-08-07 | accept-periodic-resync |
| `tdd` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/tdd/` | 2026-08-07 | selective-amalgamation |
| `tdd` | shared | `obra/superpowers @ f2cbfbe` (v5.1.0) | `skills/test-driven-development/` | 2026-08-07 | selective-amalgamation |
| `test-review` | shared | `obra/superpowers @ f2cbfbe` (v5.1.0) | `skills/test-driven-development/testing-anti-patterns.md` | 2026-08-07 | selective-amalgamation |
| `grilling` | shared | `mattpocock/skills @ 84fdeffd` | `skills/productivity/grilling/` | 2026-08-07 | selective-amalgamation |
| `zoom-out` | claude (command) | `mattpocock/skills @ e74f0061` | `skills/engineering/zoom-out/` (deleted upstream after this commit) | 2026-08-07 | rewrite-and-divorce |
| `to-spec` | shared | `mattpocock/skills @ ed37663c` | `skills/engineering/to-spec/` | 2026-07-24 | local-fork |
| `handoff` | shared | `mattpocock/skills @ ed37663c` | `skills/productivity/handoff/` (pristine upstream; local extensions in deployed copy) | 2026-05-23 | rewrite-and-divorce (project-extended, Claude-specific) |
| `improve-codebase-architecture` | shared | `mattpocock/skills @ e74f006` | `skills/engineering/improve-codebase-architecture/` | 2026-05-23 | rewrite-and-divorce (project-extended fork) |
| `to-tickets` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/to-tickets/` | 2026-08-07 | local-fork |
| `research` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/research/` | 2026-08-07 | local-fork |
| `wayfinder` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/wayfinder/` | 2026-08-07 | local-fork |
| `prototype` | shared | `mattpocock/skills @ 84fdeffd` | `skills/engineering/prototype/` (SKILL.md, LOGIC.md, UI.md — the latter two deployed under `references/`) | 2026-08-07 | local-fork |
| `using-git-worktrees` | shared | `obra/superpowers @ f2cbfbe` (v5.1.0) | `skills/using-git-worktrees/` | 2026-08-07 | rewrite-and-divorce (detection moved into a shipped script; consent prompt removed) |
| `caveman` | claude | `mattpocock/skills @ e74f006` | `skills/productivity/caveman/` (present at the pin, removed upstream since — the pin is the only reference copy) | 2026-05-23 | rewrite-and-divorce (project-extended, user-invoked only) |
| `explain-diff` | claude | `scotthamilton77/claude-code-sidekick @ 44e57b6` | `assets/sidekick/personas/` — 17 of the upstream's 48 persona files, trimmed and re-emitted; the rest of the skill is authored in-repo | 2026-07-10 | local-fork |

Update this table whenever an artifact is added, replaced, retired, or amalgamated from an OSS source.

`Upstream` and `Path in upstream` together fetch the exact reference bytes. `Last sync` is a different fact — when the deployed copy was last reconciled against upstream — so it can legitimately predate the pinned commit, as `handoff`'s does. `zoom-out` is the opposite case: its path is gone from upstream's head, so the pin is the last commit that still holds the reference bytes and no later pin exists to move to.

Claude-only front matter is no longer a reason to leave the shared tree. The installer projects capability keys per target tool at deploy: `disable-model-invocation`, `allowed-tools` and `argument-hint` are kept for Claude and dropped for Codex, Gemini and OpenCode, which have no equivalent to translate onto. `handoff` was the standing exception to the placement rule and is now the ordinary case.

Placement still turns on capability-dependency, but of the skill's *procedure* rather than its front matter. A skill whose steps require a Claude-only mechanism belongs in the Claude tree. So does one whose admission record depends on behaviour the other tools cannot reproduce — dropping a key removes the bytes, not the gap, so a skill that must not fire unprompted is still model-invocable wherever the flag is unsupported.

## Common pitfall — extracted helpers must be wired in

When you extract a helper script out of in-model skill code, the live path keeps
using the in-model code until `SKILL.md` is rewired to invoke the helper. So
smoke tests, Copilot, and first-pass review can all pass while the helper chain
carries a latent, unexercised contract bug. Treat "helper added but not yet
invoked by `SKILL.md`" as a review smell, and drive the documented helper chain
end-to-end on a fixture before merging — an architecture-challenge review pass
catches these cross-file contract gaps that per-line review misses.

## Companion folders

- `src/user/.claude/skills/` — skills that depend on Claude-only capabilities (depth-1 same rule). Placement is by capability-dependency: a skill that works on every supported tool belongs in **this** folder; one that needs a Claude-specific capability belongs in **that** one.
